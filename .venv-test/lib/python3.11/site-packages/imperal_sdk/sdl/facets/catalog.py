"""Catalog, Products & Inventory family — branding, stock, bundles, materials, compliance. Namespace catalog.*"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class Branded(BaseModel):
    brand: str | None = _facet_field(role="catalog.brand")
    manufacturer: str | None = _facet_field(role="catalog.manufacturer")
    model_name: str | None = _facet_field(role="catalog.model_name")
    model_year: int | None = _facet_field(role="catalog.model_year")
    country_of_origin: str | None = _facet_field(role="catalog.country_of_origin")


class Inventory(BaseModel):
    in_stock: bool | None = _facet_field(role="catalog.in_stock")
    availability: Literal["in_stock", "out_of_stock", "preorder", "backorder", "discontinued"] | None = _facet_field(role="catalog.availability")
    low_stock_threshold: int | None = _facet_field(role="catalog.low_stock_threshold")
    is_low_stock: bool | None = _facet_field(role="catalog.is_low_stock")
    backorderable: bool | None = _facet_field(role="catalog.backorderable")
    preorder: bool | None = _facet_field(role="catalog.preorder")


class Bundle(BaseModel):
    is_bundle: bool | None = _facet_field(role="catalog.is_bundle")
    bundle_items: list[Ref] | None = _facet_field(role="catalog.bundle_items")
    bundle_type: str | None = _facet_field(role="catalog.bundle_type")


class ColorMaterial(BaseModel):
    color: str | None = _facet_field(role="catalog.color")
    # Prefixed to avoid collision with identity.Iconified.color_hex (role core.color_hex)
    material_color_hex: str | None = _facet_field(role="catalog.color_hex")
    material: str | None = _facet_field(role="catalog.material")
    pattern: str | None = _facet_field(role="catalog.pattern")
    finish: str | None = _facet_field(role="catalog.finish")


class ProductCompliance(BaseModel):
    certifications: list[str] | None = _facet_field(role="catalog.certifications")
    hs_code: str | None = _facet_field(role="catalog.hs_code")
    age_restriction: int | None = _facet_field(role="catalog.age_restriction")
    restricted_regions: list[str] | None = _facet_field(role="catalog.restricted_regions")
    requires_prescription: bool | None = _facet_field(role="catalog.requires_prescription")
