from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import gpxpy


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    ele: float | None
    time: datetime | None


def _iter_points(gpx: gpxpy.gpx.GPX) -> Iterable[GeoPoint]:
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                yield GeoPoint(
                    point.latitude, point.longitude, point.elevation, point.time
                )

    for route in gpx.routes:
        for point in route.points:
            yield GeoPoint(point.latitude, point.longitude, point.elevation, point.time)


def load_gpx(path: Path) -> list[GeoPoint]:
    with path.open("r", encoding="utf-8") as handle:
        gpx = gpxpy.parse(handle)

    points = list(_iter_points(gpx))
    if not points:
        raise ValueError(f"No points found in GPX: {path}")
    return points
