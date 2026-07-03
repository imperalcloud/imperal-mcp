# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any
import httpx

from imperal_sdk.types.models import (
    BalanceInfo, PaymentMethod, SetupIntentResult, ChangePlanResult,
    TopupResult, PaymentRecord, PlanInfo, AutoTopupSettings,
)

log = logging.getLogger(__name__)


@dataclass
class LimitsResult:
    plan: str
    usage: dict[str, int]
    limits: dict[str, int]
    exceeded: list[str]

    def is_exceeded(self, meter: str) -> bool:
        return meter in self.exceeded

    @property
    def any_exceeded(self) -> bool:
        return bool(self.exceeded)


@dataclass
class SubscriptionInfo:
    plan: str
    status: str
    started_at: str | None = None
    expires_at: str | None = None
    cancel_at_period_end: bool = False


class BillingClient:
    """Read-only billing client for extensions.

    When initialized with service_token (kernel context), uses internal
    endpoints with X-Service-Token header. When initialized with auth_token
    (user JWT from Panel), uses public endpoints with Authorization header.
    """

    def __init__(
        self, gateway_url: str, auth_token: str = "",
        service_token: str = "", user_id: str = "",
    ):
        self._gateway_url = gateway_url.rstrip("/")
        self._service_token = service_token
        self._auth_token = auth_token
        self._user_id = user_id

    def _headers(self) -> dict:
        if self._service_token:
            h = {"X-Service-Token": self._service_token}
            if self._user_id:
                h["X-Acting-User"] = self._user_id
            return h
        return {"Authorization": f"Bearer {self._auth_token}"}

    def _uid(self, user: Any = None) -> str:
        return self._user_id or (getattr(user, "id", "") if user else "")

    async def check_limits(self, user: Any = None) -> LimitsResult:
        uid = self._uid(user)
        try:
            async with httpx.AsyncClient() as client:
                if self._service_token and uid:
                    resp = await client.get(
                        f"{self._gateway_url}/v1/billing/internal/user-limits/{uid}",
                        headers=self._headers(), timeout=10)
                else:
                    resp = await client.get(
                        f"{self._gateway_url}/v1/billing/usage",
                        headers=self._headers(), timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return LimitsResult(
                    plan=data.get("plan", "free"),
                    usage=data.get("usage", {}),
                    limits=data.get("limits", {}),
                    exceeded=data.get("exceeded", []),
                )
        except Exception as e:
            log.warning("Billing check_limits failed: %s", e)
            return LimitsResult(plan="unknown", usage={}, limits={}, exceeded=[])

    async def get_subscription(self, user: Any = None) -> SubscriptionInfo:
        uid = self._uid(user)
        try:
            async with httpx.AsyncClient() as client:
                if self._service_token and uid:
                    resp = await client.get(
                        f"{self._gateway_url}/v1/billing/internal/subscription/{uid}",
                        headers=self._headers(), timeout=10)
                else:
                    resp = await client.get(
                        f"{self._gateway_url}/v1/billing/subscription",
                        headers=self._headers(), timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return SubscriptionInfo(
                    plan=data.get("plan", "free"),
                    status=data.get("status", "unknown"),
                    started_at=data.get("started_at"),
                    expires_at=data.get("expires_at"),
                    cancel_at_period_end=bool(data.get("cancel_at_period_end", False)),
                )
        except Exception as e:
            log.warning("Billing get_subscription failed: %s", e)
            return SubscriptionInfo(plan="unknown", status="unavailable")

    async def track_usage(self, meter: str, quantity: int = 1, user: Any = None) -> bool:
        """Track usage for a given meter. Returns True on success.

        Requires service_token — usage tracking is a server-to-server operation.
        The gateway endpoint is POST /v1/billing/internal/usage/track (service
        token required). There is no public user-facing track endpoint; calling
        without a service token logs a warning and returns False.
        """
        uid = self._uid(user)
        if not self._service_token:
            log.warning(
                "Billing track_usage requires a service token; "
                "no-token path is not supported (no public track endpoint). "
                "Returning False without attempting the request."
            )
            return False
        try:
            async with httpx.AsyncClient() as client:
                payload: dict = {"meter": meter, "quantity": quantity}
                if uid:
                    payload["user_id"] = uid
                    payload["tenant_id"] = "default"
                resp = await client.post(
                    f"{self._gateway_url}/v1/billing/internal/usage/track",
                    json=payload, headers=self._headers(), timeout=10)
                return resp.status_code == 200
        except Exception as e:
            log.warning("Billing track_usage failed: %s", e)
            return False

    async def get_balance(self, user: Any = None) -> BalanceInfo:
        """Get current token balance and plan cap."""
        uid = self._uid(user)
        try:
            async with httpx.AsyncClient() as client:
                if self._service_token and uid:
                    resp = await client.get(
                        f"{self._gateway_url}/v1/billing/internal/balance/{uid}",
                        headers=self._headers(), timeout=10)
                else:
                    resp = await client.get(
                        f"{self._gateway_url}/v1/billing/balance",
                        headers=self._headers(), timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return BalanceInfo(
                    balance=data.get("balance", 0),
                    plan=data.get("plan", ""),
                    cap=data.get("cap", 0),
                )
        except Exception as e:
            log.warning("Billing get_balance failed: %s", e)
            return BalanceInfo(balance=0, plan="unknown", cap=0)

    # ─── Payment methods + plan changes + top-up + payment history ──────── #

    async def list_payment_methods(self, user: Any = None) -> list[PaymentMethod]:
        uid = self._uid(user)
        try:
            async with httpx.AsyncClient() as client:
                url = (f"{self._gateway_url}/v1/billing/internal/payment-methods/{uid}"
                       if (self._service_token and uid)
                       else f"{self._gateway_url}/v1/billing/payment-methods")
                resp = await client.get(url, headers=self._headers(), timeout=10)
                resp.raise_for_status()
                return [PaymentMethod(**m) for m in resp.json()]
        except Exception as e:
            log.warning("Billing list_payment_methods failed: %s", e)
            return []

    async def list_payments(self, user: Any = None, limit: int = 50, offset: int = 0) -> list[PaymentRecord]:
        uid = self._uid(user)
        try:
            async with httpx.AsyncClient() as client:
                if self._service_token and uid:
                    url = f"{self._gateway_url}/v1/billing/internal/payments/{uid}"
                else:
                    url = f"{self._gateway_url}/v1/billing/payments"
                resp = await client.get(url, headers=self._headers(),
                                        params={"limit": limit, "offset": offset}, timeout=15)
                resp.raise_for_status()
                return [PaymentRecord(**p) for p in resp.json()]
        except Exception as e:
            log.warning("Billing list_payments failed: %s", e)
            return []

    async def create_setup_intent(self, user: Any = None) -> SetupIntentResult:
        """Add-card SetupIntent. Surfaces errors (the ext needs the client secret)."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/billing/payment-methods/setup",
                                     headers=self._headers(), timeout=10)
            resp.raise_for_status()
            d = resp.json()
            return SetupIntentResult(client_secret=d.get("client_secret", ""),
                                     publishable_key=d.get("publishable_key", ""))

    async def set_default_payment_method(self, pm_id: str, user: Any = None) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.put(f"{self._gateway_url}/v1/billing/payment-methods/{pm_id}/default",
                                    headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return True

    async def remove_payment_method(self, pm_id: str, user: Any = None) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(f"{self._gateway_url}/v1/billing/payment-methods/{pm_id}",
                                       headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return True

    async def change_plan(self, plan_id: str, period: str = "monthly", user: Any = None) -> ChangePlanResult:
        """Upgrade (prorated, immediate) / downgrade (scheduled). Surfaces errors."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/billing/change-plan",
                                     json={"plan_id": plan_id, "period": period},
                                     headers=self._headers(), timeout=15)
            resp.raise_for_status()
            d = resp.json()
            return ChangePlanResult(
                action=d.get("action", ""), plan=d.get("plan", ""),
                succeeded=bool(d.get("succeeded", False)),
                requires_action=bool(d.get("requires_action", False)),
                client_secret=d.get("client_secret", ""),
                effective_at=d.get("effective_at", "") or "",
                pending=bool(d.get("pending", False)))

    async def topup(self, tokens: int, price_cents: int, save_payment_method: bool = True,
                    off_session: bool = True, user: Any = None) -> TopupResult:
        """Token top-up PaymentIntent. Surfaces errors.

        With ``off_session=True`` (default) the gateway attempts an immediate
        off-session charge against the saved card and returns ``succeeded`` /
        ``requires_action``. The Element path (``off_session=False``) returns
        the ``client_secret`` instead.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/billing/topup",
                                     json={"tokens": tokens, "price_cents": price_cents,
                                           "save_payment_method": save_payment_method,
                                           "off_session": off_session},
                                     headers=self._headers(), timeout=15)
            resp.raise_for_status()
            d = resp.json()
            return TopupResult(client_secret=d.get("client_secret", ""),
                               payment_intent_id=d.get("payment_intent_id", ""),
                               publishable_key=d.get("publishable_key", ""),
                               succeeded=bool(d.get("succeeded", False)),
                               requires_action=bool(d.get("requires_action", False)))

    async def create_billing_portal_session(self, user: Any = None) -> str:
        """Create a Stripe Customer Portal session and return its hosted URL.
        Surfaces errors (the ext needs the URL)."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/billing/portal",
                                     headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json().get("url", "")

    async def list_plans(self, user: Any = None) -> list[PlanInfo]:
        """Public plan catalog. Safe-degrades to []."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._gateway_url}/v1/billing/plans",
                                        headers=self._headers(), timeout=10)
                resp.raise_for_status()
                return [PlanInfo(**p) for p in resp.json()]
        except Exception as e:
            log.warning("Billing list_plans failed: %s", e)
            return []

    async def get_auto_topup(self, user: Any = None) -> AutoTopupSettings:
        """Safe-degrades to disabled defaults."""
        uid = self._uid(user)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._gateway_url}/v1/billing/auto-topup",
                                        headers=self._headers(), timeout=10)
                resp.raise_for_status()
                return AutoTopupSettings(**resp.json())
        except Exception as e:
            log.warning("Billing get_auto_topup failed: %s", e)
            return AutoTopupSettings()

    async def set_auto_topup(self, enabled: bool, threshold_pct: int = 10,
                             recharge_tokens: int = 20000, payment_method_id: str = "",
                             user: Any = None) -> bool:
        """Surfaces errors."""
        async with httpx.AsyncClient() as client:
            resp = await client.put(f"{self._gateway_url}/v1/billing/auto-topup",
                json={"enabled": enabled, "threshold_pct": threshold_pct,
                      "recharge_tokens": recharge_tokens, "payment_method_id": payment_method_id},
                headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return True

    async def cancel_subscription(self, user: Any = None) -> dict:
        """Cancel at period end. Surfaces errors. Returns the gateway result dict."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/billing/cancel",
                                     headers=self._headers(), timeout=15)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def resume_subscription(self, user: Any = None) -> dict:
        """Undo a pending cancel-at-period-end. Surfaces errors. Returns the
        gateway result dict ({status, plan, expires_at, cancel_at_period_end})."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/billing/resume",
                                     headers=self._headers(), timeout=15)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def renew_subscription(self, user: Any = None) -> dict:
        """Renew an EXPIRED subscription for the same plan — charges the saved
        default card for one fresh period and restores access immediately.
        Surfaces errors (402 no-card / SCA, 409 not-expired). Returns the
        gateway result dict ({status, plan, expires_at, payment_intent_id})."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/billing/renew",
                                     headers=self._headers(), timeout=20)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def update_billing_profile(self, profile: dict, user: Any = None) -> bool:
        """Surfaces errors. profile keys: name/company/vat/country."""
        async with httpx.AsyncClient() as client:
            resp = await client.put(f"{self._gateway_url}/v1/billing/profile",
                                    json=profile, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return True
