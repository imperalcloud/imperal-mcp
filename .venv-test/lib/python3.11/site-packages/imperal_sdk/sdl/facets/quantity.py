"""Quantities & Units family — measures, ranges, dimensions, physical quantities. Namespace quantity.*"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class Measured(BaseModel):
    value: Decimal | None = _facet_field(role="quantity.value")
    unit: str | None = _facet_field(role="quantity.unit")
    dimension: str | None = _facet_field(role="quantity.dimension")
    unit_family: str | None = _facet_field(role="quantity.unit_family")
    value_type: str | None = _facet_field(role="quantity.value_type")
    uncertainty: Decimal | None = _facet_field(role="quantity.uncertainty")
    formatted_value: str | None = _facet_field(role="quantity.formatted_value")


class Range(BaseModel):
    min_value: Decimal | None = _facet_field(role="quantity.min_value")
    max_value: Decimal | None = _facet_field(role="quantity.max_value")
    target: Decimal | None = _facet_field(role="quantity.target")


class Dimensions3D(BaseModel):
    dim_width: float | None = _facet_field(role="quantity.dim_width")
    dim_height: float | None = _facet_field(role="quantity.dim_height")
    dim_depth: float | None = _facet_field(role="quantity.dim_depth")
    dim_unit: str | None = _facet_field(role="quantity.dim_unit")


class Area(BaseModel):
    area_m2: Decimal | None = _facet_field(role="quantity.area_m2")
    area_unit: str | None = _facet_field(role="quantity.area_unit")


class Angle(BaseModel):
    angle_deg: Decimal | None = _facet_field(role="quantity.angle_deg")
    angle_unit: str | None = _facet_field(role="quantity.angle_unit")


class Bitrate(BaseModel):
    bitrate_bps: int | None = _facet_field(role="quantity.bitrate_bps")
    bitrate_unit: str | None = _facet_field(role="quantity.bitrate_unit")


class DataSize(BaseModel):
    bytes: int | None = _facet_field(role="quantity.bytes")
    data_size_unit: str | None = _facet_field(role="quantity.data_size_unit")


class Temperature(BaseModel):
    temp_c: float | None = _facet_field(role="quantity.temp_c")
    temp_unit: str | None = _facet_field(role="quantity.temp_unit")


class Length(BaseModel):
    length_m: float | None = _facet_field(role="quantity.length_m")
    length_unit: str | None = _facet_field(role="quantity.length_unit")


class Weight(BaseModel):
    weight_kg: float | None = _facet_field(role="quantity.weight_kg")
    weight_unit: str | None = _facet_field(role="quantity.weight_unit")


class Speed(BaseModel):
    speed_mps: float | None = _facet_field(role="quantity.speed_mps")
    speed_unit: str | None = _facet_field(role="quantity.speed_unit")


class Percentage(BaseModel):
    percent: float | None = _facet_field(role="quantity.percent")
