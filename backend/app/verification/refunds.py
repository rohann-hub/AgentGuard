"""Refund verification: facts from trusted payments data, handed to OPA as input.verification.

This module only gathers facts; the OPA policy decides deny / approval / allow.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals import service as approvals
from app.tools import mock_payments as payments

REFUND_WINDOW = timedelta(days=180)
NEW_ACCOUNT_AGE = timedelta(days=30)
HIGH_REFUND_COUNT = 3  # refunds in the last 30 days


async def verify_refund(
    args: Any, *, session: AsyncSession, exclude_approval_id: uuid.UUID | None
) -> dict[str, Any]:
    txn = await payments.get_transaction(args.transaction_id)
    if txn is None:
        return {"transaction_found": False}
    customer = await payments.get_customer(txn["customer_id"]) or {}
    now = datetime.now(UTC)

    refundable = txn["amount"] - txn["refunded"]
    ineligible = []
    if customer.get("status") != "active":
        ineligible.append("customer account is not active")
    if now - txn["paid_at"] > REFUND_WINDOW:
        ineligible.append("outside the refund window")

    risk = []
    if customer.get("created_at") and now - customer["created_at"] < NEW_ACCOUNT_AGE:
        risk.append("new_account")
    if customer.get("refunds_last_30_days", 0) >= HIGH_REFUND_COUNT:
        risk.append("high_refund_frequency")
    if 0 < txn["refunded"] < txn["amount"]:
        risk.append("previously_partially_refunded")

    return {
        "transaction_found": True,
        # The agent's customer_id is checked against the transaction, never trusted.
        "customer_matches": txn["customer_id"] == args.customer_id,
        "payment_status": txn["status"],
        "paid_amount": txn["amount"],
        "refunded_amount": txn["refunded"],
        "refundable_balance": refundable,
        "fully_refunded": txn["refunded"] >= txn["amount"],
        "customer_eligible": not ineligible,
        "ineligible_reasons": ineligible,
        "refund_pending": await approvals.has_open(
            session, "payment", "refund", "transaction_id", args.transaction_id,
            exclude=exclude_approval_id,
        ),
        "risk_signals": risk,
    }  # fmt: skip
