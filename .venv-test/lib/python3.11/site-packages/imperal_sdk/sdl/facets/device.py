"""Devices / IoT / Sensors / Health family — device identity, state, sensor readings,
actuator state, consumables, activity, body composition, vitals, biometrics, sleep,
AI provenance. Namespace device.*"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class DeviceIdentity(BaseModel):
    device_id: str | None = _facet_field(role="device.device_id")
    # device_model: plan-specified prefix to co-exist with generic "model" fields
    device_model: str | None = _facet_field(role="device.device_model")
    device_manufacturer: str | None = _facet_field(role="device.device_manufacturer")
    firmware_version: str | None = _facet_field(role="device.firmware_version")
    serial: str | None = _facet_field(role="device.serial")


class DeviceState(BaseModel):
    online: bool | None = _facet_field(role="device.online")
    battery_pct: int | None = _facet_field(role="device.battery_pct")
    signal_strength: int | None = _facet_field(role="device.signal_strength")
    # device_last_seen_at: prefixed to avoid collision with people.Presence.last_seen_at
    device_last_seen_at: datetime | None = _facet_field(role="device.device_last_seen_at")


class SensorReading(BaseModel):
    sensor_type: str | None = _facet_field(role="device.sensor_type")
    # sensor_value: plan-specified prefix to differentiate from quantity.Measured.value
    sensor_value: float | None = _facet_field(role="device.sensor_value")
    sensor_unit: str | None = _facet_field(role="device.sensor_unit")
    measured_at: datetime | None = _facet_field(role="device.measured_at")
    quality: str | None = _facet_field(role="device.quality")


class ActuatorState(BaseModel):
    on: bool | None = _facet_field(role="device.on")
    level_pct: int | None = _facet_field(role="device.level_pct")
    mode: str | None = _facet_field(role="device.mode")
    locked: bool | None = _facet_field(role="device.locked")
    # actuator_position: prefixed to avoid collision with task.Boarded.position (role task.position)
    actuator_position: str | None = _facet_field(role="device.actuator_position")
    color_temp_k: int | None = _facet_field(role="device.color_temp_k")
    # actuator_color_hex: plan-specified prefix to avoid collision with identity.Iconified.color_hex
    # (role core.color_hex) and catalog.ColorMaterial.color_hex (role catalog.color_hex)
    actuator_color_hex: str | None = _facet_field(role="device.actuator_color_hex")


class Consumable(BaseModel):
    consumable_type: str | None = _facet_field(role="device.consumable_type")
    remaining_pct: int | None = _facet_field(role="device.remaining_pct")
    replace_after_at: datetime | None = _facet_field(role="device.replace_after_at")
    low: bool | None = _facet_field(role="device.low")


class ActivityMetrics(BaseModel):
    steps: int | None = _facet_field(role="device.steps")
    # activity_distance_m: plan-specified prefix to avoid collision with geo.Routed.distance_m
    activity_distance_m: float | None = _facet_field(role="device.activity_distance_m")
    active_calories_kcal: float | None = _facet_field(role="device.active_calories_kcal")
    active_minutes: int | None = _facet_field(role="device.active_minutes")
    floors_climbed: int | None = _facet_field(role="device.floors_climbed")


class BodyComposition(BaseModel):
    # body_weight_kg: prefixed to avoid collision with quantity.Weight.weight_kg (role quantity.weight_kg)
    body_weight_kg: float | None = _facet_field(role="device.weight_kg")
    bmi: float | None = _facet_field(role="device.bmi")
    body_fat_pct: float | None = _facet_field(role="device.body_fat_pct")
    muscle_mass_kg: float | None = _facet_field(role="device.muscle_mass_kg")
    # body_measured_at: plan-specified prefix to differentiate from sensor measured_at
    body_measured_at: datetime | None = _facet_field(role="device.body_measured_at")


class VitalSign(BaseModel):
    heart_rate_bpm: int | None = _facet_field(role="device.heart_rate_bpm")
    blood_pressure: str | None = _facet_field(role="device.blood_pressure")
    spo2_pct: float | None = _facet_field(role="device.spo2_pct")
    body_temp_c: float | None = _facet_field(role="device.body_temp_c")
    respiratory_rate: int | None = _facet_field(role="device.respiratory_rate")


class Biometric(BaseModel):
    # biometric_* fields: plan-specified prefixes to avoid collisions with generic type/value/unit
    biometric_type: str | None = _facet_field(role="device.biometric_type")
    biometric_value: float | None = _facet_field(role="device.biometric_value")
    biometric_unit: str | None = _facet_field(role="device.biometric_unit")
    biometric_measured_at: datetime | None = _facet_field(role="device.biometric_measured_at")
    biometric_context: str | None = _facet_field(role="device.biometric_context")
    reference_low: float | None = _facet_field(role="device.reference_low")
    reference_high: float | None = _facet_field(role="device.reference_high")


class SleepRecord(BaseModel):
    sleep_duration_s: int | None = _facet_field(role="device.sleep_duration_s")
    sleep_stages: dict[str, int] | None = _facet_field(role="device.sleep_stages")
    sleep_quality_score: float | None = _facet_field(role="device.sleep_quality_score")
    in_bed_at: datetime | None = _facet_field(role="device.in_bed_at")
    awake_at: datetime | None = _facet_field(role="device.awake_at")


class AIProvenance(BaseModel):
    generated_by_ai: bool | None = _facet_field(role="device.generated_by_ai")
    ai_model: str | None = _facet_field(role="device.ai_model")
    ai_confidence: float | None = _facet_field(role="device.ai_confidence")
    prompt_ref: str | None = _facet_field(role="device.prompt_ref")
    reviewed_by_human: bool | None = _facet_field(role="device.reviewed_by_human")
