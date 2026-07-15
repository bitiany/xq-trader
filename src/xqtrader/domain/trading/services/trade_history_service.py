"""历史交易查询服务 — 通过 QMT export_data 接口查询历史成交、委托与持仓。"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from typing import Any

import pandas as pd

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from xqtrader.broker.services.qmt_service_base import QmtServiceBase

logger = get_logger(__name__)

# QMT export_data 支持的 data_type
_DATA_TYPE_DEAL = "deal"
_DATA_TYPE_ORDER = "order"
_DATA_TYPE_POSITION = "position"

# 历史查询超时（秒）：CSV 导出可能较慢
_HISTORY_TIMEOUT: float = 15.0

# QMT DataFrame 中证券代码的常见列名（按优先级）
_STOCK_CODE_COLUMNS = ("stock_code", "StockCode", "code", "security_code")


class TradeHistoryService(QmtServiceBase):
    """历史交易查询 — 通过 QMT export_data 接口查询历史成交/委托/持仓。

    使用 QMT 的 export_data 而非 query_data，自行控制 CSV 文件生命周期，
    确保 finally 中清理临时文件，避免超时/异常时残留。

    数据为实盘真实操作记录（非模拟盘），直接来自券商。
    """

    async def query_historical_trades(
        self,
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查询历史成交记录。"""
        return await self._query_and_filter(
            data_type=_DATA_TYPE_DEAL,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    async def query_historical_orders(
        self,
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查询历史委托记录。"""
        return await self._query_and_filter(
            data_type=_DATA_TYPE_ORDER,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    async def query_position_snapshots(
        self,
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        """查询持仓快照历史。"""
        return await self._query_and_filter(
            data_type=_DATA_TYPE_POSITION,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    async def _query_and_filter(
        self,
        data_type: str,
        symbol: str | None,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """通用查询+过滤逻辑（消除三方法重复）。"""
        df = await self._export_data(
            data_type=data_type,
            start_time=_fmt_date(start_date) if start_date else None,
            end_time=_fmt_date(end_date) if end_date else None,
        )
        if df is None or df.empty:
            return []
        if symbol:
            code_col = _find_stock_code_column(df)
            if code_col is not None:
                df = df[df[code_col] == symbol]
            else:
                logger.warning(
                    "QMT %s 数据缺少证券代码列，跳过 symbol 过滤: columns=%s",
                    data_type,
                    list(df.columns)[:10],
                )
        df = df.head(limit)
        return _df_to_records(df)

    async def _export_data(
        self,
        data_type: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> pd.DataFrame | None:
        """调用 QMT export_data 导出 CSV，自行读取并清理。

        使用 export_data 而非 query_data，因为 query_data 内部虽然会
        读取并删除 CSV，但超时时线程仍在运行，无法保证清理。
        改为 export_data + 自行 pd.read_csv + finally os.remove，
        从根源避免临时文件残留。
        """
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        tmp_dir = tempfile.gettempdir()
        result_path = os.path.join(
            tmp_dir,
            f"xqtrader_history_{data_type}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.csv",
        )

        try:
            result = await self._call_sync_with_timeout(
                trader.export_data,
                (account, result_path, data_type, start_time, end_time),
                timeout=_HISTORY_TIMEOUT,
                operation_name=f"导出历史{data_type}",
            )
        except BusinessException:
            logger.warning(
                "QMT 历史 %s 导出超时或失败", data_type, exc_info=True,
            )
            return None

        if isinstance(result, dict) and "error" in result:
            error_msg = result.get("error", {})
            logger.warning(
                "QMT 历史 %s 导出返回错误: %s", data_type, error_msg,
            )
            return None

        # export_data 成功后自行读取 CSV
        if not os.path.exists(result_path):
            logger.warning(
                "QMT 历史 %s 导出成功但 CSV 不存在: %s",
                data_type,
                result_path,
            )
            return None

        try:
            df = pd.read_csv(result_path)
            return df
        except Exception:
            logger.error(
                "QMT 历史 %s CSV 读取失败: %s",
                data_type,
                result_path,
                exc_info=True,
            )
            return None
        finally:
            # 无论成功还是异常，都清理临时文件
            self._safe_remove(result_path)

    @staticmethod
    def _safe_remove(path: str) -> None:
        """安全删除临时文件，失败时仅记 warning。"""
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.warning("临时文件清理失败: %s", path, exc_info=True)


def _fmt_date(d: date) -> str:
    """将 date 格式化为 QMT 需要的时间字符串。"""
    return d.strftime("%Y%m%d")


def _find_stock_code_column(df: pd.DataFrame) -> str | None:
    """在 DataFrame 中查找证券代码列名。

    QMT 不同版本或 data_type 可能使用不同的列名，
    按优先级依次尝试，避免硬编码导致 KeyError。
    """
    for col in _STOCK_CODE_COLUMNS:
        if col in df.columns:
            return col
    return None


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """将 DataFrame 转换为 list[dict]，处理 NaN 值。"""
    cleaned = df.where(df.notna(), other=None)  # type: ignore[call-overload]
    return list(cleaned.to_dict(orient="records"))  # type: ignore[arg-type]
