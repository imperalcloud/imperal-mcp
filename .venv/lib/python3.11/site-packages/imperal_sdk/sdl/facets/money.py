"""Money & Commerce family — monetary values, pricing, discounts, subscriptions, balances, invoices. Namespace money.*"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class Monetary(BaseModel):
    amount: Decimal | None = _facet_field(role="money.amount")
    currency: str | None = _facet_field(role="money.currency")


class Priced(BaseModel):
    unit_price: Decimal | None = _facet_field(role="money.unit_price")
    list_price: Decimal | None = _facet_field(role="money.list_price")
    compare_at_price: Decimal | None = _facet_field(role="money.compare_at_price")
    price_currency: str | None = _facet_field(role="money.price_currency")
    price_includes_tax: bool | None = _facet_field(role="money.price_includes_tax")


class Discountable(BaseModel):
    sale_price: Decimal | None = _facet_field(role="money.sale_price")
    discount_pct: Decimal | None = _facet_field(role="money.discount_pct")
    is_on_sale: bool | None = _facet_field(role="money.is_on_sale")


class Subscribable(BaseModel):
    subscription_status: Literal["trialing", "active", "past_due", "paused", "canceled", "expired", "incomplete"] | None = _facet_field(role="money.subscription_status")
    billing_interval: Literal["day", "week", "month", "quarter", "year"] | None = _facet_field(role="money.billing_interval")
    billing_interval_count: int | None = _facet_field(role="money.billing_interval_count")
    current_period_start: datetime | None = _facet_field(role="money.current_period_start")
    current_period_end: datetime | None = _facet_field(role="money.current_period_end")
    trial_end: datetime | None = _facet_field(role="money.trial_end")
    recurring_amount: Decimal | None = _facet_field(role="money.recurring_amount")
    cancel_at_period_end: bool | None = _facet_field(role="money.cancel_at_period_end")


class Balanced(BaseModel):
    balance: Decimal | None = _facet_field(role="money.balance")
    balance_currency: str | None = _facet_field(role="money.balance_currency")
    available_balance: Decimal | None = _facet_field(role="money.available_balance")
    pending_balance: Decimal | None = _facet_field(role="money.pending_balance")
    credit_limit: Decimal | None = _facet_field(role="money.credit_limit")


class Invoiced(BaseModel):
    invoice_number: str | None = _facet_field(role="money.invoice_number")
    total: Decimal | None = _facet_field(role="money.total")
    tax: Decimal | None = _facet_field(role="money.tax")
    payment_status: Literal["unpaid", "paid", "partial", "refunded", "void"] | None = _facet_field(role="money.payment_status")
    paid_at: datetime | None = _facet_field(role="money.paid_at")
    invoice_due_at: datetime | None = _facet_field(role="money.invoice_due_at")
