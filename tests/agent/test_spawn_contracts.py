"""spawn JSON 契约单元测试。"""

from __future__ import annotations

import pytest

from agent.spawn_contracts import (
    SpawnContractError,
    detect_spawn_worker,
    extract_json_payload,
    validate_spawn_output,
)


def test_detect_spawn_worker_from_tag() -> None:
    task = "[spawn-worker:fund-flow] 标的 603993.SH。模式：spawn。"
    assert detect_spawn_worker(task) == "fund-flow"


def test_extract_json_payload_from_fenced_text() -> None:
    text = '说明\n```json\n{"as_of":"2026-07-06","conclusion":"中性"}\n```'
    payload = extract_json_payload(text)
    assert payload["as_of"] == "2026-07-06"


def test_validate_fund_flow_contract() -> None:
    payload = {
        "as_of": "2026-07-06",
        "main_flow": {"direction": "流出", "net_amount_wan": -1.0, "net_pct": -1.8},
        "conclusion": "偏空",
    }
    validate_spawn_output("fund-flow", payload)


def test_validate_fund_flow_missing_field_raises() -> None:
    with pytest.raises(SpawnContractError, match="契约校验失败"):
        validate_spawn_output("fund-flow", {"as_of": "2026-07-06"})
