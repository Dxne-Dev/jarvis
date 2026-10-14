"""Formes JSON échangées avec l'interface."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StatusOut(Out):
    version: str
    dev_mode: bool
    started_at: datetime
    uptime_s: float
    keyring: str
    keyring_error: str | None
    secrets_configured: int
    secrets_total: int
    events_published: int
    events_dropped: int
    stream_clients: int
    timezone: str | None


class SecretStatusOut(Out):
    name: str
    label: str
    group: str
    help: str
    configured: bool
    source: str | None
    updated_at: datetime | None
    last_check_ok: bool | None
    last_check_at: datetime | None
    last_check_detail: str | None
    last_check_latency_ms: int | None


class SecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=4096)


class CheckOut(Out):
    name: str
    ok: bool
    detail: str
    latency_ms: int | None
    trace_id: str


class EventOut(Out):
    id: int | None
    type: str
    ts: datetime
    source: str
    correlation_id: str | None
    payload: dict[str, Any]


class TraceSummaryOut(Out):
    id: str
    name: str
    kind: str
    status: str
    started_at: datetime
    duration_ms: float | None
    correlation_id: str | None
    error: str | None
    span_count: int
    meta: dict[str, Any]


class SpanOut(Out):
    id: str
    parent_id: str | None
    name: str
    kind: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: float | None
    attributes: dict[str, Any]
    error: str | None


class TraceDetailOut(Out):
    id: str
    name: str
    kind: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: float | None
    correlation_id: str | None
    error: str | None
    meta: dict[str, Any]
    spans: list[SpanOut]


class PerfSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(max_length=32)
    duration_s: float = Field(gt=0, le=600)
    frames: int = Field(ge=0)
    fps_mean: float = Field(ge=0)
    frame_ms_p50: float = Field(ge=0)
    frame_ms_p95: float = Field(ge=0)
    frame_ms_p99: float = Field(ge=0)
    long_frames: int = Field(ge=0)


class PerfReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime: str = Field(max_length=64)
    user_agent: str = Field(max_length=400)
    device_pixel_ratio: float = Field(gt=0, le=8)
    canvas_px: int = Field(ge=0)
    refresh_hint_hz: float | None = Field(default=None, ge=0, le=500)
    samples: list[PerfSample] = Field(min_length=1, max_length=20)
    notes: str = Field(default="", max_length=500)


class PerfReportOut(Out):
    saved_as: str
    event_id: int | None
