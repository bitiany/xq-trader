"""Tushare 数据采集服务 — 封装 tushare pro_api 数据采集接口。

核心模式：通过 tushare pro_api 获取数据，asyncio.to_thread 适配异步框架。
所有 tushare 接口调用均为同步 HTTP 请求，通过线程池桥接为异步。
内置令牌桶限流器，控制 API 调用频率（默认 500 次/分钟）。
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pandas as pd
import tushare as ts  # type: ignore[import-untyped]

from framework.commons.exceptions import DataCollectionError
from framework.commons.logger import get_logger
from framework.commons.utils.rate_limiter import SlidingWindowLimiter

logger = get_logger(__name__)

# tushare 限流：500 次/分钟（滑动窗口）
# 任意60秒内请求数不超过480（留20次余量避免边界误差）
_TUSHARE_MAX_REQUESTS = 480
_TUSHARE_WINDOW_SECONDS = 60.0


class TushareDataCollector:
    """Tushare 数据采集服务。

    封装 tushare pro_api，提供个股资金流向等数据采集能力。
    tushare 接口为同步 HTTP 调用，通过 asyncio.to_thread 适配异步框架。
    内置滑动窗口限流器，每次 API 调用前自动 acquire 许可。
    使用独立线程池（max_workers=3），避免默认线程池过大导致并发超限。
    """

    _THREAD_POOL: ThreadPoolExecutor | None = None

    def __init__(
        self,
        max_requests: int = _TUSHARE_MAX_REQUESTS,
        window_seconds: float = _TUSHARE_WINDOW_SECONDS,
    ) -> None:
        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            logger.warning("TUSHARE_TOKEN 未配置，tushare 接口将不可用")
        ts.set_token(token)
        self._pro = ts.pro_api()
        self._limiter = SlidingWindowLimiter(max_requests=max_requests, window_seconds=window_seconds)
        logger.info(
            "TushareDataCollector 初始化: 滑动窗口限流 max=%d/%.0fs",
            max_requests, window_seconds,
        )

    @classmethod
    def _get_executor(cls) -> ThreadPoolExecutor:
        """获取共享线程池（懒初始化，max_workers=20）。"""
        if cls._THREAD_POOL is None:
            cls._THREAD_POOL = ThreadPoolExecutor(max_workers=20, thread_name_prefix="tushare")
        return cls._THREAD_POOL

    async def fetch_moneyflow_dc(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取东方财富个股资金流向数据。

        接口：moneyflow_dc
        限制：单次最大 6000 条，需 5000 积分

        Args:
            ts_code: 股票代码，如 "002149.SZ"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/close/pct_change/net_amount 等字段
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.moneyflow_dc,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "moneyflow_dc 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "moneyflow_dc 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"moneyflow_dc 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e

    async def fetch_moneyflow(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取 tushare 原生个股资金流向数据。

        接口：moneyflow
        限制：单次最大 6000 条
        字段：买卖量/金额（手/万元），无占比字段

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/buy_sm_amount/sell_sm_amount 等字段
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.moneyflow,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "moneyflow 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "moneyflow 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"moneyflow 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e

    async def fetch_daily_basic(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取每日指标数据（估值/换手率/市值等）。

        接口：daily_basic
        限制：单次最大 6000 条，需 2000 积分

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/close/turnover_rate/pe/pb/total_mv 等官方字段
            注：ev/ebitda/ev_ebitda 不属于 daily_basic 接口，需从 fina_indicator 等其他接口获取
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        # daily_basic 官方字段（doc_id=32），不含 ev/ebitda/ev_ebitda/peg/pcf
        fields = (
            "ts_code,trade_date,close,"
            "turnover_rate,turnover_rate_f,volume_ratio,"
            "pe,pe_ttm,pb,ps,ps_ttm,"
            "dv_ratio,dv_ttm,"
            "total_share,float_share,free_share,"
            "total_mv,circ_mv"
        )

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.daily_basic,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                fields=fields,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "daily_basic 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "daily_basic 获取完成: ts_code=%s rows=%d cols=%s",
                ts_code, len(df), list(df.columns),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"daily_basic 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e

    async def fetch_fina_indicator(
        self,
        ts_code: str = "",
        ann_date: str = "",
        start_date: str = "",
        end_date: str = "",
        period: str = "",
    ) -> pd.DataFrame:
        """获取上市公司财务指标数据。

        接口：fina_indicator（doc_id=79）
        限制：单次最大 100 条，需 2000 积分；按单只股票获取历史数据
        字段：显式指定全部字段，避免 Tushare 默认只返回部分列

        Args:
            ts_code: 股票代码，如 "600000.SH"（必选）
            ann_date: 公告日期 YYYYMMDD
            start_date: 报告期开始日期 YYYYMMDD
            end_date: 报告期结束日期 YYYYMMDD
            period: 报告期 YYYYMMDD，如 20231231

        Returns:
            DataFrame，包含全部 fina_indicator 字段
        """
        if not ts_code and not ann_date and not period:
            raise DataCollectionError("ts_code、ann_date、period 至少输入一个")

        # 显式指定全部字段（含默认显示 N 的字段），避免遗漏
        _fields = (
            "ts_code,ann_date,end_date,"
            "eps,dt_eps,total_revenue_ps,revenue_ps,capital_rese_ps,"
            "surplus_rese_ps,undist_profit_ps,extra_item,profit_dedt,"
            "gross_margin,current_ratio,quick_ratio,cash_ratio,"
            "invturn_days,arturn_days,inv_turn,ar_turn,ca_turn,fa_turn,assets_turn,"
            "op_income,valuechange_income,interst_income,daa,"
            "ebit,ebitda,fcff,fcfe,"
            "current_exint,noncurrent_exint,interestdebt,netdebt,"
            "tangible_asset,working_capital,networking_capital,"
            "invest_capital,retained_earnings,"
            "diluted2_eps,bps,ocfps,retainedps,cfps,"
            "ebit_ps,fcff_ps,fcfe_ps,"
            "netprofit_margin,grossprofit_margin,cogs_of_sales,expense_of_sales,"
            "profit_to_gr,saleexp_to_gr,adminexp_of_gr,finaexp_of_gr,"
            "impai_ttm,gc_of_gr,op_of_gr,ebit_of_gr,"
            "roe,roe_waa,roe_dt,roa,npta,roic,"
            "roe_yearly,roa2_yearly,roe_avg,"
            "opincome_of_ebt,investincome_of_ebt,n_op_profit_of_ebt,"
            "tax_to_ebt,dtprofit_to_profit,"
            "salescash_to_or,ocf_to_or,ocf_to_opincome,capitalized_to_da,"
            "debt_to_assets,assets_to_eqt,dp_assets_to_eqt,"
            "ca_to_assets,nca_to_assets,tbassets_to_totalassets,"
            "int_to_talcap,eqt_to_talcapital,"
            "currentdebt_to_debt,longdeb_to_debt,"
            "ocf_to_shortdebt,debt_to_eqt,eqt_to_debt,eqt_to_interestdebt,"
            "tangibleasset_to_debt,tangasset_to_intdebt,tangibleasset_to_netdebt,"
            "ocf_to_debt,ocf_to_interestdebt,ocf_to_netdebt,"
            "ebit_to_interest,longdebt_to_workingcapital,ebitda_to_debt,"
            "turn_days,roa_yearly,roa_dp,fixed_assets,"
            "profit_prefin_exp,non_op_profit,op_to_ebt,nop_to_ebt,"
            "ocf_to_profit,cash_to_liqdebt,cash_to_liqdebt_withinterest,"
            "op_to_liqdebt,op_to_debt,roic_yearly,total_fa_trun,profit_to_op,"
            "q_opincome,q_investincome,q_dtprofit,q_eps,"
            "q_netprofit_margin,q_gsprofit_margin,q_exp_to_sales,"
            "q_profit_to_gr,q_saleexp_to_gr,q_adminexp_to_gr,q_finaexp_to_gr,"
            "q_impair_to_gr_ttm,q_gc_to_gr,q_op_to_gr,"
            "q_roe,q_dt_roe,q_npta,"
            "q_opincome_to_ebt,q_investincome_to_ebt,q_dtprofit_to_profit,"
            "q_salescash_to_or,q_ocf_to_sales,q_ocf_to_or,"
            "basic_eps_yoy,dt_eps_yoy,cfps_yoy,"
            "op_yoy,ebt_yoy,netprofit_yoy,dt_netprofit_yoy,ocf_yoy,"
            "roe_yoy,bps_yoy,assets_yoy,eqt_yoy,"
            "tr_yoy,or_yoy,"
            "q_gr_yoy,q_gr_qoq,q_sales_yoy,q_sales_qoq,"
            "q_op_yoy,q_op_qoq,q_profit_yoy,q_profit_qoq,"
            "q_netprofit_yoy,q_netprofit_qoq,"
            "equity_yoy,rd_exp,update_flag"
        )

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            kwargs: dict[str, str] = {}
            if ts_code:
                kwargs["ts_code"] = ts_code
            if ann_date:
                kwargs["ann_date"] = ann_date
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            if period:
                kwargs["period"] = period
            kwargs["fields"] = _fields
            func = partial(self._pro.fina_indicator, **kwargs)
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "fina_indicator 无数据: ts_code=%s ann_date=%s period=%s range=%s~%s",
                    ts_code, ann_date, period, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "fina_indicator 获取完成: ts_code=%s rows=%d cols=%d",
                ts_code, len(df), len(df.columns),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"fina_indicator 采集失败 ts_code={ts_code} period={period}: {e}"
            ) from e

    async def fetch_stock_basic(
        self,
        ts_code: str = "",
        list_status: str = "L",
        exchange: str = "",
    ) -> pd.DataFrame:
        """获取股票基本信息。

        接口：stock_basic
        限制：无单次上限，无需积分

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            list_status: 上市状态 L(上市) D(退市) P(暂停上市)
            exchange: 交易所 SSE/SZSE/BSE

        Returns:
            DataFrame，包含 ts_code/symbol/name/area/industry/list_date/list_status 等字段
        """
        # 必须显式指定 fields，否则 Tushare SDK 默认只返回部分字段
        # （缺少 list_status/exchange/fullname/enname/curr_type/delist_date/is_hs 等）
        _fields = (
            "ts_code,symbol,name,area,industry,fullname,enname,cnspell,"
            "market,exchange,curr_type,list_status,list_date,delist_date,"
            "is_hs,act_name,act_ent_type"
        )
        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.stock_basic,
                ts_code=ts_code,
                list_status=list_status,
                exchange=exchange,
                fields=_fields,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "stock_basic 无数据: ts_code=%s list_status=%s exchange=%s",
                    ts_code, list_status, exchange,
                )
                return pd.DataFrame()

            logger.debug(
                "stock_basic 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"stock_basic 采集失败 ts_code={ts_code} list_status={list_status}: {e}"
            ) from e

    async def fetch_suspend_d(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
        suspend_type: str = "",
    ) -> pd.DataFrame:
        """获取每日停复牌信息。

        接口：suspend_d
        限制：需 2000 积分

        Args:
            ts_code: 股票代码，如 "000001.SZ"（可输入多值，逗号分隔）
            trade_date: 交易日期 YYYYMMDD
            start_date: 查询开始日期 YYYYMMDD
            end_date: 查询结束日期 YYYYMMDD
            suspend_type: 停复牌类型 S-停牌 R-复牌

        Returns:
            DataFrame，包含 ts_code/trade_date/suspend_timing/suspend_type 字段
        """
        if not ts_code and not trade_date and not start_date:
            raise DataCollectionError("ts_code、trade_date、start_date 至少输入一个")

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            kwargs: dict[str, str] = {}
            if ts_code:
                kwargs["ts_code"] = ts_code
            if trade_date:
                kwargs["trade_date"] = trade_date
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            if suspend_type:
                kwargs["suspend_type"] = suspend_type
            func = partial(self._pro.suspend_d, **kwargs)
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "suspend_d 无数据: ts_code=%s trade_date=%s range=%s~%s type=%s",
                    ts_code, trade_date, start_date, end_date, suspend_type,
                )
                return pd.DataFrame()

            logger.debug(
                "suspend_d 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"suspend_d 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e

    async def fetch_sw_daily(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取申万行业日线行情数据。

        接口：sw_daily
        限制：单次最大 4000 条，需 5000 积分

        Args:
            ts_code: 行业代码，如 "801010.SI"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/open/close/high/low/change/pct_change/vol/amount/pe/pb 等字段
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.sw_daily,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "sw_daily 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "sw_daily 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"sw_daily 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e
