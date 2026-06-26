"""北交所个股资金流历史补采 — 使用 Tushare moneyflow_dc 接口。

moneyflow 接口不含北交所数据；moneyflow_dc 支持 .BJ 标的。
本脚本独立运行，不依赖 FastAPI / ORM 初始化，避免环境缺依赖导致失败。
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import tushare as ts
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".trae" / "skills" / "db-tools" / ".env"
BACKFILL_START = "20230603"
SOURCE = "tushare"
DATA_TYPE = "fund_flow"
MAX_WORKERS = 8
REQUEST_INTERVAL = 0.15


def load_database_url() -> str:
    load_dotenv(ENV_PATH)
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(f"未找到 DATABASE_URL: {ENV_PATH}")
    if "psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://")
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    return url


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


def fetch_and_persist(pro, engine, symbol: str, end_date: str) -> dict:
    time.sleep(REQUEST_INTERVAL)
    raw = pro.moneyflow_dc(ts_code=symbol, start_date=BACKFILL_START, end_date=end_date)
    if raw is None or raw.empty:
        return {"symbol": symbol, "rows": 0, "max_date": None, "status": "empty"}

    cleaned = clean_fund_flow_dc_data(raw)
    if cleaned.empty:
        return {"symbol": symbol, "rows": 0, "max_date": None, "status": "clean_empty"}

    records = cleaned.to_dict(orient="records")
    upsert_rows(engine, records)
    max_date = max(r["trade_date"] for r in records)
    return {"symbol": symbol, "rows": len(records), "max_date": max_date, "status": "ok"}


def sync_watermarks(engine, symbols: list[str]) -> int:
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
        GROUP BY ff.symbol
        ON CONFLICT (data_type, watermark_code) DO UPDATE SET
            watermark_date = EXCLUDED.watermark_date,
            status = 'active',
            updated_at = NOW()
    """)
    with engine.begin() as conn:
        result = conn.execute(sql, {"data_type": DATA_TYPE, "symbols": symbols})
        return result.rowcount


def main() -> int:
    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        load_dotenv(ENV_PATH)
        token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        print("[ERROR] TUSHARE_TOKEN 未配置", file=sys.stderr)
        return 1

    engine = create_engine(load_database_url(), pool_pre_ping=True)
    ts.set_token(token)
    pro = ts.pro_api()
    end_date = date.today().strftime("%Y%m%d")

    with engine.connect() as conn:
        symbols = [
            row[0]
            for row in conn.execute(text("""
                SELECT symbol FROM stock.sdc_security
                WHERE list_status = 'L' AND symbol LIKE '%.BJ'
                ORDER BY symbol
            """)).fetchall()
        ]

    print(f"[INFO] 北交所上市标的: {len(symbols)} 只, 补采区间: {BACKFILL_START} ~ {end_date}")

    ok = 0
    empty = 0
    failed = 0
    total_rows = 0
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(fetch_and_persist, pro, engine, symbol, end_date): symbol
            for symbol in symbols
        }
        for idx, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                result = future.result()
                results.append(result)
                if result["status"] == "ok":
                    ok += 1
                    total_rows += result["rows"]
                else:
                    empty += 1
            except Exception as exc:
                failed += 1
                print(f"[ERROR] {symbol}: {exc}")
            if idx % 20 == 0 or idx == len(symbols):
                print(f"[PROGRESS] {idx}/{len(symbols)} ok={ok} empty={empty} failed={failed} rows={total_rows}")

    updated = sync_watermarks(engine, symbols)
    print(f"[OK] 补采完成: ok={ok} empty={empty} failed={failed} persisted_rows={total_rows}")
    print(f"[OK] 水位更新: {updated} 条")

    with engine.connect() as conn:
        summary = conn.execute(text("""
            SELECT
                COUNT(DISTINCT symbol) AS symbols_with_data,
                MIN(trade_date) AS min_date,
                MAX(trade_date) AS max_date,
                COUNT(*) AS total_rows
            FROM stock.sdc_fund_flow_individual
            WHERE symbol LIKE '%.BJ' AND source = 'tushare'
        """)).mappings().one()
        wm = conn.execute(text("""
            SELECT COUNT(*) AS cnt,
                   MIN(watermark_date) AS min_wm,
                   MAX(watermark_date) AS max_wm
            FROM public.t_collect_watermark
            WHERE data_type = 'fund_flow' AND watermark_code LIKE '%.BJ'
        """)).mappings().one()
    print(f"[VERIFY] BJ fund_flow data: {dict(summary)}")
    print(f"[VERIFY] BJ fund_flow watermark: {dict(wm)}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
