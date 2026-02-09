from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from trailgen.geo import (
    EARTH_RADIUS_M,
    RoutePoint,
    bearing_deg,
    haversine_m,
    interpolate_along_route,
)
from trailgen.terrain import TerrainSampler


@dataclass(frozen=True)
class FreeCameraFrame:
    position: list[float]
    altitude: float
    target: list[float]
    progress: float
    free: bool = True


@dataclass(frozen=True)
class AutoCameraConfig:
    fps: int
    intro_frames: int
    outro_frames: int
    total_frames: int
    lookahead_m: float
    side_offset_m: float
    back_offset_m: float
    base_clearance_m: float
    relief_factor: float
    summit_boost_m: float
    relief_window_m: float
    summit_sigma_m: float


@dataclass(frozen=True)
class AutoCandidate:
    side_offset_m: float
    back_offset_m: float
    base_clearance_m: float


@dataclass(frozen=True)
class _RouteSample:
    distance_m: float
    point: RoutePoint
    bearing: float
    progress: float


def _offset_latlon(
    lat: float, lon: float, east_m: float, north_m: float
) -> tuple[float, float]:
    dlat = (north_m / EARTH_RADIUS_M) * (180.0 / math.pi)
    dlon = (east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))) * (180.0 / math.pi)
    return lat + dlat, lon + dlon


def _meters_offset(
    from_lat: float, from_lon: float, to_lat: float, to_lon: float
) -> tuple[float, float]:
    dlat = math.radians(to_lat - from_lat)
    dlon = math.radians(to_lon - from_lon)
    north = dlat * EARTH_RADIUS_M
    east = dlon * EARTH_RADIUS_M * math.cos(math.radians(from_lat))
    return east, north


def _weighted_distances(
    distances: list[float],
    summit_distance: float,
    summit_sigma_m: float,
    summit_bonus: float,
) -> list[float]:
    weighted = [0.0]
    for idx in range(1, len(distances)):
        mid = 0.5 * (distances[idx - 1] + distances[idx])
        weight = 1.0 + summit_bonus * math.exp(
            -((mid - summit_distance) ** 2) / (2 * summit_sigma_m**2)
        )
        segment = distances[idx] - distances[idx - 1]
        weighted.append(weighted[-1] + segment * weight)
    return weighted


def _distance_for_time(
    distances: list[float], weighted: list[float], t: float
) -> float:
    if t <= 0:
        return distances[0]
    if t >= 1:
        return distances[-1]
    target = t * weighted[-1]
    idx = bisect.bisect_left(weighted, target)
    if idx <= 0:
        return distances[0]
    if idx >= len(weighted):
        return distances[-1]
    w0 = weighted[idx - 1]
    w1 = weighted[idx]
    if w1 == w0:
        return distances[idx]
    ratio = (target - w0) / (w1 - w0)
    return distances[idx - 1] + ratio * (distances[idx] - distances[idx - 1])


def _compute_relief(
    distances: list[float], elevations: list[float], window_m: float
) -> list[float]:
    relief = [0.0] * len(distances)
    start = 0
    end = 0
    for idx in range(len(distances)):
        center = distances[idx]
        while start < len(distances) and distances[start] < center - window_m / 2:
            start += 1
        while end < len(distances) and distances[end] <= center + window_m / 2:
            end += 1
        window = elevations[start:end]
        if window:
            relief[idx] = max(window) - min(window)
    return relief


def _interpolate_scalar(
    distances: list[float], values: list[float], target: float
) -> float:
    if target <= distances[0]:
        return values[0]
    if target >= distances[-1]:
        return values[-1]
    idx = bisect.bisect_left(distances, target)
    prev_d = distances[idx - 1]
    next_d = distances[idx]
    if next_d == prev_d:
        return values[idx]
    ratio = (target - prev_d) / (next_d - prev_d)
    return values[idx - 1] + ratio * (values[idx] - values[idx - 1])


