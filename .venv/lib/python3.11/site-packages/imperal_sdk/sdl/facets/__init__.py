"""SDL standard facet library — composable typed mixins.

Each family module defines BaseModel mixins whose fields carry standard semantic
roles (via _facet_field). Family modules are imported here as they land; this
file is the aggregate export surface (re-exported from imperal_sdk.sdl).
"""
from imperal_sdk.sdl.facets.identity import Localized, Versioned, Iconified, Lifecycle
from imperal_sdk.sdl.facets.time import Timestamped, Schedulable, Duration, Recurring, Booked
from imperal_sdk.sdl.facets.people import Authorship, Assignable, Participants, Correspondents, ContactPoints, Presence
from imperal_sdk.sdl.facets.content import Bodied, Excerptable, Categorized, Attached, Editorial
from imperal_sdk.sdl.facets.comm import Conversational, Threaded, MessageState, Reactable, Callable, Draftable
from imperal_sdk.sdl.facets.media import FileObject, ImageMedia, AudioTrack, VideoTrack, Archive, ContentSafety, Transcribable
from imperal_sdk.sdl.facets.quantity import Measured, Range, Dimensions3D, Area, Angle, Bitrate, DataSize, Temperature, Length, Weight, Speed, Percentage
from imperal_sdk.sdl.facets.money import Monetary, Priced, Discountable, Subscribable, Balanced, Invoiced
from imperal_sdk.sdl.facets.catalog import Branded, Inventory, Bundle, ColorMaterial, ProductCompliance
from imperal_sdk.sdl.facets.task import Prioritized, Progress, Completable, Blockable, Dependencies, Boarded, Checklist, WorkflowState, Approvable, Estimable
from imperal_sdk.sdl.facets.geo import Geolocated, PostalAddress, AdminRegion, BoundingBox, Geofence, Routed, Placed
from imperal_sdk.sdl.facets.net import NetAsset, ApiEndpoint, HostResource, ComputeSpec, Container, ServiceHealth, Certificated, DataRecord, ConfigSetting, Backup
from imperal_sdk.sdl.facets.metric import Aggregated, TimeSeriesPoint, Trended, Confident, Threshold, Dimensioned
from imperal_sdk.sdl.facets.event import Eventful, Capacity, RSVP, Ticketed, AdmissionPolicy, AgendaSlot, Cancellation, CalendarFeed
from imperal_sdk.sdl.facets.rating import Rated, Reviewed, Sentiment, Voted
from imperal_sdk.sdl.facets.security import AccessLeveled, Permissioned, Auditable, Consented, Compliant, Attested, Signed, Retained, Alertable, Caseable, RiskScored
from imperal_sdk.sdl.facets.device import DeviceIdentity, DeviceState, SensorReading, ActuatorState, Consumable, ActivityMetrics, BodyComposition, VitalSign, Biometric, SleepRecord, AIProvenance

__all__: list[str] = [
    # Identity & Provenance
    "Localized", "Versioned", "Iconified", "Lifecycle",
    # Time
    "Timestamped", "Schedulable", "Duration", "Recurring", "Booked",
    # People
    "Authorship", "Assignable", "Participants", "Correspondents", "ContactPoints", "Presence",
    # Content
    "Bodied", "Excerptable", "Categorized", "Attached", "Editorial",
    # Communication
    "Conversational", "Threaded", "MessageState", "Reactable", "Callable", "Draftable",
    # Media
    "FileObject", "ImageMedia", "AudioTrack", "VideoTrack", "Archive", "ContentSafety", "Transcribable",
    # Quantities
    "Measured", "Range", "Dimensions3D", "Area", "Angle", "Bitrate", "DataSize", "Temperature", "Length", "Weight", "Speed", "Percentage",
    # Money
    "Monetary", "Priced", "Discountable", "Subscribable", "Balanced", "Invoiced",
    # Catalog
    "Branded", "Inventory", "Bundle", "ColorMaterial", "ProductCompliance",
    # Tasks
    "Prioritized", "Progress", "Completable", "Blockable", "Dependencies", "Boarded", "Checklist", "WorkflowState", "Approvable", "Estimable",
    # Geo
    "Geolocated", "PostalAddress", "AdminRegion", "BoundingBox", "Geofence", "Routed", "Placed",
    # Net
    "NetAsset", "ApiEndpoint", "HostResource", "ComputeSpec", "Container", "ServiceHealth", "Certificated", "DataRecord", "ConfigSetting", "Backup",
    # Metric
    "Aggregated", "TimeSeriesPoint", "Trended", "Confident", "Threshold", "Dimensioned",
    # Events
    "Eventful", "Capacity", "RSVP", "Ticketed", "AdmissionPolicy", "AgendaSlot", "Cancellation", "CalendarFeed",
    # Rating
    "Rated", "Reviewed", "Sentiment", "Voted",
    # Security
    "AccessLeveled", "Permissioned", "Auditable", "Consented", "Compliant", "Attested", "Signed", "Retained", "Alertable", "Caseable", "RiskScored",
    # Device
    "DeviceIdentity", "DeviceState", "SensorReading", "ActuatorState", "Consumable", "ActivityMetrics", "BodyComposition", "VitalSign", "Biometric", "SleepRecord", "AIProvenance",
]
