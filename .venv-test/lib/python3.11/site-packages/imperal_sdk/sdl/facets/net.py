"""Tech / Infra / Network / Data family — network assets, API endpoints, host resources,
compute specs, containers, service health, certificates, data records, config settings,
backups. Namespace net.*

Field-name collision notes:
- ApiEndpoint uses ``api_path`` (role ``net.path``) instead of ``path`` to avoid
  colliding with media.FileObject.path when both facets are mixed together.
- ConfigSetting uses ``config_value_type`` (role ``net.value_type``) instead of
  ``value_type`` to avoid colliding with quantity.Measured.value_type.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class NetAsset(BaseModel):
    domain: str | None = _facet_field(role="net.domain")
    ip: str | None = _facet_field(role="net.ip")
    port: int | None = _facet_field(role="net.port")
    protocol: str | None = _facet_field(role="net.protocol")
    record_type: str | None = _facet_field(role="net.record_type")


class ApiEndpoint(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] | None = _facet_field(role="net.method")
    # Prefixed to avoid collision with media.FileObject.path
    api_path: str | None = _facet_field(role="net.path")
    operation_id: str | None = _facet_field(role="net.operation_id")
    auth_required: bool | None = _facet_field(role="net.auth_required")
    deprecated: bool | None = _facet_field(role="net.deprecated")


class HostResource(BaseModel):
    hostname: str | None = _facet_field(role="net.hostname")
    resource_id: str | None = _facet_field(role="net.resource_id")
    environment: str | None = _facet_field(role="net.environment")
    host_region: str | None = _facet_field(role="net.host_region")


class ComputeSpec(BaseModel):
    vcpus: int | None = _facet_field(role="net.vcpus")
    memory_bytes: int | None = _facet_field(role="net.memory_bytes")
    disk_bytes: int | None = _facet_field(role="net.disk_bytes")
    gpu_count: int | None = _facet_field(role="net.gpu_count")
    arch: Literal["x86_64", "arm64", "riscv"] | None = _facet_field(role="net.arch")


class Container(BaseModel):
    container_id: str | None = _facet_field(role="net.container_id")
    container_name: str | None = _facet_field(role="net.container_name")
    image: str | None = _facet_field(role="net.image")
    image_digest: str | None = _facet_field(role="net.image_digest")
    runtime: Literal["docker", "containerd", "podman", "lxc"] | None = _facet_field(role="net.runtime")
    compose_project: str | None = _facet_field(role="net.compose_project")


class ServiceHealth(BaseModel):
    health: Literal["healthy", "degraded", "down"] | None = _facet_field(role="net.health")
    uptime_s: int | None = _facet_field(role="net.uptime_s")
    last_check_at: datetime | None = _facet_field(role="net.last_check_at")


class Certificated(BaseModel):
    cert_issuer: str | None = _facet_field(role="net.cert_issuer")
    cert_subject: str | None = _facet_field(role="net.cert_subject")
    not_after: datetime | None = _facet_field(role="net.not_after")
    fingerprint: str | None = _facet_field(role="net.fingerprint")
    cert_is_valid: bool | None = _facet_field(role="net.cert_is_valid")


class DataRecord(BaseModel):
    table: str | None = _facet_field(role="net.table")
    row_id: str | None = _facet_field(role="net.row_id")
    query: str | None = _facet_field(role="net.query")
    schema_ref: str | None = _facet_field(role="net.schema_ref")


class ConfigSetting(BaseModel):
    config_key: str | None = _facet_field(role="net.config_key")
    config_value: str | None = _facet_field(role="net.config_value")
    # Prefixed to avoid collision with quantity.Measured.value_type
    config_value_type: Literal["string", "int", "float", "bool", "json"] | None = _facet_field(role="net.value_type")
    is_secret: bool | None = _facet_field(role="net.is_secret")
    config_source: str | None = _facet_field(role="net.config_source")
    default_value: str | None = _facet_field(role="net.default_value")


class Backup(BaseModel):
    snapshot_id: str | None = _facet_field(role="net.snapshot_id")
    source_resource: str | None = _facet_field(role="net.source_resource")
    taken_at: datetime | None = _facet_field(role="net.taken_at")
    backup_size_bytes: int | None = _facet_field(role="net.backup_size_bytes")
    retain_until: datetime | None = _facet_field(role="net.retain_until")
    backup_kind: Literal["full", "incremental", "differential", "snapshot"] | None = _facet_field(role="net.backup_kind")
    # Prefixed to avoid collision with rating.Reviewed.is_verified (role rating.is_verified)
    backup_is_verified: bool | None = _facet_field(role="net.is_verified")