def _line_of_sight_visible(
    terrain: TerrainSampler,
    camera: RoutePoint,
    camera_alt: float,
    target: RoutePoint,
    target_alt: float,
    step_m: float = 40.0,
    margin_m: float = 2.0,
) -> bool:
    distance = haversine_m(camera, target)
    steps = max(1, int(distance / step_m))
    for idx in range(1, steps):
        t = idx / steps
        lat = camera.lat + (target.lat - camera.lat) * t
        lon = camera.lon + (target.lon - camera.lon) * t
        ray_alt = camera_alt + (target_alt - camera_alt) * t
        terrain_alt = terrain.height_at(lon, lat)
        if terrain_alt is None:
            continue
        if terrain_alt + margin_m > ray_alt:
            return False
    return True


def _build_samples(
    route_points: list[RoutePoint],
    distances: list[float],
    total_distance: float,
    frames: int,
    lookahead_m: float,
    summit_distance: float,
    summit_sigma_m: float,
    summit_bonus: float,
) -> list[_RouteSample]:
    weighted = _weighted_distances(
        distances, summit_distance, summit_sigma_m, summit_bonus
    )
    samples: list[_RouteSample] = []
    for frame in range(frames):
        t = frame / (frames - 1) if frames > 1 else 0.0
        target_m = _distance_for_time(distances, weighted, t)
        next_target = min(total_distance, target_m + lookahead_m)
        curr = interpolate_along_route(route_points, distances, target_m)
        nxt = interpolate_along_route(route_points, distances, next_target)
        bearing = bearing_deg(curr, nxt)
        samples.append(
            _RouteSample(
                distance_m=target_m,
                point=curr,
                bearing=bearing,
                progress=target_m / total_distance,
            )
        )
    return samples


def _build_camera_frames(
    route_points: list[RoutePoint],
    samples: list[_RouteSample],
    distances: list[float],
    relief: list[float],
    total_distance: float,
    candidate: AutoCandidate,
    lookahead_m: float,
    terrain: TerrainSampler,
    summit_distance: float,
    summit_sigma_m: float,
    summit_boost_m: float,
    relief_factor: float,
) -> list[FreeCameraFrame]:
    frames: list[FreeCameraFrame] = []
    min_altitudes: list[float] = []
    turn_weights: list[float] = []
    summit_idx = _summit_frame_index(samples, summit_distance)
    summit_point = interpolate_along_route(route_points, distances, summit_distance)
    summit_alt = (
        terrain.height_at(summit_point.lon, summit_point.lat) or summit_point.ele
    )
    for idx, sample in enumerate(samples):
        heading_rad = math.radians(sample.bearing)
        heading_east = math.sin(heading_rad)
        heading_north = math.cos(heading_rad)
        side_east = -heading_north
        side_north = heading_east
        relief_here = _interpolate_scalar(distances, relief, sample.distance_m)
        turn_weight = 0.0
        if 0 < idx < len(samples) - 1:
            prev_bearing = samples[idx - 1].bearing
            next_bearing = samples[idx + 1].bearing
            delta = abs(((next_bearing - prev_bearing + 180) % 360) - 180)
            turn_weight = min(1.0, delta / 60.0)
        relief_scale = 1.0 - min(0.45, relief_here / 1800.0)
        summit_weight = math.exp(
            -((sample.distance_m - summit_distance) ** 2) / (2 * summit_sigma_m**2)
        )
        summit_scale = 1.0 - 0.4 * summit_weight
        side_offset = candidate.side_offset_m * relief_scale * summit_scale
        back_offset = candidate.back_offset_m * (1.0 - 0.25 * summit_weight)

        east_m = side_east * side_offset + heading_east * (-back_offset)
        north_m = side_north * side_offset + heading_north * (-back_offset)
        cam_lat, cam_lon = _offset_latlon(
            sample.point.lat, sample.point.lon, east_m, north_m
        )
        cam_ground = terrain.height_at(cam_lon, cam_lat)
        if cam_ground is None:
            cam_ground = sample.point.ele
        clearance = (
            candidate.base_clearance_m
            + relief_here * relief_factor
            + summit_boost_m * summit_weight
        )
        cam_alt = cam_ground + clearance

        dynamic_lookahead = lookahead_m * (
            1.0 - 0.8 * summit_weight + 0.8 * turn_weight
        )
        target_m = min(total_distance, sample.distance_m + dynamic_lookahead)
        target = interpolate_along_route(route_points, distances, target_m)
        target_alt = terrain.height_at(target.lon, target.lat) or target.ele

        cam_alt, _ = _ensure_visible_altitude(
            terrain,
            cam_lat,
            cam_lon,
            cam_ground,
            cam_alt,
            target,
            target_alt,
            max_raise_m=900.0,
            step_m=80.0,
        )
        if idx == summit_idx:
            cam_alt, _ = _ensure_visible_altitude(
                terrain,
                cam_lat,
                cam_lon,
                cam_ground,
                cam_alt,
                summit_point,
                summit_alt,
                max_raise_m=1600.0,
                step_m=100.0,
            )
        if turn_weight > 0:
            cam_alt += 80.0 * turn_weight
        frames.append(
            FreeCameraFrame(
                position=[cam_lon, cam_lat],
                altitude=cam_alt,
                target=[target.lon, target.lat],
                progress=sample.progress,
            )
        )
        min_altitudes.append(cam_alt)
        turn_weights.append(turn_weight)
    return _smooth_camera_frames(frames, min_altitudes, turn_weights)


