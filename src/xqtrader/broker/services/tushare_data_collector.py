"""Tushare 数据采集服务 — 封装 tushare pro_api 数据采集接口。

核心模式：通过 tushare pro_api 获取数据，asyncio.to_thread 适配异步框架。
所有 tushare 接口调用均为同步 HTTP 请求，通过线程池桥接为异步。

限流策略：按 Tushare 接口独立限流。不同接口的频率上限不同（5000 积分用户）：
  - sw_daily / fina_indicator / moneyflow：硬限 200 次/分钟
  - daily_basic / income / balancesheet / cashflow / moneyflow_dc：500 次/分钟
  - 其他接口：默认 480 次/分钟（500 次/分钟留 20 余量）
每个接口对应独立的 SlidingWindowLimiter 实例，互不干扰。
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

# 默认限流参数：5000 积分用户理论上限 500 次/分钟，留 20 次余量避免边界误差
_DEFAULT_MAX_REQUESTS = 480
_DEFAULT_WINDOW_SECONDS = 60.0


class TushareDataCollector:
    """Tushare 数据采集服务。

    封装 tushare pro_api，提供个股资金流向等数据采集能力。
    tushare 接口为同步 HTTP 调用，通过 asyncio.to_thread 适配异步框架。
    内置按接口的滑动窗口限流器注册表，每次 API 调用前自动 acquire 对应接口许可。
    使用独立线程池（max_workers=20），避免默认线程池过大导致并发超限。
    """

    # Tushare 各接口实际频率上限（5000 积分用户）
    # 仅显式注册严格限制接口（硬限 200/min）；其他接口走默认限流器
    _ENDPOINT_LIMITS: dict[str, tuple[int, float]] = {
        "sw_daily": (200, 60.0),         # 申万行业日线：硬限 200/min
        "fina_indicator": (200, 60.0),   # 财务指标：硬限 200/min
        "moneyflow": (200, 60.0),       # 个股资金流向：硬限 200/min
    }

    _THREAD_POOL: ThreadPoolExecutor | None = None

    def __init__(self) -> None:
        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            logger.warning("TUSHARE_TOKEN 未配置，tushare 接口将不可用")
        ts.set_token(token)
        self._pro = ts.pro_api()

        # 按接口构建独立限流器（注册表模式）
        self._limiters: dict[str, SlidingWindowLimiter] = {
            endpoint: SlidingWindowLimiter(max_req, win)
            for endpoint, (max_req, win) in self._ENDPOINT_LIMITS.items()
        }
        self._default_limiter = SlidingWindowLimiter(_DEFAULT_MAX_REQUESTS, _DEFAULT_WINDOW_SECONDS)

        logger.info(
            "TushareDataCollector 初始化: 按接口限流 endpoints=%s default=%d/%.0fs",
            {ep: f"{m}/{w:.0f}s" for ep, (m, w) in self._ENDPOINT_LIMITS.items()},
            _DEFAULT_MAX_REQUESTS, _DEFAULT_WINDOW_SECONDS,
        )

    def _get_limiter(self, endpoint: str) -> SlidingWindowLimiter:
        """根据 Tushare 接口名获取对应限流器。

        已注册接口（sw_daily/fina_indicator/moneyflow）使用专属 200/min 限流器；
        其他接口使用默认 480/min 限流器。
        """
        return self._limiters.get(endpoint, self._default_limiter)

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
            await self._get_limiter("moneyflow_dc").acquire()
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
            await self._get_limiter("moneyflow").acquire()
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
            await self._get_limiter("daily_basic").acquire()
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
            "q_opincome_qoq,q_investincome_qoq,q_dtprofit_qoq,"
            "q_roe_qoq,q_equity_qoq,q_assets_qoq,"
            "q_tr_yoy,q_or_yoy,q_gr_yoy,"
            "q_op_yoy,q_profit_yoy,q_netprofit_yoy,q_dtprofit_yoy,"
            "q_ocf_yoy,q_roe_yoy,q_assets_yoy,q_equity_yoy,"
            "q_trgrow_qoq,q_orgrow_qoq,q_opgrow_qoq,"
            "q_profitgrow_qoq,q_netprofitgrow_qoq,q_ocfgrow_qoq,"
            "q_roegrow_qoq,q_equitygrow_qoq,"
            "basic_eps_yoy,dt_eps_yoy,cfps_yoy,"
            "op_yoy,ebt_yoy,netprofit_yoy,dt_netprofit_yoy,ocf_yoy,"
            "roe_yoy,bps_yoy,assets_yoy,eqt_yoy,"
            "tr_yoy,or_yoy,"
            "q_gr_qoq,q_sales_yoy,q_sales_qoq,"
            "q_op_qoq,q_profit_qoq,q_netprofit_qoq,"
            "equity_yoy,rd_exp,update_flag"
        )

        try:
            await self._get_limiter("fina_indicator").acquire()
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

    async def fetch_income(
        self,
        ts_code: str = "",
        ann_date: str = "",
        start_date: str = "",
        end_date: str = "",
        period: str = "",
        report_type: str = "",
    ) -> pd.DataFrame:
        """获取上市公司利润表数据。

        接口：income（doc_id=33）
        限制：单次最大返回按标的，需 2000 积分；按单只股票获取历史数据
        字段：显式指定核心字段，避免 Tushare 默认只返回部分列

        Args:
            ts_code: 股票代码，如 "600000.SH"（必选）
            ann_date: 公告日期 YYYYMMDD
            start_date: 公告日开始日期 YYYYMMDD
            end_date: 公告日结束日期 YYYYMMDD
            period: 报告期 YYYYMMDD，如 20231231
            report_type: 报告类型（1合并报表 2单季合并 等）

        Returns:
            DataFrame，包含利润表核心字段
        """
        if not ts_code and not ann_date and not period:
            raise DataCollectionError("ts_code、ann_date、period 至少输入一个")

        _fields = (
            "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,"
            "basic_eps,diluted_eps,"
            "total_revenue,revenue,oper_cost,total_cogs,"
            "sell_exp,admin_exp,fin_exp,assets_impair_loss,"
            "invest_income,ass_invest_income,fv_value_chg_gain,forex_gain,"
            "operate_profit,non_oper_income,non_oper_exp,nca_disploss,"
            "total_profit,income_tax,"
            "n_income,n_income_attr_p,minority_gain,"
            "oth_compr_income,t_compr_income,compr_inc_attr_p,compr_inc_attr_m_s,"
            "ebit,ebitda,rd_exp,"
            "credit_impa_loss,oth_income,asset_disp_income,"
            "update_flag"
        )

        try:
            await self._get_limiter("income").acquire()
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
            if report_type:
                kwargs["report_type"] = report_type
            kwargs["fields"] = _fields
            func = partial(self._pro.income, **kwargs)
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "income 无数据: ts_code=%s ann_date=%s period=%s range=%s~%s",
                    ts_code, ann_date, period, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "income 获取完成: ts_code=%s rows=%d cols=%d",
                ts_code, len(df), len(df.columns),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"income 采集失败 ts_code={ts_code} period={period}: {e}"
            ) from e

    async def fetch_balancesheet(
        self,
        ts_code: str = "",
        ann_date: str = "",
        start_date: str = "",
        end_date: str = "",
        period: str = "",
        report_type: str = "",
    ) -> pd.DataFrame:
        """获取上市公司资产负债表数据。

        接口：balancesheet（doc_id=36）
        限制：单次最大返回按标的，需 2000 积分；按单只股票获取历史数据
        字段：显式指定核心字段，避免 Tushare 默认只返回部分列

        Args:
            ts_code: 股票代码，如 "600000.SH"（必选）
            ann_date: 公告日期 YYYYMMDD
            start_date: 公告日开始日期 YYYYMMDD
            end_date: 公告日结束日期 YYYYMMDD
            period: 报告期 YYYYMMDD，如 20231231
            report_type: 报告类型（1合并报表 2单季合并 等）

        Returns:
            DataFrame，包含资产负债表核心字段
        """
        if not ts_code and not ann_date and not period:
            raise DataCollectionError("ts_code、ann_date、period 至少输入一个")

        _fields = (
            "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,"
            "total_share,cap_rese,undistr_porfit,surplus_rese,special_rese,"
            "money_cap,trad_asset,notes_receiv,accounts_receiv,oth_receiv,"
            "prepayment,div_receiv,int_receiv,inventories,amor_exp,"
            "nca_within_1y,total_cur_assets,"
            "lt_eqt_invest,invest_real_estate,time_deposits,oth_assets,"
            "fix_assets,cip,intan_assets,r_and_d,goodwill,lt_amor_exp,"
            "defer_tax_assets,oth_nca,total_nca,total_assets,"
            "lt_borr,st_borr,"
            "notes_payable,acct_payable,adv_receipts,"
            "payroll_payable,taxes_payable,int_payable,div_payable,oth_payable,"
            "non_cur_liab_due_1y,oth_cur_liab,total_cur_liab,"
            "bond_payable,lt_payable,specific_payables,estimated_liab,"
            "defer_tax_liab,oth_ncl,total_ncl,oth_liab,total_liab,"
            "treasury_share,ordin_risk_reser,forex_differ,invest_loss_unconf,"
            "minority_int,total_hldr_eqy_exc_min_int,total_hldr_eqy_inc_min_int,"
            "total_liab_hldr_eqy,"
            "contract_assets,contract_liab,"
            "update_flag"
        )

        try:
            await self._get_limiter("balancesheet").acquire()
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
            if report_type:
                kwargs["report_type"] = report_type
            kwargs["fields"] = _fields
            func = partial(self._pro.balancesheet, **kwargs)
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "balancesheet 无数据: ts_code=%s ann_date=%s period=%s range=%s~%s",
                    ts_code, ann_date, period, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "balancesheet 获取完成: ts_code=%s rows=%d cols=%d",
                ts_code, len(df), len(df.columns),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"balancesheet 采集失败 ts_code={ts_code} period={period}: {e}"
            ) from e

    async def fetch_cashflow(
        self,
        ts_code: str = "",
        ann_date: str = "",
        start_date: str = "",
        end_date: str = "",
        period: str = "",
        report_type: str = "",
    ) -> pd.DataFrame:
        """获取上市公司现金流量表数据。

        接口：cashflow（doc_id=34）
        限制：单次最大返回按标的，需 2000 积分；按单只股票获取历史数据
        字段：显式指定核心字段，避免 Tushare 默认只返回部分列

        Args:
            ts_code: 股票代码，如 "600000.SH"（必选）
            ann_date: 公告日期 YYYYMMDD
            start_date: 公告日开始日期 YYYYMMDD
            end_date: 公告日结束日期 YYYYMMDD
            period: 报告期 YYYYMMDD，如 20231231
            report_type: 报告类型（1合并报表 2单季合并 等）

        Returns:
            DataFrame，包含现金流量表核心字段
        """
        if not ts_code and not ann_date and not period:
            raise DataCollectionError("ts_code、ann_date、period 至少输入一个")

        _fields = (
            "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,"
            "net_profit,"
            "c_fr_sale_sg,recp_tax_rends,n_depos_incr_fi,c_inf_fr_operate_a,"
            "c_paid_goods_s,c_paid_to_for_empl,c_paid_for_taxes,"
            "oth_cash_pay_oper_act,st_cash_out_act,n_cashflow_act,"
            "c_disp_withdrwl_invest,c_recp_return_invest,n_recp_disp_fiolta,"
            "stot_inflows_inv_act,"
            "c_pay_acq_const_fiolta,c_paid_invest,n_disp_subs_oth_biz,"
            "oth_pay_ral_inv_act,n_incr_pledge_loan,stot_out_inv_act,"
            "n_cashflow_inv_act,"
            "c_recp_borrow,proc_issue_bonds,oth_cash_recp_ral_fnc_act,"
            "stot_cash_in_fnc_act,free_cashflow,"
            "c_prepay_amt_borr,c_pay_dist_dpcp_int_exp,"
            "incl_dvd_profit_paid_sc_ms,oth_cashpay_ral_fnc_act,"
            "stot_cashout_fnc_act,n_cash_flows_fnc_act,"
            "eff_fx_flu_cash,n_incr_cash_cash_equ,"
            "c_cash_equ_beg_period,c_cash_equ_end_period,"
            "update_flag"
        )

        try:
            await self._get_limiter("cashflow").acquire()
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
            if report_type:
                kwargs["report_type"] = report_type
            kwargs["fields"] = _fields
            func = partial(self._pro.cashflow, **kwargs)
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "cashflow 无数据: ts_code=%s ann_date=%s period=%s range=%s~%s",
                    ts_code, ann_date, period, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "cashflow 获取完成: ts_code=%s rows=%d cols=%d",
                ts_code, len(df), len(df.columns),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"cashflow 采集失败 ts_code={ts_code} period={period}: {e}"
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
            await self._get_limiter("stock_basic").acquire()
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
            await self._get_limiter("suspend_d").acquire()
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
            await self._get_limiter("sw_daily").acquire()
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

    async def fetch_index_daily(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取指数日线行情数据。

        接口：index_daily
        限制：单次最大 4000 条，需 2000 积分

        Args:
            ts_code: 指数代码，如 "000001.SH"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，字段格式与 QmtDataCollector._format_kline 对齐：
            trade_date(YYYY-MM-DD)/open/close/high/low/volume/amount/change/pre_close/pct_chg
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._get_limiter("index_daily").acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.index_daily,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "index_daily 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            # trade_date 格式 YYYYMMDD → YYYY-MM-DD（对齐 QMT _format_kline）
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")

            # volume → int（对齐 QMT _format_kline；Tushare 缺失时填 0）
            if "volume" in df.columns:
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

            # 字段对齐 QMT _format_kline 输出列
            keep_cols = [
                "trade_date", "open", "close", "high", "low",
                "volume", "amount", "change", "pre_close", "pct_chg",
            ]
            existing = [c for c in keep_cols if c in df.columns]
            df = df[existing]

            logger.debug(
                "index_daily 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"index_daily 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e
