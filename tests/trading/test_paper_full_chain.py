"""模拟盘全链路集成测试 — 历史日期逐日 T+1 回放。

流程（每个交易日 T）：
  1. 决策流：signal_date=T, execution_date=下一交易日 → 生成 pending 预订单
  2. 审批：自动 approve 当日 pending 预订单
  3. 执行：submit → SimulatedMatchingService 本地撮合 → td_order/trade/position 更新

验收：至少一个交易日完成「信号→审批→撮合→持仓」闭环。
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

API_PREFIX = "/api/v1"
PAPER_ACCOUNT_ID = 1
OPERATOR = "paper-chain-test"


def _next_calendar_day(d: date) -> date:
    return d + timedelta(days=1)


async def _get_trading_days(api_client: httpx.AsyncClient, start: date, end: date) -> list[date]:
    """从因子水位推断可用交易日（决策流依赖因子数据）。"""
    response = await api_client.get(
        f"{API_PREFIX}/factors/watermark",
        params={"start_date": start.isoformat(), "end_date": end.isoformat()},
    )
    if response.status_code == 200:
        body = response.json()
        if body.get("code") == 0:
            items = body.get("data", {}).get("items") or body.get("data") or []
            if isinstance(items, list) and items:
                dates = sorted({
                    date.fromisoformat(str(item["trade_date"])[:10])
                    for item in items
                    if item.get("trade_date")
                })
                return [d for d in dates if start <= d <= end]

    # 回退：工作日序列（周末跳过）
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


async def _run_decision(
    api_client: httpx.AsyncClient,
    signal_date: date,
    execution_date: date,
) -> dict:
    response = await api_client.post(
        f"{API_PREFIX}/trading/accounts/{PAPER_ACCOUNT_ID}/decision-workflow/run",
        json={
            "signal_date": signal_date.isoformat(),
            "execution_date": execution_date.isoformat(),
            "min_confidence": 0.3,
            "max_selected": 10,
            "lookback_days": 120,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body.get("message")
    return body["data"]


async def _approve_pre_order(api_client: httpx.AsyncClient, pre_order_id: int) -> dict:
    response = await api_client.post(
        f"{API_PREFIX}/trading/approval/{pre_order_id}",
        json={"approved": True, "approved_by": OPERATOR, "comment": "paper-chain-test auto approve"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body.get("message")
    return body["data"]


async def _submit_pre_order(api_client: httpx.AsyncClient, pre_order_id: int) -> dict:
    response = await api_client.post(
        f"{API_PREFIX}/trading/pre-orders/{pre_order_id}/submit",
        json={"operator": OPERATOR},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body.get("message")
    return body["data"]


class TestPaperFullChain:
    """模拟盘全链路黑盒测试。"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_probe_historical_signal_dates(self, api_client: httpx.AsyncClient) -> None:
        """探测历史日期中哪些能产出预订单。"""
        candidates = [date(2026, 6, d) for d in (3, 10, 17, 20, 24, 27)]
        productive: list[tuple[date, int]] = []
        for signal_date in candidates:
            execution_date = _next_calendar_day(signal_date)
            data = await _run_decision(api_client, signal_date, execution_date)
            pre_count = data["pre_orders_count"]
            if pre_count > 0:
                productive.append((signal_date, pre_count))
        # 至少一个历史日期能产出信号（依赖库内因子/行情数据）
        assert productive, (
            "历史日期均未产出预订单，请检查 paper 账户自选池策略绑定与因子数据覆盖"
        )

    @pytest.mark.asyncio(loop_scope="session")
    async def test_single_day_full_chain(self, api_client: httpx.AsyncClient) -> None:
        """单日全链路：决策 → 审批 → 模拟撮合 → 持仓/资金更新。"""
        signal_date = date(2026, 6, 24)
        execution_date = date(2026, 6, 25)

        # 记录执行前状态
        before_account = await api_client.get(f"{API_PREFIX}/trading/accounts/{PAPER_ACCOUNT_ID}")
        before_cash = float(before_account.json()["data"]["available_cash"])

        # 1. 决策流
        decision = await _run_decision(api_client, signal_date, execution_date)
        pre_orders = decision.get("pre_orders") or []
        if not pre_orders:
            pytest.skip(
                f"{signal_date} 无预订单产出，跳过单日链路"
                f"（signals={decision['signals_count']} fusion={decision['fusion_count']}）"
            )

        # 2. 审批 + 3. 提交（模拟撮合）
        submitted: list[dict] = []
        for po in pre_orders:
            approved = await _approve_pre_order(api_client, po["id"])
            assert approved["approval_status"] == "approved"
            result = await _submit_pre_order(api_client, approved["id"])
            assert result["submitter"] == "simulated", f"paper 账户应走 simulated，实际: {result['submitter']}"
            assert result["order"]["status"] == "filled", f"模拟撮合应即时成交，实际: {result['order']['status']}"
            assert result["broker_order_id"].startswith("SIM-")
            submitted.append(result)

        # 4. 验证持仓
        after_positions = await api_client.get(
            f"{API_PREFIX}/trading/positions",
            params={"account_id": PAPER_ACCOUNT_ID},
        )
        after_pos = after_positions.json()["data"]["items"]
        buy_symbols = {r["order"]["symbol"] for r in submitted if r["order"]["side"] == "buy"}
        if buy_symbols:
            held_symbols = {p["symbol"] for p in after_pos if int(p["qty"]) > 0}
            assert buy_symbols & held_symbols, f"买入后应有持仓，buy={buy_symbols} held={held_symbols}"

        # 5. 验证资金变化（买入应减少现金）
        after_account = await api_client.get(f"{API_PREFIX}/trading/accounts/{PAPER_ACCOUNT_ID}")
        after_cash = float(after_account.json()["data"]["available_cash"])
        has_buy = any(r["order"]["side"] == "buy" for r in submitted)
        if has_buy:
            assert after_cash < before_cash, f"买入后现金应减少: before={before_cash} after={after_cash}"

        # 6. 验证订单列表
        orders_resp = await api_client.get(
            f"{API_PREFIX}/trading/orders",
            params={"account_id": PAPER_ACCOUNT_ID, "page_size": 50},
        )
        order_ids = {o["id"] for o in orders_resp.json()["data"]["items"]}
        for r in submitted:
            assert r["order"]["id"] in order_ids

        # 7. 验证账户快照
        snapshot_resp = await api_client.get(
            f"{API_PREFIX}/trading/accounts/{PAPER_ACCOUNT_ID}/snapshot",
        )
        snapshot = snapshot_resp.json()["data"]
        assert snapshot is not None
        assert float(snapshot["total_assets"]) > 0

    @pytest.mark.asyncio(loop_scope="session")
    async def test_multi_day_t_plus_one_replay(self, api_client: httpx.AsyncClient) -> None:
        """多日回放：从上月某日起逐日执行 T 信号 → T+1 执行，模拟真实交易节奏。"""
        start = date(2026, 6, 3)
        end = date(2026, 6, 27)
        trading_days = await _get_trading_days(api_client, start, end)
        assert len(trading_days) >= 5, "交易日数量不足"

        stats = {
            "days_run": 0,
            "days_with_signals": 0,
            "pre_orders_generated": 0,
            "pre_orders_submitted": 0,
            "submit_failures": 0,
        }

        for idx, signal_date in enumerate(trading_days[:-1]):
            execution_date = trading_days[idx + 1]  # 下一交易日 T+1
            stats["days_run"] += 1

            decision = await _run_decision(api_client, signal_date, execution_date)
            pre_orders = decision.get("pre_orders") or []
            if not pre_orders:
                continue

            stats["days_with_signals"] += 1
            stats["pre_orders_generated"] += len(pre_orders)

            for po in pre_orders:
                try:
                    approved = await _approve_pre_order(api_client, po["id"])
                    result = await _submit_pre_order(api_client, approved["id"])
                    if result["submitter"] == "simulated" and result["order"]["status"] == "filled":
                        stats["pre_orders_submitted"] += 1
                except AssertionError:
                    stats["submit_failures"] += 1

        # 验收：多日回放中至少完成一次全链路
        assert stats["days_with_signals"] >= 1, (
            f"多日回放未产出任何预订单，stats={stats}"
        )
        assert stats["pre_orders_submitted"] >= 1, (
            f"多日回放未成功提交任何预订单，stats={stats}"
        )

        # 最终状态检查
        positions = await api_client.get(
            f"{API_PREFIX}/trading/positions",
            params={"account_id": PAPER_ACCOUNT_ID},
        )
        orders = await api_client.get(
            f"{API_PREFIX}/trading/orders",
            params={"account_id": PAPER_ACCOUNT_ID, "page_size": 100},
        )
        snapshots = await api_client.get(
            f"{API_PREFIX}/trading/accounts/{PAPER_ACCOUNT_ID}/snapshots",
            params={"page_size": 31},
        )

        pos_items = positions.json()["data"]["items"]
        order_items = orders.json()["data"]["items"]
        snap_items = snapshots.json()["data"]["items"]

        assert len(order_items) >= stats["pre_orders_submitted"]
        assert len(snap_items) >= 1

        # 输出统计供验收报告引用
        print("\n=== PAPER MULTI-DAY REPLAY STATS ===")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print(f"  final_positions: {len([p for p in pos_items if int(p['qty']) > 0])}")
        print(f"  final_orders: {len(order_items)}")
        print(f"  final_snapshots: {len(snap_items)}")
