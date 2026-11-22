"""Mock payments system: the trusted source of transactions and customer refund data.

Refund checks read from here, never from what the agent sent. Replace with a real
payments client that implements the same three async functions.
"""

from datetime import UTC, datetime, timedelta
from typing import Any


def _ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _seed() -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    transactions = {
        "txn_1001": {"customer_id": 101, "amount": 12000, "status": "succeeded", "refunded": 0},
        "txn_1002": {"customer_id": 101, "amount": 3000, "status": "succeeded", "refunded": 3000},
        "txn_1003": {"customer_id": 101, "amount": 5000, "status": "failed", "refunded": 0},
        "txn_1004": {"customer_id": 102, "amount": 4000, "status": "succeeded", "refunded": 0},
        "txn_1005": {"customer_id": 101, "amount": 9000, "status": "succeeded", "refunded": 2000},
        "txn_1006": {"customer_id": 103, "amount": 1000, "status": "succeeded", "refunded": 0},
        "txn_1007": {"customer_id": 101, "amount": 2000, "status": "succeeded", "refunded": 0},
        "txn_1008": {"customer_id": 104, "amount": 1500, "status": "succeeded", "refunded": 0},
        "txn_1009": {"customer_id": 101, "amount": 2500, "status": "succeeded", "refunded": 0},
        "txn_1010": {"customer_id": 101, "amount": 9500, "status": "succeeded", "refunded": 0},
        "txn_1011": {"customer_id": 101, "amount": 20000, "status": "succeeded", "refunded": 0},
    }
    for tid, days in {"txn_1007": 400}.items():
        transactions[tid]["paid_at"] = _ago(days)
    for t in transactions.values():
        t.setdefault("paid_at", _ago(5))
    customers = {
        101: {"status": "active", "created_at": _ago(900), "refunds_last_30_days": 0},
        102: {"status": "active", "created_at": _ago(10), "refunds_last_30_days": 0},
        103: {"status": "closed", "created_at": _ago(900), "refunds_last_30_days": 0},
        104: {"status": "active", "created_at": _ago(900), "refunds_last_30_days": 4},
    }
    return transactions, customers


_TRANSACTIONS, _CUSTOMERS = _seed()


def reset() -> None:
    """Restore the seed data (tests)."""
    global _TRANSACTIONS, _CUSTOMERS
    _TRANSACTIONS, _CUSTOMERS = _seed()


async def get_transaction(transaction_id: str) -> dict[str, Any] | None:
    t = _TRANSACTIONS.get(transaction_id)
    return dict(t) if t else None


async def get_customer(customer_id: int) -> dict[str, Any] | None:
    c = _CUSTOMERS.get(customer_id)
    return dict(c) if c else None


async def apply_refund(transaction_id: str, amount: float) -> float:
    """Record a refund and return the new refunded total. Re-checks the balance at the
    moment of refunding, as a real payments provider would."""
    t = _TRANSACTIONS[transaction_id]
    if t["refunded"] + amount > t["amount"]:
        raise ValueError("refund exceeds refundable balance")
    t["refunded"] += amount
    return t["refunded"]
