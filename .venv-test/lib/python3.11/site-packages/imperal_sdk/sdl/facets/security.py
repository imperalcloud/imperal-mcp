"""Security / Legal / Compliance / Audit family — access control, permissions,
audit trails, consent, compliance frameworks, attestation, signing, retention,
alerting, case management, risk scoring. Namespace sec.*"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class AccessLeveled(BaseModel):
    classification: Literal["public", "internal", "confidential", "restricted", "secret", "top_secret"] | None = _facet_field(role="sec.classification")
    clearance_required: str | None = _facet_field(role="sec.clearance_required")
    # access_visibility: prefixed to avoid collision with identity.Lifecycle.visibility (role core.visibility)
    access_visibility: Literal["private", "team", "organization", "public"] | None = _facet_field(role="sec.visibility")
    handling_caveats: list[str] | None = _facet_field(role="sec.handling_caveats")


class Permissioned(BaseModel):
    # sec_permissions: prefixed to avoid collision with media.FileObject.permissions (role media.permissions)
    sec_permissions: list[str] | None = _facet_field(role="sec.permissions")
    role: str | None = _facet_field(role="sec.role")
    can_read: bool | None = _facet_field(role="sec.can_read")
    can_write: bool | None = _facet_field(role="sec.can_write")
    can_delete: bool | None = _facet_field(role="sec.can_delete")
    can_share: bool | None = _facet_field(role="sec.can_share")


class Auditable(BaseModel):
    actor: Ref | None = _facet_field(role="sec.actor")
    action: str | None = _facet_field(role="sec.action")
    # audit_target: prefixed to avoid collision with quantity.Range.target (role quantity.target)
    audit_target: Ref | None = _facet_field(role="sec.target")
    occurred_at: datetime | None = _facet_field(role="sec.occurred_at")
    outcome: Literal["success", "failure", "denied", "error"] | None = _facet_field(role="sec.outcome")
    source_ip: str | None = _facet_field(role="sec.source_ip")
    changes: dict | None = _facet_field(role="sec.changes")


class Consented(BaseModel):
    consent_purpose: str | None = _facet_field(role="sec.consent_purpose")
    consent_state: Literal["granted", "withdrawn", "pending", "expired"] | None = _facet_field(role="sec.consent_state")
    consent_subject: Ref | None = _facet_field(role="sec.consent_subject")
    granted_at: datetime | None = _facet_field(role="sec.granted_at")
    legal_basis: Literal["consent", "contract", "legal_obligation", "vital_interest", "public_task", "legitimate_interest"] | None = _facet_field(role="sec.legal_basis")
    consent_proof: str | None = _facet_field(role="sec.consent_proof")


class Compliant(BaseModel):
    framework: str | None = _facet_field(role="sec.framework")
    control_id: str | None = _facet_field(role="sec.control_id")
    compliance_status: Literal["compliant", "non_compliant", "partial", "not_applicable", "not_assessed"] | None = _facet_field(role="sec.compliance_status")
    last_assessed_at: datetime | None = _facet_field(role="sec.last_assessed_at")
    assessed_by: Ref | None = _facet_field(role="sec.assessed_by")


class Attested(BaseModel):
    attestation_type: str | None = _facet_field(role="sec.attestation_type")
    attestation_result: Literal["verified", "rejected", "pending", "expired", "needs_review"] | None = _facet_field(role="sec.attestation_result")
    attested_by: Ref | None = _facet_field(role="sec.attested_by")
    # attestation_confidence: plan-specified prefix to differentiate from bare "confidence"
    attestation_confidence: Decimal | None = _facet_field(role="sec.attestation_confidence")


class Signed(BaseModel):
    signature: str | None = _facet_field(role="sec.signature")
    signer: Ref | None = _facet_field(role="sec.signer")
    algorithm: str | None = _facet_field(role="sec.algorithm")
    # signature_is_valid: plan-specified prefix to avoid confusion with net.Certificated.cert_is_valid
    signature_is_valid: bool | None = _facet_field(role="sec.signature_is_valid")
    signed_at: datetime | None = _facet_field(role="sec.signed_at")


class Retained(BaseModel):
    retention_class: str | None = _facet_field(role="sec.retention_class")
    # sec_retain_until: prefixed to avoid collision with net.Backup.retain_until (role net.retain_until)
    sec_retain_until: datetime | None = _facet_field(role="sec.retain_until")
    legal_hold: bool | None = _facet_field(role="sec.legal_hold")


class Alertable(BaseModel):
    # alert_severity: plan-specified prefix to avoid collision with task.Prioritized.severity (role task.severity)
    alert_severity: Literal["info", "warning", "critical", "emergency"] | None = _facet_field(role="sec.alert_severity")
    alert_state: Literal["firing", "pending", "resolved", "silenced"] | None = _facet_field(role="sec.alert_state")
    fired_at: datetime | None = _facet_field(role="sec.fired_at")
    resolved_at: datetime | None = _facet_field(role="sec.resolved_at")
    rule_name: str | None = _facet_field(role="sec.rule_name")
    # alert_threshold: plan-specified prefix to avoid collision with metric.Threshold.threshold
    alert_threshold: float | None = _facet_field(role="sec.alert_threshold")


class Caseable(BaseModel):
    case_number: str | None = _facet_field(role="sec.case_number")
    case_type: str | None = _facet_field(role="sec.case_type")
    case_stage: str | None = _facet_field(role="sec.case_stage")
    opened_at: datetime | None = _facet_field(role="sec.opened_at")
    closed_at: datetime | None = _facet_field(role="sec.closed_at")
    # case_resolution: plan-specified prefix to avoid collision with task.Completable.resolution
    case_resolution: str | None = _facet_field(role="sec.case_resolution")
    jurisdiction: str | None = _facet_field(role="sec.jurisdiction")


class RiskScored(BaseModel):
    risk_score: float | None = _facet_field(role="sec.risk_score")
    risk_level: Literal["low", "medium", "high", "critical"] | None = _facet_field(role="sec.risk_level")
    risk_factors: list[str] | None = _facet_field(role="sec.risk_factors")
