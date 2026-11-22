import uuid

import pytest

from app.approvals import service as approvals
from app.database.models import Agent
from app.tools import mock_payments
from app.tools.mock_tools import RefundArgs
from app.verification.refunds import verify_refund

URL = "/api/v1/proxy/execute"


async def _facts(db, txn, customer_id=101, amount=100, exclude=None):
    args = RefundArgs(transaction_id=txn, customer_id=customer_id, amount=amount)
    async with db.sessions() as session:
        return await verify_refund(args, session=session, exclude_approval_id=exclude)


async def test_unknown_transaction(db):
    assert await _facts(db, "txn_9999") == {"transaction_found": False}


async def test_clean_transaction(db):
    f = await _facts(db, "txn_1009")
    assert f["transaction_found"] and f["customer_matches"] and f["customer_eligible"]
    assert (f["payment_status"], f["refundable_balance"], f["risk_signals"]) == (
        "succeeded",
        2500,
        [],
    )
    assert not f["fully_refunded"] and not f["refund_pending"]


@pytest.mark.parametrize(
    ("txn", "customer", "key", "expected"),
    [
        ("txn_1001", 102, "customer_matches", False),  # agent claims another customer
        ("txn_1003", 101, "payment_status", "failed"),
        ("txn_1002", 101, "fully_refunded", True),
        ("txn_1005", 101, "refundable_balance", 7000),  # 9000 paid, 2000 refunded
        ("txn_1006", 103, "ineligible_reasons", ["customer account is not active"]),
        ("txn_1007", 101, "ineligible_reasons", ["outside the refund window"]),
        ("txn_1004", 102, "risk_signals", ["new_account"]),
        ("txn_1005", 101, "risk_signals", ["previously_partially_refunded"]),
        ("txn_1008", 104, "risk_signals", ["high_refund_frequency"]),
    ],
)
async def test_facts_come_from_trusted_data(db, txn, customer, key, expected):
    assert (await _facts(db, txn, customer))[key] == expected


async def test_open_approval_marks_refund_pending(db):
    agent = Agent(name="a", status="active", api_key_hash="0" * 64)
    db.add(agent)
    db.commit()
    async with db.sessions() as session:
        approval = await approvals.create(
            session,
            agent=agent,
            request_id="r",
            tool_name="payment",
            action="refund",
            arguments={"transaction_id": "txn_1001", "customer_id": 101, "amount": 8000},
            reason="x",
            ttl_seconds=60,
        )
        await session.commit()
    assert (await _facts(db, "txn_1001"))["refund_pending"] is True
    # ...but not when that approval is the one being used.
    assert (await _facts(db, "txn_1001", exclude=approval.id))["refund_pending"] is False
    assert (await _facts(db, "txn_1009"))["refund_pending"] is False


async def test_executed_refund_updates_the_trusted_balance():
    await mock_payments.apply_refund("txn_1009", 2000)
    t = await mock_payments.get_transaction("txn_1009")
    assert t["refunded"] == 2000
    with pytest.raises(ValueError):
        await mock_payments.apply_refund("txn_1009", 501)


def test_proxy_sends_verification_to_policy(api, policy):
    calls = policy("allow")
    body = {
        "tool_name": "payment",
        "action": "refund",
        "arguments": {"transaction_id": "txn_1009", "customer_id": 101, "amount": 100},
    }
    assert api.post(URL, json=body).status_code == 200
    assert calls[0]["verification"]["refundable_balance"] == 2500


def test_payments_tool_rejects_over_refund_even_if_policy_allows(api, policy):
    policy("allow")
    body = {
        "tool_name": "payment",
        "action": "refund",
        "arguments": {"transaction_id": "txn_1002", "customer_id": 101, "amount": 1},
    }
    resp = api.post(URL, json=body)
    assert resp.status_code == 422
    assert resp.json()["reason"] == "Refund rejected by the payments system"


def test_verification_failure_fails_closed(api, policy, monkeypatch, tool_calls):
    async def down(_id):
        raise ConnectionError("payments down")

    monkeypatch.setattr(mock_payments, "get_transaction", down)
    calls = policy("allow")
    body = {
        "tool_name": "payment",
        "action": "refund",
        "arguments": {"transaction_id": "txn_1009", "customer_id": 101, "amount": 100},
        "request_id": f"v-{uuid.uuid4().hex}",
    }
    resp = api.post(URL, json=body)
    assert resp.status_code == 503
    assert resp.json()["reason"] == "Verification unavailable"
    assert calls == [] and tool_calls == []
