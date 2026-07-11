"""FastAPI application for the ParkSignals public REST API."""

from __future__ import annotations

import logging
import time
from typing import Annotated, List, Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .models import (
    ErrorResponse,
    ForecastInfo,
    OperationalStatus,
    ParkHoursHistory,
    ParkDetail,
    ParkSummary,
    RideEvent,
    RideDetail,
    RideSummary,
    WaitSample,
    WaitInfo,
)
from .services import ApiError, NotFoundError, ParkSignalsDataService, ValidationError


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("parksignals.api")

app = FastAPI(
    title="ParkSignals API",
    summary="Public REST API for ParkSignals park, ride, wait, status, and forecast data.",
    description=(
        "ParkSignals exposes the data already collected and cached by the monitor. "
        "The API does not scrape provider websites or call third-party providers in request handlers."
    ),
    version=settings.version,
    openapi_version="3.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    servers=[
        {"url": settings.public_api_base_url, "description": "ParkSignals API"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

data_service = ParkSignalsDataService()


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info("%s %s %s %.2fms", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


async def optional_api_key(x_api_key: Annotated[Optional[str], Header(include_in_schema=False)] = None):
    if not settings.api_key_required:
        return
    if not settings.api_key or x_api_key != settings.api_key:
        raise ValidationError("A valid X-API-Key header is required")


def service():
    return data_service


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, exc: Exception):
    logger.exception("Unhandled API error")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": "Unexpected API error"},
    )


@app.get("/api/health", tags=["System"])
async def health():
    return {"status": "ok", "version": settings.version}


@app.get(
    "/api/parks",
    response_model=List[ParkSummary],
    responses={500: {"model": ErrorResponse}},
    tags=["Parks"],
    dependencies=[Depends(optional_api_key)],
)
async def parks(data: ParkSignalsDataService = Depends(service)):
    return [data.park_summary(park) for park in data.parks()]


@app.get(
    "/api/parks/{park_id}",
    response_model=ParkDetail,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["Parks"],
    dependencies=[Depends(optional_api_key)],
)
async def park_detail(park_id: str, data: ParkSignalsDataService = Depends(service)):
    return data.park_detail(data.resolve_park(park_id))


@app.get(
    "/api/rides",
    response_model=List[RideSummary],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["Rides"],
    dependencies=[Depends(optional_api_key)],
)
async def rides(
    park: Annotated[Optional[str], Query(description="Optional park id or slug, such as magic-kingdom")] = None,
    data: ParkSignalsDataService = Depends(service),
):
    ride_records = data.rides_for_park(park) if park else data.all_rides()
    return [data.ride_summary(ride) for ride in ride_records]


@app.get(
    "/api/rides/{ride_id}",
    response_model=RideDetail,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["Rides"],
    dependencies=[Depends(optional_api_key)],
)
async def ride_detail(ride_id: str, data: ParkSignalsDataService = Depends(service)):
    return data.ride_detail(data.resolve_ride(ride_id))


@app.get(
    "/api/waits",
    response_model=List[WaitInfo],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["Waits"],
    dependencies=[Depends(optional_api_key)],
)
async def waits(
    park: Annotated[Optional[str], Query(description="Optional park id or slug, such as magic-kingdom")] = None,
    data: ParkSignalsDataService = Depends(service),
):
    return data.waits(park)


@app.get(
    "/api/forecast",
    response_model=List[ForecastInfo],
    responses={500: {"model": ErrorResponse}},
    tags=["Forecast"],
    dependencies=[Depends(optional_api_key)],
)
async def forecast(data: ParkSignalsDataService = Depends(service)):
    return data.forecast()


@app.get(
    "/api/status",
    response_model=OperationalStatus,
    responses={500: {"model": ErrorResponse}},
    tags=["Status"],
    dependencies=[Depends(optional_api_key)],
)
async def status(data: ParkSignalsDataService = Depends(service)):
    return data.operational_status()


@app.get(
    "/api/history/ride-events",
    response_model=List[RideEvent],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["History"],
    dependencies=[Depends(optional_api_key)],
)
async def ride_events(
    park: Annotated[Optional[str], Query(description="Optional park id or slug")] = None,
    ride: Annotated[Optional[str], Query(description="Optional ride id or slug")] = None,
    startDate: Annotated[Optional[str], Query(description="Inclusive YYYY-MM-DD start date")] = None,
    endDate: Annotated[Optional[str], Query(description="Inclusive YYYY-MM-DD end date")] = None,
    data: ParkSignalsDataService = Depends(service),
):
    return data.ride_events(park_id=park, ride_id=ride, start_date=startDate, end_date=endDate)


@app.get(
    "/api/history/wait-samples",
    response_model=List[WaitSample],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["History"],
    dependencies=[Depends(optional_api_key)],
)
async def wait_samples(
    park: Annotated[Optional[str], Query(description="Optional park id or slug")] = None,
    ride: Annotated[Optional[str], Query(description="Optional ride id or slug")] = None,
    startDate: Annotated[Optional[str], Query(description="Inclusive YYYY-MM-DD start date")] = None,
    endDate: Annotated[Optional[str], Query(description="Inclusive YYYY-MM-DD end date")] = None,
    data: ParkSignalsDataService = Depends(service),
):
    return data.wait_samples(park_id=park, ride_id=ride, start_date=startDate, end_date=endDate)


@app.get(
    "/api/history/park-hours",
    response_model=List[ParkHoursHistory],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["History"],
    dependencies=[Depends(optional_api_key)],
)
async def park_hours_history(
    park: Annotated[Optional[str], Query(description="Optional park id or slug")] = None,
    startDate: Annotated[Optional[str], Query(description="Inclusive YYYY-MM-DD start date")] = None,
    endDate: Annotated[Optional[str], Query(description="Inclusive YYYY-MM-DD end date")] = None,
    data: ParkSignalsDataService = Depends(service),
):
    return data.park_hours_history(park_id=park, start_date=startDate, end_date=endDate)


@app.get(
    "/api/history/daily-ride-metrics",
    responses={500: {"model": ErrorResponse}},
    tags=["History"],
    dependencies=[Depends(optional_api_key)],
)
async def daily_ride_metrics(data: ParkSignalsDataService = Depends(service)):
    return data.daily_ride_metrics()


# Alias used by some ASGI hosts.
application = app
