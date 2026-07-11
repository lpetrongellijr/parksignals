"""Typed API response models."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class OperatingHours(BaseModel):
    source: Optional[str] = None
    timezone: Optional[str] = None
    opensAt: Optional[str] = None
    closesAt: Optional[str] = None


class ParkReference(BaseModel):
    id: str
    name: str


class ParkSummary(BaseModel):
    id: str
    name: str
    status: str
    operatingHours: Optional[OperatingHours] = None
    crowdScore: Optional[int] = Field(default=None, ge=0, le=100)
    lastUpdated: Optional[str] = None


class RideSummary(BaseModel):
    id: str
    name: str
    park: ParkReference
    currentWait: Optional[int] = None
    status: str
    lightningLaneAvailability: Optional[Any] = None
    virtualQueueStatus: Optional[Any] = None
    lastUpdated: Optional[str] = None


class RideDetail(RideSummary):
    parkSlug: str
    downtimeTodaySeconds: int
    currentDowntimeSeconds: int
    plannedClosure: bool
    history: List[Dict[str, Any]] = Field(default_factory=list)
    intradaySamples: List[Dict[str, Any]] = Field(default_factory=list)


class ParkDetail(ParkSummary):
    slug: str
    trackedRideCount: int
    openRideCount: int
    unavailableRideCount: int
    averageWaitMinutes: Optional[int] = None
    rides: List[RideSummary] = Field(default_factory=list)


class WaitInfo(BaseModel):
    rideId: str
    rideName: str
    park: ParkReference
    currentWait: Optional[int] = None
    status: str
    lastUpdated: Optional[str] = None


class ForecastInfo(BaseModel):
    park: ParkReference
    crowdPrediction: Literal["unknown", "light", "moderate", "heavy"]
    crowdScore: Optional[int] = Field(default=None, ge=0, le=100)
    recommendedArrivalTime: Optional[str] = None
    recommendedDepartureTime: Optional[str] = None
    confidenceScore: int = Field(ge=0, le=100)
    method: str
    lastUpdated: Optional[str] = None


class OperationalStatus(BaseModel):
    generatedAt: Optional[str] = None
    timezone: Optional[str] = None
    source: Optional[str] = None
    parks: List[ParkSummary] = Field(default_factory=list)
    activeClosures: int
    latestUpdates: List[Dict[str, Any]] = Field(default_factory=list)


class RideEvent(BaseModel):
    observed_at: str
    event_type: str
    ride_id: str
    ride_name: str
    park_id: str
    park_name: str
    park_slug: str


class WaitSample(BaseModel):
    observed_at: str
    ride_id: str
    ride_name: str
    park_id: str
    park_name: str
    park_slug: str
    wait_time_minutes: int
    status: Optional[str] = None


class ParkHoursHistory(BaseModel):
    date: str
    park_id: str
    park_name: Optional[str] = None
    park_slug: str
    timezone: str
    opens_at: Optional[str] = None
    closes_at: Optional[str] = None
    source: Optional[str] = None
    last_observed_at: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: str
