"""Media & Files family — file objects, images, audio, video, archives, safety, transcription. Namespace media.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class FileObject(BaseModel):
    filename: str | None = _facet_field(role="media.filename")
    extension: str | None = _facet_field(role="media.extension")
    mime_type: str | None = _facet_field(role="media.mime_type")
    size_bytes: int | None = _facet_field(role="media.size_bytes")
    media_class: str | None = _facet_field(role="media.media_class")
    path: str | None = _facet_field(role="media.path")
    checksum_sha256: str | None = _facet_field(role="media.checksum_sha256")
    permissions: str | None = _facet_field(role="media.permissions")


class ImageMedia(BaseModel):
    width: int | None = _facet_field(role="media.width")
    height: int | None = _facet_field(role="media.height")
    color_space: str | None = _facet_field(role="media.color_space")
    exif: dict | None = _facet_field(role="media.exif")
    blurhash: str | None = _facet_field(role="media.blurhash")


class AudioTrack(BaseModel):
    audio_codec: str | None = _facet_field(role="media.audio_codec")
    bitrate_kbps: int | None = _facet_field(role="media.bitrate_kbps")
    sample_rate_hz: int | None = _facet_field(role="media.sample_rate_hz")
    channels: int | None = _facet_field(role="media.channels")
    bit_depth: int | None = _facet_field(role="media.bit_depth")
    loudness_lufs: float | None = _facet_field(role="media.loudness_lufs")


class VideoTrack(BaseModel):
    video_codec: str | None = _facet_field(role="media.video_codec")
    # Prefixed to avoid collision with task.Completable.resolution (role task.resolution)
    video_resolution: str | None = _facet_field(role="media.resolution")
    fps: float | None = _facet_field(role="media.fps")
    video_bitrate_kbps: int | None = _facet_field(role="media.video_bitrate_kbps")
    hdr: bool | None = _facet_field(role="media.hdr")


class Archive(BaseModel):
    archive_format: str | None = _facet_field(role="media.archive_format")
    entry_count: int | None = _facet_field(role="media.entry_count")
    uncompressed_size_bytes: int | None = _facet_field(role="media.uncompressed_size_bytes")
    compression_ratio: float | None = _facet_field(role="media.compression_ratio")
    is_encrypted: bool | None = _facet_field(role="media.is_encrypted")


class ContentSafety(BaseModel):
    scan_state: Literal["unscanned", "clean", "infected", "suspicious"] | None = _facet_field(role="media.scan_state")
    is_nsfw: bool | None = _facet_field(role="media.is_nsfw")
    moderation_labels: list[str] | None = _facet_field(role="media.moderation_labels")
    virus_name: str | None = _facet_field(role="media.virus_name")
    scanned_at: datetime | None = _facet_field(role="media.scanned_at")


class Transcribable(BaseModel):
    transcript: str | None = _facet_field(role="media.transcript")
    captions_url: str | None = _facet_field(role="media.captions_url")
    transcript_language: str | None = _facet_field(role="media.transcript_language")
