"""回补「有日线、无资金流」的缺失数据，并同步 fund_flow 水位。

策略：
1. 找出 fund_flow 水位落后于 daily_kline 的标的
2. 对每个标的，找出日线有、资金流无的交易日
3. 按 ts_code 调用 Tushare moneyflow_dc 拉取 [ff_wm, k_wm] 区间
4. upsert 到 stock.sdc_fund_flow_individual
5. 按表内 MAX(trade_date) 回写 public.t_collect_watermark
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import tushare as ts
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = "tushare"
DATA_TYPE = "fund_flow"
MAX_WORKERS = 4
REQUEST_INTERVAL = 0.2


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    # 兼容历史 db-tools / 本地覆盖
    for p in (
        PROJECT_ROOT / ".trae" / "skills" / "db-tools" / ".env",
        Path.home() / ".trae" / "skills" / "db-tools" / ".env",
    ):
        if p.exists():
            load_dotenv(p, override=False)


def database_url() -> str:
    host = os.environ["DATABASES_STOCK_HOST"]
    port = os.environ["DATABASES_STOCK_PORT"]
    name = os.environ["DATABASES_STOCK_NAME"]
    user = quote_plus(os.environ["DATABASES_STOCK_USER"])
    password = quote_plus(os.environ["DATABASES_STOCK_PASSWORD"].strip())
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def clean_fund_flow_dc_data(df: pd.DataFrame) -> pd.DataFrame:
    net_mapping = {
        "buy_elg_amount": "huge_net_amt",
        "buy_lg_amount": "big_net_amt",
        "buy_md_amount": "mid_net_amt",
        "buy_sm_amount": "small_net_amt",
    }
    pct_mapping = {
        "buy_elg_amount_rate": "huge_net_pct",
        "buy_lg_amount_rate": "big_net_pct",
        "buy_md_amount_rate": "mid_net_pct",
        "buy_sm_amount_rate": "small_net_pct",
    }
    numeric_cols = [
        "close", "pct_change",
        "huge_net_amt", "huge_net_pct",
        "big_net_amt", "big_net_pct",
        "mid_net_amt", "mid_net_pct",
        "small_net_amt", "small_net_pct",
        "main_net_amt", "main_net_pct",
        "net_mf_amt",
    ]

    df = df.rename(columns={"ts_code": "symbol"})
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.date

    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    for src, dst in net_mapping.items():
        if src in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce")
    for src, dst in pct_mapping.items():
        if src in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce")
    if "net_amount" in df.columns:
        df["net_mf_amt"] = pd.to_numeric(df["net_amount"], errors="coerce")
    if "net_amount_rate" in df.columns:
        df["main_net_pct"] = pd.to_numeric(df["net_amount_rate"], errors="coerce")
    if "pct_change" in df.columns:
        df["pct_change"] = pd.to_numeric(df["pct_change"], errors="coerce")
    if "close" in df.columns:
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if "huge_net_amt" in df.columns and "big_net_amt" in df.columns:
        df["main_net_amt"] = df["huge_net_amt"] + df["big_net_amt"]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].round(4)

    df["source"] = SOURCE
    return df.dropna(subset=["symbol", "trade_date"]).reset_index(drop=True)


def upsert_rows(engine, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = text("""
        INSERT INTO stock.sdc_fund_flow_individual (
            symbol, trade_date, source, close, pct_change,
            main_net_amt, main_net_pct,
            huge_net_amt, huge_net_pct,
            big_net_amt, big_net_pct,
            mid_net_amt, mid_net_pct,
            small_net_amt, small_net_pct,
            net_mf_amt
        ) VALUES (
            :symbol, :trade_date, :source, :close, :pct_change,
            :main_net_amt, :main_net_pct,
            :huge_net_amt, :huge_net_pct,
            :big_net_amt, :big_net_pct,
            :mid_net_amt, :mid_net_pct,
            :small_net_amt, :small_net_pct,
            :net_mf_amt
        )
        ON CONFLICT (symbol, trade_date, source) DO UPDATE SET
            close = EXCLUDED.close,
            pct_change = EXCLUDED.pct_change,
            main_net_amt = EXCLUDED.main_net_amt,
            main_net_pct = EXCLUDED.main_net_pct,
            huge_net_amt = EXCLUDED.huge_net_amt,
            huge_net_pct = EXCLUDED.huge_net_pct,
            big_net_amt = EXCLUDED.big_net_amt,
            big_net_pct = EXCLUDED.big_net_pct,
            mid_net_amt = EXCLUDED.mid_net_amt,
            mid_net_pct = EXCLUDED.mid_net_pct,
            small_net_amt = EXCLUDED.small_net_amt,
            small_net_pct = EXCLUDED.small_net_pct,
            net_mf_amt = EXCLUDED.net_mf_amt
    """)
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def list_behind_symbols(engine) -> list[dict]:
    sql = text("""
        SELECT f.watermark_code AS symbol,
               f.watermark_date AS ff_wm,
               k.watermark_date AS k_wm
        FROM public.t_collect_watermark f
        JOIN public.t_collect_watermark k
          ON k.watermark_code = f.watermark_code
         AND k.data_type = 'daily_kline'
         AND k.status = 'active'
        WHERE f.data_type = 'fund_flow'
          AND f.status = 'active'
          AND f.watermark_date < k.watermark_date
        ORDER BY f.watermark_date, f.watermark_code
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql).mappings().all()]


