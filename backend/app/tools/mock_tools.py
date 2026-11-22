"""Mock tools that stand in for real systems until integrations exist."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.tools import mock_payments
from app.tools.errors import ToolError

_CUSTOMERS = {
    101: {
        "customer_id": 101,
        "name": "Asha Rao",
        "email": "asha.rao@example.com",
        "phone": "+91 98765 43210",
        "plan": "pro",
    },
    102: {"customer_id": 102, "name": "Vikram Shah", "email": "vikram@example.com", "plan": "free"},
}


class CustomerArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(gt=0)


class RefundArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(pattern=r"^txn_[A-Za-z0-9]{1,32}$")
    customer_id: int = Field(gt=0)
    # shortcut: float amount is fine for a mock; use integer minor units for real payments.
    amount: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    note: str | None = Field(default=None, max_length=500)


def _customer(customer_id: int) -> dict[str, Any]:
    if customer_id not in _CUSTOMERS:
        raise ToolError(f"Customer {customer_id} not found")
    return _CUSTOMERS[customer_id]


async def read_customer(args: CustomerArgs) -> dict[str, Any]:
    return {"customer": _customer(args.customer_id)}


async def delete_customer(args: CustomerArgs) -> dict[str, Any]:
    _customer(args.customer_id)
    return {"deleted": True, "customer_id": args.customer_id}  # mock: nothing is removed


async def refund(args: RefundArgs) -> dict[str, Any]:
    try:
        total = await mock_payments.apply_refund(args.transaction_id, args.amount)
    except (KeyError, ValueError) as exc:
        raise ToolError("Refund rejected by the payments system") from exc
    return {
        "refunded": True,
        "transaction_id": args.transaction_id,
        "amount": args.amount,
        "total_refunded": total,
        "note": args.note,
    }