def _smooth_camera_frames(
    frames: list[FreeCameraFrame],
    min_altitudes: list[float],
    turn_weights: list[float],
) -> list[FreeCameraFrame]:
    if not frames:
        return frames
    base_pos_alpha = 0.18
    base_target_alpha = 0.14
    base_alt_alpha = 0.12
    ref_lat = frames[0].position[1]
    ref_lon = frames[0].position[0]
    pos_e, pos_n = 0.0, 0.0
    tar_e, tar_n = _meters_offset(
        ref_lat, ref_lon, frames[0].target[1], frames[0].target[0]
    )
    alt = frames[0].altitude
    smoothed: list[FreeCameraFrame] = []
    for idx, frame in enumerate(frames):
        turn_weight = turn_weights[idx] if idx < len(turn_weights) else 0.0
        pos_alpha = max(0.05, base_pos_alpha * (1.0 - 0.6 * turn_weight))
        target_alpha = max(0.04, base_target_alpha * (1.0 - 0.6 * turn_weight))
        alt_alpha = max(0.05, base_alt_alpha * (1.0 - 0.4 * turn_weight))

        cur_e, cur_n = _meters_offset(
            ref_lat, ref_lon, frame.position[1], frame.position[0]
        )
        pos_e = pos_e * (1 - pos_alpha) + cur_e * pos_alpha
        pos_n = pos_n * (1 - pos_alpha) + cur_n * pos_alpha

        cur_te, cur_tn = _meters_offset(
            ref_lat, ref_lon, frame.target[1], frame.target[0]
        )
        tar_e = tar_e * (1 - target_alpha) + cur_te * target_alpha
        tar_n = tar_n * (1 - target_alpha) + cur_tn * target_alpha

        alt = alt * (1 - alt_alpha) + frame.altitude * alt_alpha
        if idx < len(min_altitudes) and alt < min_altitudes[idx]:
            alt = min_altitudes[idx]

        pos_lat, pos_lon = _offset_latlon(ref_lat, ref_lon, pos_e, pos_n)
        tar_lat, tar_lon = _offset_latlon(ref_lat, ref_lon, tar_e, tar_n)
        smoothed.append(
            FreeCameraFrame(
                position=[pos_lon, pos_lat],
                altitude=alt,
                target=[tar_lon, tar_lat],
                progress=frame.progress,
            )
        )
    return smoothed


def _ensure_visible_altitude(
    terrain: TerrainSampler,
    cam_lat: float,
    cam_lon: float,
    cam_ground: float,
    cam_alt: float,
    target: RoutePoint,
    target_alt: float,
    max_raise_m: float,
    step_m: float,
) -> tuple[float, bool]:
    camera_point = RoutePoint(cam_lat, cam_lon, cam_ground)
    if _line_of_sight_visible(terrain, camera_point, cam_alt, target, target_alt):
        return cam_alt, True
    remaining = max(0.0, max_raise_m)
    while remaining > 0:
        cam_alt += step_m
        if _line_of_sight_visible(terrain, camera_point, cam_alt, target, target_alt):
            return cam_alt, True
        remaining -= step_m
    return cam_alt, False


