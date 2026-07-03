"""Location & Geo family — coordinates, postal addresses, administrative regions,
bounding boxes, geofences, routing, places. Namespace geo.*

Field-name collision note: Geolocated uses ``geo_speed_mps`` (role ``geo.speed_mps``)
instead of ``speed_mps`` to avoid colliding with quantity.Speed.speed_mps when both
facets are mixed into the same entity.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class Geolocated(BaseModel):
    lat: float | None = _facet_field(role="geo.lat")
    lon: float | None = _facet_field(role="geo.lon")
    altitude_m: float | None = _facet_field(role="geo.altitude_m")
    accuracy_m: float | None = _facet_field(role="geo.accuracy_m")
    heading_deg: float | None = _facet_field(role="geo.heading_deg")
    # Prefixed to avoid collision with quantity.Speed.speed_mps
    geo_speed_mps: float | None = _facet_field(role="geo.speed_mps")
    located_at: datetime | None = _facet_field(role="geo.located_at")


class PostalAddress(BaseModel):
    street: str | None = _facet_field(role="geo.street")
    city: str | None = _facet_field(role="geo.city")
    postal_code: str | None = _facet_field(role="geo.postal_code")
    region: str | None = _facet_field(role="geo.region")
    country: str | None = _facet_field(role="geo.country")


class AdminRegion(BaseModel):
    country_code: str | None = _facet_field(role="geo.country_code")
    region_code: str | None = _facet_field(role="geo.region_code")
    county: str | None = _facet_field(role="geo.county")
    locality: str | None = _facet_field(role="geo.locality")
    neighborhood: str | None = _facet_field(role="geo.neighborhood")
    continent: str | None = _facet_field(role="geo.continent")


class BoundingBox(BaseModel):
    min_lat: float | None = _facet_field(role="geo.min_lat")
    min_lon: float | None = _facet_field(role="geo.min_lon")
    max_lat: float | None = _facet_field(role="geo.max_lat")
    max_lon: float | None = _facet_field(role="geo.max_lon")


class Geofence(BaseModel):
    center_lat: float | None = _facet_field(role="geo.center_lat")
    center_lon: float | None = _facet_field(role="geo.center_lon")
    radius_m: float | None = _facet_field(role="geo.radius_m")
    trigger: Literal["enter", "exit", "dwell", "both"] | None = _facet_field(role="geo.trigger")
    dwell_s: int | None = _facet_field(role="geo.dwell_s")


class Routed(BaseModel):
    origin: str | None = _facet_field(role="geo.origin")
    destination: str | None = _facet_field(role="geo.destination")
    distance_m: float | None = _facet_field(role="geo.distance_m")
    route_duration_s: int | None = _facet_field(role="geo.route_duration_s")
    waypoints: list[str] | None = _facet_field(role="geo.waypoints")


class Placed(BaseModel):
    place_name: str | None = _facet_field(role="geo.place_name")
    place_type: str | None = _facet_field(role="geo.place_type")
    plus_code: str | None = _facet_field(role="geo.plus_code")
