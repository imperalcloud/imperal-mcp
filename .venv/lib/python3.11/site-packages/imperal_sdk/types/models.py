"""Data types returned by SDK clients.

These are the typed return values from StoreProtocol, AIProtocol,
BillingProtocol, StorageProtocol, and HTTPProtocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Document:
    """A document in the extension store.

    Canonical dataclass — the single source of truth for Document shape
    across the SDK. `StoreClient.query/get/query_all/...` all return
    instances of this class.

    Wire contract equivalent: ``imperal_sdk.types.client_contracts.DocumentModel``
    (Pydantic). Field shape + defaults must match — verified by contract test
    ``tests/test_document_contract.py``.
    """
    id: str
    collection: str
    data: dict
    extension_id: str = ""
    tenant_id: str = "default"
    created_at: str = ""
    updated_at: str = ""
    user_id: str = ""

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)


@dataclass
class CompletionResult:
    """Result from ctx.ai.complete()."""
    text: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    stop_reason: str = ""


@dataclass
class LimitsResult:
    """Result from ctx.billing.check_limits()."""
    allowed: bool = True
    balance: int = 0
    plan: str = ""
    limits: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class SubscriptionInfo:
    """Result from ctx.billing.get_subscription()."""
    plan_id: str = ""
    plan_name: str = ""
    status: str = ""
    period: str = "monthly"
    current_period_start: str = ""
    current_period_end: str = ""


@dataclass
class BalanceInfo:
    """Result from ctx.billing.get_balance()."""
    balance: int = 0
    plan: str = ""
    cap: int = 0


@dataclass
class FileInfo:
    """Result from ctx.storage.upload() and ctx.storage.list()."""
    path: str
    size: int = 0
    content_type: str = ""
    created_at: str = ""
    url: str = ""


@dataclass
class HTTPResponse:
    """Result from ctx.http.get/post/put/patch/delete()."""
    status_code: int
    body: dict | str | bytes = ""
    headers: dict = field(default_factory=dict)

    def json(self) -> dict | list:
        # Already-parsed JSON (the prod http client parses on content-type: json,
        # so an array endpoint like WP /wp/v2/posts yields a list body).
        if isinstance(self.body, (dict, list)):
            return self.body
        if isinstance(self.body, (str, bytes, bytearray)):
            import json
            return json.loads(self.body)
        raise ValueError(f"Cannot parse {type(self.body).__name__} body as JSON")

    def text(self) -> str:
        if isinstance(self.body, str):
            return self.body
        if isinstance(self.body, bytes):
            return self.body.decode("utf-8")
        import json
        return json.dumps(self.body)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> None:
        """Raise an exception if status_code indicates an error (4xx/5xx)."""
        if self.status_code >= 400:
            raise HTTPStatusError(self.status_code, self.body)


class HTTPStatusError(Exception):
    """Raised by HTTPResponse.raise_for_status() on 4xx/5xx."""
    def __init__(self, status_code: int, body=None):
        self.status_code = status_code
        self.body = body or ""
        super().__init__(f"HTTP {status_code}: {str(body)[:200]}")


@dataclass
class PaymentMethod:
    """Result item from ctx.billing.list_payment_methods()."""
    id: str = ""
    type: str = "card"
    brand: str = ""
    last4: str = ""
    exp_month: int = 0
    exp_year: int = 0
    is_default: bool = False


@dataclass
class SetupIntentResult:
    """Result from ctx.billing.create_setup_intent() — drives a Stripe add-card flow."""
    client_secret: str = ""
    publishable_key: str = ""


@dataclass
class ChangePlanResult:
    """Result from ctx.billing.change_plan()."""
    action: str = ""
    plan: str = ""
    succeeded: bool = False
    requires_action: bool = False
    client_secret: str = ""
    effective_at: str = ""
    pending: bool = False


@dataclass
class TopupResult:
    """Result from ctx.billing.topup() — drives a Stripe Payment Element."""
    client_secret: str = ""
    payment_intent_id: str = ""
    publishable_key: str = ""
    succeeded: bool = False
    requires_action: bool = False


@dataclass
class PaymentRecord:
    """Result item from ctx.billing.list_payments()."""
    payment_intent_id: str = ""
    amount_cents: int = 0
    currency: str = "usd"
    tokens: int = 0
    status: str = ""
    type: str = ""
    created_at: str | None = None
    completed_at: str | None = None
    receipt_url: str = ""


@dataclass
class PlanInfo:
    """Result item from ctx.billing.list_plans() — the public plan catalog."""
    id: str = ""
    name: str = ""
    price: float = 0.0
    interval: str = "monthly"
    features: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)


@dataclass
class AutoTopupSettings:
    """Result from ctx.billing.get_auto_topup() — auto-recharge configuration."""
    enabled: bool = False
    threshold_pct: int = 10
    recharge_tokens: int = 20000
    recharge_cents: int = 2000
    payment_method_id: str = ""