def _summit_frame_index(samples: list[_RouteSample], summit_distance: float) -> int:
    best_idx = 0
    best_delta = float("inf")
    for idx, sample in enumerate(samples):
        delta = abs(sample.distance_m - summit_distance)
        if delta < best_delta:
            best_delta = delta
            best_idx = idx
    return best_idx


def _pick_best_candidate(
    route_points: list[RoutePoint],
    candidates: list[AutoCandidate],
    samples: list[_RouteSample],
    distances: list[float],
    total_distance: float,
    relief: list[float],
    lookahead_m: float,
    terrain: TerrainSampler,
    summit_distance: float,
    summit_sigma_m: float,
    summit_boost_m: float,
    relief_factor: float,
) -> AutoCandidate:
    summit_idx = _summit_frame_index(samples, summit_distance)
    best_score = -1.0
    best = candidates[0]
    for candidate in candidates:
        visible = 0
        tested = 0
        avg_distance = 0.0
        for idx in range(0, len(samples), max(1, len(samples) // 30)):
            sample = samples[idx]
            cam_lat, cam_lon = _camera_position(sample, candidate)
            cam_ground = terrain.height_at(cam_lon, cam_lat) or sample.point.ele
            relief_here = _interpolate_scalar(distances, relief, sample.distance_m)
            summit_weight = math.exp(
                -((sample.distance_m - summit_distance) ** 2) / (2 * summit_sigma_m**2)
            )
            clearance = (
                candidate.base_clearance_m
                + relief_here * relief_factor
                + summit_boost_m * summit_weight
            )
            cam_alt = cam_ground + clearance
            summit_weight = math.exp(
                -((sample.distance_m - summit_distance) ** 2) / (2 * summit_sigma_m**2)
            )
            dynamic_lookahead = lookahead_m * (1.0 - 0.8 * summit_weight)
            target_m = min(total_distance, sample.distance_m + dynamic_lookahead)
            target = interpolate_along_route(route_points, distances, target_m)
            target_alt = terrain.height_at(target.lon, target.lat) or target.ele
            tested += 1
            if _line_of_sight_visible(
                terrain,
                RoutePoint(cam_lat, cam_lon, cam_ground),
                cam_alt,
                target,
                target_alt,
            ):
                visible += 1
            avg_distance += haversine_m(
                RoutePoint(cam_lat, cam_lon, 0.0),
                RoutePoint(target.lat, target.lon, 0.0),
            )

        visibility = visible / max(1, tested)
        avg_distance = avg_distance / max(1, tested)
        desired = 650.0
        distance_score = 1.0 - min(1.0, abs(avg_distance - desired) / desired)

        summit_sample = samples[summit_idx]
        summit_visible = _is_summit_visible(
            terrain,
            summit_sample,
            candidate,
            route_points,
            distances,
            relief,
            summit_distance,
            summit_sigma_m,
            summit_boost_m,
            relief_factor,
        )
        score = (
            0.7 * visibility
            + 0.2 * distance_score
            + 0.1 * (1.0 if summit_visible else 0.0)
        )
        if summit_visible:
            score += 0.2
        if score > best_score:
            best_score = score
            best = candidate
    return best


def _camera_position(
    sample: _RouteSample, candidate: AutoCandidate
) -> tuple[float, float]:
    heading_rad = math.radians(sample.bearing)
    heading_east = math.sin(heading_rad)
    heading_north = math.cos(heading_rad)
    side_east = -heading_north
    side_north = heading_east
    east_m = side_east * candidate.side_offset_m + heading_east * (
        -candidate.back_offset_m
    )
    north_m = side_north * candidate.side_offset_m + heading_north * (
        -candidate.back_offset_m
    )
    cam_lat, cam_lon = _offset_latlon(
        sample.point.lat, sample.point.lon, east_m, north_m
    )
    return cam_lat, cam_lon


def _is_summit_visible(
    terrain: TerrainSampler,
    sample: _RouteSample,
    candidate: AutoCandidate,
    route_points: list[RoutePoint],
    distances: list[float],
    relief: list[float],
    summit_distance: float,
    summit_sigma_m: float,
    summit_boost_m: float,
    relief_factor: float,
) -> bool:
    cam_lat, cam_lon = _camera_position(sample, candidate)
    cam_ground = terrain.height_at(cam_lon, cam_lat) or sample.point.ele
    relief_here = _interpolate_scalar(distances, relief, sample.distance_m)
    summit_weight = math.exp(
        -((sample.distance_m - summit_distance) ** 2) / (2 * summit_sigma_m**2)
    )
    clearance = (
        candidate.base_clearance_m
        + relief_here * relief_factor
        + summit_boost_m * summit_weight
    )
    cam_alt = cam_ground + clearance
    summit_point = interpolate_along_route(route_points, distances, summit_distance)
    summit_alt = (
        terrain.height_at(summit_point.lon, summit_point.lat) or summit_point.ele
    )
    return _line_of_sight_visible(
        terrain,
        RoutePoint(cam_lat, cam_lon, cam_ground),
        cam_alt,
        summit_point,
        summit_alt,
    )


def build_auto_camera_frames(
    route_points: list[RoutePoint],
    distances: list[float],
    total_distance: float,
    cfg: AutoCameraConfig,
    terrain: TerrainSampler,
    summit_distance: float,
    elevations: list[float],
) -> list[FreeCameraFrame]:
    main_frames = max(2, cfg.total_frames - cfg.intro_frames - cfg.outro_frames)
    samples = _build_samples(
        route_points,
        distances,
        total_distance,
        main_frames,
        cfg.lookahead_m,
        summit_distance,
        cfg.summit_sigma_m,
        summit_bonus=2.0,
    )
    relief = _compute_relief(distances, elevations, cfg.relief_window_m)

    candidates = [
        AutoCandidate(
            side_offset_m=cfg.side_offset_m,
            back_offset_m=cfg.back_offset_m,
            base_clearance_m=cfg.base_clearance_m,
        ),
        AutoCandidate(
            side_offset_m=-cfg.side_offset_m,
            back_offset_m=cfg.back_offset_m,
            base_clearance_m=cfg.base_clearance_m,
        ),
        AutoCandidate(
            side_offset_m=cfg.side_offset_m,
            back_offset_m=cfg.back_offset_m * 0.5,
            base_clearance_m=cfg.base_clearance_m + 80.0,
        ),
        AutoCandidate(
            side_offset_m=-cfg.side_offset_m,
            back_offset_m=cfg.back_offset_m * 0.5,
            base_clearance_m=cfg.base_clearance_m + 80.0,
        ),
    ]

    best = _pick_best_candidate(
        route_points,
        candidates,
        samples,
        distances,
        total_distance,
        relief,
        cfg.lookahead_m,
        terrain,
        summit_distance,
        cfg.summit_sigma_m,
        cfg.summit_boost_m,
        cfg.relief_factor,
    )

    # Ensure summit visibility by increasing boost if needed.
    summit_boost = cfg.summit_boost_m
    for _ in range(3):
        summit_idx = _summit_frame_index(samples, summit_distance)
        if _is_summit_visible(
            terrain,
            samples[summit_idx],
            best,
            route_points,
            distances,
            relief,
            summit_distance,
            cfg.summit_sigma_m,
            summit_boost,
            cfg.relief_factor,
        ):
            break
        summit_boost *= 1.4

    frames = _build_camera_frames(
        route_points,
        samples,
        distances,
        relief,
        total_distance,
        best,
        cfg.lookahead_m,
        terrain,
        summit_distance,
        cfg.summit_sigma_m,
        summit_boost,
        cfg.relief_factor,
    )

    intro = _intro_transition(frames, cfg.intro_frames)
    outro = _outro_transition(frames, cfg.outro_frames, route_points)
    return intro + frames + outro


def _intro_transition(
    frames: list[FreeCameraFrame], count: int
) -> list[FreeCameraFrame]:
    if count <= 0 or not frames:
        return []
    first = frames[0]
    zoom_scale = 2**2
    start_alt = max(first.altitude * zoom_scale, first.altitude + 900.0)
    start_target = first.target
    target_lon, target_lat = start_target[0], start_target[1]
    base_east, base_north = _meters_offset(
        target_lat, target_lon, first.position[1], first.position[0]
    )
    base_radius = math.hypot(base_east, base_north)
    if base_radius < 50:
        base_radius = 400.0
        base_east, base_north = 0.0, base_radius
    base_angle = math.atan2(base_east, base_north)
    orbit_rad = math.radians(90.0)
    start_angle = base_angle + orbit_rad
    start_radius = max(base_radius * zoom_scale, base_radius + 1400.0)
    intro: list[FreeCameraFrame] = []
    for idx in range(count):
        t = (idx + 1) / count
        ease = t * t * (3 - 2 * t)
        zoom_phase = min(1.0, ease / 0.6)
        orbit_phase = 0.0 if ease < 0.2 else min(1.0, (ease - 0.2) / 0.8)
        angle = start_angle + (base_angle - start_angle) * orbit_phase
        radius = start_radius + (base_radius - start_radius) * zoom_phase
        east = radius * math.sin(angle)
        north = radius * math.cos(angle)
        lat, lon = _offset_latlon(target_lat, target_lon, east, north)
        intro.append(
            FreeCameraFrame(
                position=[lon, lat],
                altitude=start_alt + (first.altitude - start_alt) * zoom_phase,
                target=start_target,
                progress=0.0,
            )
        )
    return intro


def _outro_transition(
    frames: list[FreeCameraFrame], count: int, route_points: list[RoutePoint]
) -> list[FreeCameraFrame]:
    if count <= 0 or not frames:
        return []
    last = frames[-1]
    zoom_scale = 2**2
    lats = [p.lat for p in route_points]
    lons = [p.lon for p in route_points]
    center_lat = (min(lats) + max(lats)) / 2
    center_lon = (min(lons) + max(lons)) / 2
    max_dist = max(
        haversine_m(RoutePoint(center_lat, center_lon, 0.0), p) for p in route_points
    )
    end_radius = max(700.0, max_dist * 1.7)
    end_alt = max(last.altitude * 1.6, max_dist * 2.2)
    base_east, base_north = _meters_offset(
        center_lat, center_lon, last.position[1], last.position[0]
    )
    base_radius = math.hypot(base_east, base_north)
    if base_radius < 50:
        base_radius = end_radius * 0.6
        base_east, base_north = 0.0, base_radius
    base_angle = math.atan2(base_east, base_north)
    orbit_rad = math.radians(100.0)
    end_angle = base_angle + orbit_rad
    end_radius = max(end_radius, base_radius * zoom_scale, base_radius + 1400.0)
    end_alt = max(end_alt, last.altitude * zoom_scale, last.altitude + 900.0)
    outro: list[FreeCameraFrame] = []
    for idx in range(count):
        t = (idx + 1) / count
        ease = t * t * (3 - 2 * t)
        zoom_phase = min(1.0, ease / 0.7)
        orbit_phase = min(1.0, ease / 0.85)
        angle = base_angle + (end_angle - base_angle) * orbit_phase
        radius = base_radius + (end_radius - base_radius) * zoom_phase
        east = radius * math.sin(angle)
        north = radius * math.cos(angle)
        lat, lon = _offset_latlon(center_lat, center_lon, east, north)
        outro.append(
            FreeCameraFrame(
                position=[lon, lat],
                altitude=last.altitude + (end_alt - last.altitude) * zoom_phase,
                target=[
                    last.target[0] + (center_lon - last.target[0]) * ease,
                    last.target[1] + (center_lat - last.target[1]) * ease,
                ],
                progress=1.0,
            )
        )
    return outro
