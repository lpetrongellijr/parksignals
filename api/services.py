"""Data access and normalization for the ParkSignals public API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
from typing import Any

from .config import settings


logger = logging.getLogger("parksignals.api")


class ApiError(Exception):
    status_code = 500
    error = "api_error"

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


class NotFoundError(ApiError):
    status_code = 404
    error = "not_found"


class ValidationError(ApiError):
    status_code = 400
    error = "validation_error"


@dataclass
class CachedJson:
    path: Path
    modified_at: float
    loaded_at: float
    data: dict[str, Any]


def slugify(value):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def data_age_minutes(timestamp):
    parsed = parse_timestamp(timestamp)
    if not parsed:
        return None
    return max(0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60)


def operating_hours(raw):
    if not isinstance(raw, dict):
        return None
    return {
        "source": raw.get("source"),
        "timezone": raw.get("timezone"),
        "opensAt": raw.get("opens_at") or raw.get("opensAt"),
        "closesAt": raw.get("closes_at") or raw.get("closesAt"),
    }


def crowd_score(average_wait_minutes):
    if not isinstance(average_wait_minutes, (int, float)):
        return None
    return max(0, min(100, round((average_wait_minutes / 75) * 100)))


def crowd_prediction(score):
    if score is None:
        return "unknown"
    if score < 35:
        return "light"
    if score < 70:
        return "moderate"
    return "heavy"


def confidence_score(last_updated):
    age = data_age_minutes(last_updated)
    if age is None:
        return 30
    if age <= 10:
        return 90
    if age <= 30:
        return 75
    if age <= 60:
        return 55
    return 35


def recommended_times(park, score):
    hours = operating_hours(park.get("hours")) or {}
    opens = hours.get("opensAt")
    closes = hours.get("closesAt")
    if not opens or not closes or score is None:
        return None, None
    if score >= 70:
        return opens, closes
    if score >= 35:
        return opens, None
    return None, closes


class ParkSignalsDataService:
    def __init__(self, data_dir=None, cache_ttl_seconds=None):
        self.data_dir = Path(data_dir or settings.data_dir)
        self.cache_ttl_seconds = settings.cache_ttl_seconds if cache_ttl_seconds is None else cache_ttl_seconds
        self._cache: dict[str, CachedJson] = {}

    def _load_json(self, name):
        path = self.data_dir / name
        if not path.exists():
            raise NotFoundError(f"Data file not found: {path}")
        modified_at = path.stat().st_mtime
        cached = self._cache.get(name)
        now = time.time()
        if (
            cached
            and cached.modified_at == modified_at
            and now - cached.loaded_at <= self.cache_ttl_seconds
        ):
            return cached.data
        try:
            with open(path, "r") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            logger.exception("Invalid JSON in %s", path)
            raise ApiError(f"Invalid data file: {path.name}") from exc
        self._cache[name] = CachedJson(path=path, modified_at=modified_at, loaded_at=now, data=data)
        return data

    def latest(self):
        return self._load_json("latest.json")

    def history(self):
        return self._load_json("history.json")

    def intraday(self):
        return self._load_json("intraday.json")

    def parks(self):
        return list(self.latest().get("parks", []))

    def all_rides(self):
        rides = []
        for park in self.parks():
            for ride in park.get("rides", []):
                ride_copy = dict(ride)
                ride_copy.setdefault("park_slug", park.get("slug"))
                ride_copy.setdefault("park_id", park.get("id"))
                ride_copy.setdefault("park_name", park.get("name"))
                rides.append(ride_copy)
        return rides

    def resolve_park(self, park_id):
        normalized = str(park_id or "").strip().lower()
        for park in self.parks():
            candidates = {
                str(park.get("id", "")).lower(),
                str(park.get("slug", "")).lower(),
                slugify(str(park.get("name", ""))),
            }
            if normalized in candidates:
                return park
        raise NotFoundError(f"Park not found: {park_id}")

    def resolve_ride(self, ride_id):
        normalized = str(ride_id or "").strip().lower()
        for ride in self.all_rides():
            candidates = {
                str(ride.get("id", "")).lower(),
                slugify(str(ride.get("name", ""))),
            }
            if normalized in candidates:
                return ride
        raise NotFoundError(f"Ride not found: {ride_id}")

    def park_summary(self, park):
        last_updated = self.latest().get("generated_at")
        score = crowd_score(park.get("average_wait_minutes"))
        return {
            "id": park.get("slug") or park.get("id"),
            "name": park.get("name"),
            "status": park.get("status", "unknown"),
            "operatingHours": operating_hours(park.get("hours")),
            "crowdScore": score,
            "lastUpdated": last_updated,
        }

    def park_detail(self, park):
        summary = self.park_summary(park)
        summary.update({
            "slug": park.get("slug") or park.get("id"),
            "trackedRideCount": int(park.get("tracked_ride_count") or 0),
            "openRideCount": int(park.get("open_ride_count") or 0),
            "unavailableRideCount": int(park.get("unavailable_ride_count") or 0),
            "averageWaitMinutes": park.get("average_wait_minutes"),
            "rides": [self.ride_summary(ride) for ride in park.get("rides", [])],
        })
        return summary

    def ride_summary(self, ride):
        return {
            "id": ride.get("id"),
            "name": ride.get("name"),
            "park": {
                "id": ride.get("park_slug") or ride.get("park_id"),
                "name": ride.get("park_name"),
            },
            "currentWait": ride.get("wait_time_minutes"),
            "status": ride.get("status", "unknown"),
            "lightningLaneAvailability": ride.get("lightning_lane_availability"),
            "virtualQueueStatus": ride.get("virtual_queue_status"),
            "lastUpdated": ride.get("last_seen_at") or self.latest().get("generated_at"),
        }

    def ride_detail(self, ride):
        summary = self.ride_summary(ride)
        summary.update({
            "parkSlug": ride.get("park_slug"),
            "downtimeTodaySeconds": int(ride.get("downtime_today_seconds") or 0),
            "currentDowntimeSeconds": int(ride.get("current_downtime_seconds") or 0),
            "plannedClosure": bool(ride.get("planned_closure")),
            "history": self.ride_history(ride.get("id")),
            "intradaySamples": self.ride_intraday(ride.get("id")),
        })
        return summary

    def ride_history(self, ride_id):
        records = []
        for day in self.history().get("days", []):
            for ride in day.get("rides", []):
                if str(ride.get("ride_id")) == str(ride_id):
                    records.append(dict(ride))
        return records

    def ride_intraday(self, ride_id):
        return [
            dict(sample)
            for sample in self.intraday().get("samples", [])
            if str(sample.get("ride_id")) == str(ride_id)
        ]

    def waits(self, park_id=None):
        rides = self.rides_for_park(park_id) if park_id else self.all_rides()
        return [
            {
                "rideId": ride.get("id"),
                "rideName": ride.get("name"),
                "park": {
                    "id": ride.get("park_slug") or ride.get("park_id"),
                    "name": ride.get("park_name"),
                },
                "currentWait": ride.get("wait_time_minutes"),
                "status": ride.get("status", "unknown"),
                "lastUpdated": ride.get("last_seen_at") or self.latest().get("generated_at"),
            }
            for ride in rides
        ]

    def rides_for_park(self, park_id):
        park = self.resolve_park(park_id)
        return list(park.get("rides", []))

    def forecast(self):
        last_updated = self.latest().get("generated_at")
        forecasts = []
        for park in self.parks():
            score = crowd_score(park.get("average_wait_minutes"))
            arrival, departure = recommended_times(park, score)
            forecasts.append({
                "park": {
                    "id": park.get("slug") or park.get("id"),
                    "name": park.get("name"),
                },
                "crowdPrediction": crowd_prediction(score),
                "crowdScore": score,
                "recommendedArrivalTime": arrival,
                "recommendedDepartureTime": departure,
                "confidenceScore": confidence_score(last_updated),
                "method": "derived_from_current_waits_and_park_hours",
                "lastUpdated": last_updated,
            })
        return forecasts

    def operational_status(self):
        latest = self.latest()
        return {
            "generatedAt": latest.get("generated_at"),
            "timezone": latest.get("timezone"),
            "source": latest.get("source"),
            "parks": [self.park_summary(park) for park in self.parks()],
            "activeClosures": len(latest.get("closures", [])),
            "latestUpdates": latest.get("latest_updates", []),
        }

