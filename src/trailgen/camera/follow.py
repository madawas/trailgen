from __future__ import annotations

import math
from dataclasses import dataclass

from .auto import (
    FreeCameraFrame,
    _intro_transition,
    _outro_transition,
    _ensure_visible_altitude,
    _meters_offset,
    _offset_latlon,
)
from trailgen.geo import RoutePoint, bearing_deg, interpolate_along_route
from trailgen.terrain import TerrainSampler


@dataclass(frozen=True)
class FollowCameraConfig:
    fps: int
    intro_frames: int
    outro_frames: int
    total_frames: int
    distance_m: float
    pitch_deg: float
    lookahead_m: float
    bearing_sensitivity: float
    panning_sensitivity: float
    smoothing_s: float
    min_clearance_m: float


def _alpha_from_smoothing(fps: int, smoothing_s: float, sensitivity: float) -> float:
    if smoothing_s <= 0:
        return 1.0
    dt = 1.0 / max(1, fps)
    base = 1.0 - math.exp(-dt / smoothing_s)
    return max(0.01, min(1.0, base * max(0.1, sensitivity)))


def _smooth_bearing(prev_deg: float, cur_deg: float, alpha: float) -> float:
    prev_rad = math.radians(prev_deg)
    cur_rad = math.radians(cur_deg)
    prev_x, prev_y = math.cos(prev_rad), math.sin(prev_rad)
    cur_x, cur_y = math.cos(cur_rad), math.sin(cur_rad)
    x = prev_x * (1.0 - alpha) + cur_x * alpha
    y = prev_y * (1.0 - alpha) + cur_y * alpha
    if x == 0 and y == 0:
        return cur_deg
    angle = math.degrees(math.atan2(y, x)) % 360.0
    return angle


def build_follow_camera_frames(
    route_points: list[RoutePoint],
    distances: list[float],
    total_distance: float,
    cfg: FollowCameraConfig,
    terrain: TerrainSampler,
) -> list[FreeCameraFrame]:
    main_frames = max(2, cfg.total_frames - cfg.intro_frames - cfg.outro_frames)
    targets: list[RoutePoint] = []
    bearings: list[float] = []
    progresses: list[float] = []

    for frame in range(main_frames):
        t = frame / (main_frames - 1) if main_frames > 1 else 0.0
        target_m = t * total_distance
        target = interpolate_along_route(route_points, distances, target_m)
        ahead_m = min(total_distance, target_m + max(5.0, cfg.lookahead_m))
        ahead = interpolate_along_route(route_points, distances, ahead_m)
        bearings.append(bearing_deg(target, ahead))
        targets.append(target)
        progresses.append(target_m / total_distance if total_distance > 0 else 0.0)

    alpha_target = _alpha_from_smoothing(
        cfg.fps, cfg.smoothing_s, cfg.panning_sensitivity
    )
    alpha_bearing = _alpha_from_smoothing(
        cfg.fps, cfg.smoothing_s, cfg.bearing_sensitivity
    )
    alpha_alt = _alpha_from_smoothing(cfg.fps, cfg.smoothing_s, 1.0)

    ref_lat = targets[0].lat
    ref_lon = targets[0].lon
    tar_e, tar_n = _meters_offset(ref_lat, ref_lon, targets[0].lat, targets[0].lon)
    smoothed_bearing = bearings[0]
    smoothed_alt = None

    frames: list[FreeCameraFrame] = []
    pitch_rad = math.radians(max(5.0, min(85.0, cfg.pitch_deg)))
    vertical_from_target = cfg.distance_m / math.tan(pitch_rad)

    for idx, target in enumerate(targets):
        cur_e, cur_n = _meters_offset(ref_lat, ref_lon, target.lat, target.lon)
        tar_e = tar_e * (1.0 - alpha_target) + cur_e * alpha_target
        tar_n = tar_n * (1.0 - alpha_target) + cur_n * alpha_target
        smoothed_bearing = _smooth_bearing(
            smoothed_bearing, bearings[idx], alpha_bearing
        )

        tar_lat, tar_lon = _offset_latlon(ref_lat, ref_lon, tar_e, tar_n)
        heading = math.radians(smoothed_bearing)
        east = math.sin(heading) * -cfg.distance_m
        north = math.cos(heading) * -cfg.distance_m
        cam_lat, cam_lon = _offset_latlon(tar_lat, tar_lon, east, north)

        target_alt = terrain.height_at(tar_lon, tar_lat) or target.ele
        cam_ground = terrain.height_at(cam_lon, cam_lat) or target.ele
        desired_alt = target_alt + vertical_from_target
        if desired_alt < cam_ground + cfg.min_clearance_m:
            desired_alt = cam_ground + cfg.min_clearance_m

        cam_alt, _ = _ensure_visible_altitude(
            terrain,
            cam_lat,
            cam_lon,
            cam_ground,
            desired_alt,
            RoutePoint(tar_lat, tar_lon, target_alt),
            target_alt,
            max_raise_m=900.0,
            step_m=60.0,
        )

        if smoothed_alt is None:
            smoothed_alt = cam_alt
        else:
            smoothed_alt = smoothed_alt * (1.0 - alpha_alt) + cam_alt * alpha_alt

        frames.append(
            FreeCameraFrame(
                position=[cam_lon, cam_lat],
                altitude=smoothed_alt,
                target=[tar_lon, tar_lat],
                progress=progresses[idx],
            )
        )

    intro = _intro_transition(frames, cfg.intro_frames)
    outro = _outro_transition(frames, cfg.outro_frames, route_points)
    return intro + frames + outro