def missing_kline_dates(engine, symbol: str, start: date, end: date) -> list[date]:
    """日线有、资金流无的交易日（含 start 次日到 end）。"""
    sql = text("""
        SELECT k.trade_date
        FROM stock.sdc_candlestick_daily k
        LEFT JOIN stock.sdc_fund_flow_individual f
          ON f.symbol = k.symbol
         AND f.trade_date = k.trade_date
         AND f.source = :source
        WHERE k.symbol = :symbol
          AND k.trade_date > :start
          AND k.trade_date <= :end
          AND f.symbol IS NULL
        ORDER BY k.trade_date
    """)
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"symbol": symbol, "start": start, "end": end, "source": SOURCE},
        ).fetchall()
    return [r[0] for r in rows]


def fetch_and_persist(pro, engine, item: dict) -> dict:
    symbol = item["symbol"]
    ff_wm: date = item["ff_wm"]
    k_wm: date = item["k_wm"]
    # 从水位次日开始补，避免重复；若水位日本身也缺则从水位日开始
    start = ff_wm
    end = k_wm
    missing = missing_kline_dates(engine, symbol, start - timedelta(days=1), end)
    if not missing:
        return {
            "symbol": symbol,
            "status": "no_gap",
            "rows": 0,
            "missing_days": 0,
            "max_date": None,
            "ff_wm": ff_wm,
            "k_wm": k_wm,
        }

    time.sleep(REQUEST_INTERVAL)
    ts_start = min(missing).strftime("%Y%m%d")
    ts_end = max(missing).strftime("%Y%m%d")
    raw = pro.moneyflow_dc(ts_code=symbol, start_date=ts_start, end_date=ts_end)
    if raw is None or raw.empty:
        return {
            "symbol": symbol,
            "status": "empty",
            "rows": 0,
            "missing_days": len(missing),
            "max_date": None,
            "ff_wm": ff_wm,
            "k_wm": k_wm,
            "missing_sample": [d.isoformat() for d in missing[:5]],
        }

    cleaned = clean_fund_flow_dc_data(raw)
    if cleaned.empty:
        return {
            "symbol": symbol,
            "status": "clean_empty",
            "rows": 0,
            "missing_days": len(missing),
            "max_date": None,
            "ff_wm": ff_wm,
            "k_wm": k_wm,
        }

    # 只保留确实缺失的交易日
    missing_set = set(missing)
    cleaned = cleaned[cleaned["trade_date"].isin(missing_set)]
    if cleaned.empty:
        return {
            "symbol": symbol,
            "status": "no_overlap",
            "rows": 0,
            "missing_days": len(missing),
            "max_date": None,
            "ff_wm": ff_wm,
            "k_wm": k_wm,
        }

    records = cleaned.to_dict(orient="records")
    # 补齐可能缺失的列
    for r in records:
        for col in (
            "close", "pct_change",
            "main_net_amt", "main_net_pct",
            "huge_net_amt", "huge_net_pct",
            "big_net_amt", "big_net_pct",
            "mid_net_amt", "mid_net_pct",
            "small_net_amt", "small_net_pct",
            "net_mf_amt",
        ):
            r.setdefault(col, None)
    upsert_rows(engine, records)
    max_date = max(r["trade_date"] for r in records)
    return {
        "symbol": symbol,
        "status": "ok",
        "rows": len(records),
        "missing_days": len(missing),
        "filled_days": len(records),
        "max_date": max_date,
        "ff_wm": ff_wm,
        "k_wm": k_wm,
    }


