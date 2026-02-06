from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from trailgen.gpx import GeoPoint


EARTH_RADIUS_M = 6371000.0


@dataclass(frozen=True)
class RoutePoint:
    lat: float
    lon: float
    ele: float


def haversine_m(a: RoutePoint, b: RoutePoint) -> float:
    """
    Calculates the great-circle distance in meters between two RoutePoints using the Haversine formula.
    Args:
        a: The first RoutePoint.
        b: The second RoutePoint.
    Returns:
        Distance in meters between a and b.
    """
    lat1 = math.radians(a.lat)
    lon1 = math.radians(a.lon)
    lat2 = math.radians(b.lat)
    lon2 = math.radians(b.lon)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: RoutePoint, b: RoutePoint) -> float:
    """
    Computes the compass bearing in degrees from RoutePoint a to RoutePoint b.
    Args:
        a: The starting RoutePoint.
        b: The destination RoutePoint.
    Returns:
        Bearing in degrees (0-360) from a to b.
    """
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlon = math.radians(b.lon - a.lon)

    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def to_route_points(points: Iterable[GeoPoint]) -> list[RoutePoint]:
    """
    Converts an iterable of GeoPoint objects to a list of RoutePoint objects.
    Elevation is set to 0.0 if missing.
    Args:
        points: Iterable of GeoPoint objects.
    Returns:
        List of RoutePoint objects.
    """
    route = []
    for point in points:
        ele = 0.0 if point.ele is None else float(point.ele)
        route.append(RoutePoint(point.lat, point.lon, ele))
    return route


def cumulative_distances(points: list[RoutePoint]) -> list[float]:
    """
    Computes cumulative distances (in meters) along a list of RoutePoints.
    Args:
        points: List of RoutePoint objects.
    Returns:
        List of cumulative distances, starting with 0.0.
    """
    distances = [0.0]
    for idx in range(1, len(points)):
        distances.append(distances[-1] + haversine_m(points[idx - 1], points[idx]))
    return distances


def resample_by_distance(points: list[RoutePoint], step_m: float) -> list[RoutePoint]:
    """
    Resamples the route so that points are spaced approximately every step_m meters apart.
    Uses linear interpolation between points to create new points at the desired intervals.
    Args:
        points: List of RoutePoint objects.
        step_m: Desired spacing in meters between points.
    Returns:
        List of resampled RoutePoint objects.
    """
    if len(points) < 2:
        return points

    distances = cumulative_distances(points)
    total = distances[-1]
    if total == 0:
        return points

    result = [points[0]]
    target = step_m
    idx = 1

    while target < total and idx < len(points):
        while idx < len(points) and distances[idx] < target:
            idx += 1
        if idx >= len(points):
            break

        prev = points[idx - 1]
        curr = points[idx]
        span = distances[idx] - distances[idx - 1]
        if span == 0:
            ratio = 0.0
        else:
            ratio = (target - distances[idx - 1]) / span

        lat = prev.lat + ratio * (curr.lat - prev.lat)
        lon = prev.lon + ratio * (curr.lon - prev.lon)
        ele = prev.ele + ratio * (curr.ele - prev.ele)
        result.append(RoutePoint(lat, lon, ele))
        target += step_m

    result.append(points[-1])
    return result


def chaikin_smooth(points: list[RoutePoint], iterations: int = 2) -> list[RoutePoint]:
    """
    Smooths the route using Chaikin’s corner-cutting algorithm.
    Each iteration adds new points to smooth out sharp corners.
    Args:
        points: List of RoutePoint objects.
        iterations: Number of smoothing iterations to apply.
    Returns:
        Smoothed list of RoutePoint objects.
    """
    if len(points) < 3:
        return points

    current = points
    for _ in range(iterations):
        next_points: list[RoutePoint] = [current[0]]
        for idx in range(len(current) - 1):
            p0 = current[idx]
            p1 = current[idx + 1]
            q = RoutePoint(
                lat=0.75 * p0.lat + 0.25 * p1.lat,
                lon=0.75 * p0.lon + 0.25 * p1.lon,
                ele=0.75 * p0.ele + 0.25 * p1.ele,
            )
            r = RoutePoint(
                lat=0.25 * p0.lat + 0.75 * p1.lat,
                lon=0.25 * p0.lon + 0.75 * p1.lon,
                ele=0.25 * p0.ele + 0.75 * p1.ele,
            )
            next_points.extend([q, r])
        next_points.append(current[-1])
        current = next_points

    return current


def interpolate_along_route(points: list[RoutePoint], distances: list[float], target_m: float) -> RoutePoint:
    """
    Finds the position along the route at a specific cumulative distance using linear interpolation.
    Args:
        points: List of RoutePoint objects.
        distances: List of cumulative distances corresponding to points.
        target_m: Target distance along the route in meters.
    Returns:
        Interpolated RoutePoint at the specified distance.
    """
    if target_m <= 0:
        return points[0]
    if target_m >= distances[-1]:
        return points[-1]

    idx = 1
    while idx < len(distances) and distances[idx] < target_m:
        idx += 1

    prev = points[idx - 1]
    curr = points[idx]
    span = distances[idx] - distances[idx - 1]
    if span == 0:
        ratio = 0.0
    else:
        ratio = (target_m - distances[idx - 1]) / span

    lat = prev.lat + ratio * (curr.lat - prev.lat)
    lon = prev.lon + ratio * (curr.lon - prev.lon)
    ele = prev.ele + ratio * (curr.ele - prev.ele)
    return RoutePoint(lat, lon, ele)