def sync_watermarks(engine, symbols: list[str]) -> int:
    if not symbols:
        return 0
    sql = text("""
        INSERT INTO public.t_collect_watermark (
            data_type, watermark_code, watermark_date, record_count, status, updated_at
        )
        SELECT
            :data_type,
            ff.symbol,
            MAX(ff.trade_date),
            0,
            'active',
            NOW()
        FROM stock.sdc_fund_flow_individual ff
        WHERE ff.symbol = ANY(:symbols)
          AND ff.source = :source
        GROUP BY ff.symbol
        ON CONFLICT (data_type, watermark_code) DO UPDATE SET
            watermark_date = EXCLUDED.watermark_date,
            status = 'active',
            updated_at = NOW()
    """)
    with engine.begin() as conn:
        result = conn.execute(
            sql,
            {"data_type": DATA_TYPE, "symbols": symbols, "source": SOURCE},
        )
        return result.rowcount


def main() -> int:
    _load_env()
    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        print("[ERROR] TUSHARE_TOKEN 未配置", file=sys.stderr)
        return 1

    engine = create_engine(database_url(), pool_pre_ping=True)
    ts.set_token(token)
    pro = ts.pro_api()

    behind = list_behind_symbols(engine)
    print(f"[INFO] fund_flow 落后 daily_kline 的标的: {len(behind)}")
    if not behind:
        return 0

    # 先统计真实缺口
    gap_items: list[dict] = []
    no_gap = 0
    for item in behind:
        missing = missing_kline_dates(
            engine,
            item["symbol"],
            item["ff_wm"] - timedelta(days=1),
            item["k_wm"],
        )
        if missing:
            gap_items.append(item)
        else:
            no_gap += 1
    print(f"[INFO] 有日线无资金流缺口: {len(gap_items)}，水位落后但无缺口: {no_gap}")

    ok = 0
    empty = 0
    failed = 0
    total_rows = 0
    empty_symbols: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(fetch_and_persist, pro, engine, item): item["symbol"]
            for item in gap_items
        }
        for idx, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                result = future.result()
                status = result["status"]
                if status == "ok":
                    ok += 1
                    total_rows += int(result["rows"])
                    print(
                        f"[OK] {symbol}: filled={result['rows']}/{result['missing_days']} "
                        f"max={result['max_date']} wm={result['ff_wm']}->{result['k_wm']}"
                    )
                elif status == "empty":
                    empty += 1
                    empty_symbols.append(symbol)
                    print(
                        f"[EMPTY] {symbol}: missing_days={result['missing_days']} "
                        f"sample={result.get('missing_sample')}"
                    )
                else:
                    empty += 1
                    print(f"[{status.upper()}] {symbol}: {result}")
            except Exception as exc:
                failed += 1
                print(f"[ERROR] {symbol}: {exc}")
            if idx % 20 == 0 or idx == len(gap_items):
                print(
                    f"[PROGRESS] {idx}/{len(gap_items)} "
                    f"ok={ok} empty={empty} failed={failed} rows={total_rows}"
                )

    symbols = [i["symbol"] for i in behind]
    updated = sync_watermarks(engine, symbols)
    print(f"[DONE] ok={ok} empty={empty} failed={failed} persisted_rows={total_rows}")
    print(f"[DONE] watermark synced: {updated}")

    with engine.connect() as conn:
        summary = conn.execute(text("""
            SELECT
                COUNT(*) AS codes,
                COUNT(*) FILTER (WHERE watermark_date IS NULL) AS missing,
                MIN(watermark_date) AS min_d,
                MAX(watermark_date) AS max_d,
                COUNT(*) FILTER (WHERE watermark_date = DATE '2026-04-29') AS at_0429
            FROM public.t_collect_watermark
            WHERE status = 'active' AND data_type = 'fund_flow'
        """)).mappings().one()
        lag = conn.execute(text("""
            SELECT COUNT(*) AS ff_behind
            FROM public.t_collect_watermark f
            JOIN public.t_collect_watermark k
              ON k.watermark_code = f.watermark_code
             AND k.data_type = 'daily_kline' AND k.status = 'active'
            WHERE f.data_type = 'fund_flow' AND f.status = 'active'
              AND f.watermark_date < k.watermark_date
        """)).mappings().one()
        stuck = conn.execute(text("""
            SELECT watermark_code, watermark_date
            FROM public.t_collect_watermark
            WHERE data_type = 'fund_flow' AND status = 'active'
              AND watermark_date = DATE '2026-04-29'
        """)).mappings().all()
    print(f"[VERIFY] fund_flow watermark: {dict(summary)}")
    print(f"[VERIFY] still behind kline: {dict(lag)}")
    print(f"[VERIFY] still at 2026-04-29: {[dict(r) for r in stuck]}")
    if empty_symbols:
        print(f"[VERIFY] tushare empty symbols ({len(empty_symbols)}): {empty_symbols[:30]}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
