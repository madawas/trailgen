from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

from trailgen.config import MapConfig, map_config
from trailgen.ffmpeg import FFmpegError, encode_video
from trailgen.geo import (
    bearing_deg,
    chaikin_smooth,
    cumulative_distances,
    interpolate_along_route,
    resample_by_distance,
    to_route_points,
)
from trailgen.gpx import load_gpx
from trailgen.server import RendererServer


@dataclass(frozen=True)
class RenderOptions:
    gpx_path: Path
    out_path: Path
    fps: int
    width: int
    height: int
    duration: float | None
    speed_kmh: float
    map_provider: str
    zoom: float
    pitch: float
    bearing_offset: float
    intro_seconds: float
    outro_seconds: float
    orbit_degrees: float
    zoom_out: float
    pitch_drop: float
    lookahead_m: float
    smooth_factor: float
    no_terrain: bool
    frames_dir: Path | None
    keep_frames: bool
    crf: int
    preset: str


@dataclass(frozen=True)
class FrameCamera:
    center: list[float]
    bearing: float
    pitch: float
    zoom: float
    progress: float


def _build_route_geojson(route: list[tuple[float, float]]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": route},
                "properties": {},
            }
        ],
    }


def _build_marker_geojson(route: list[tuple[float, float]]) -> dict:
    if not route:
        return {"type": "FeatureCollection", "features": []}
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": route[0]},
                "properties": {"label": "start", "color": "#16a34a"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": route[-1]},
                "properties": {"label": "end", "color": "#ef4444"},
            },
        ],
    }


def _ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


def _follow_route_frames(
    route_points,
    distances,
    total_distance,
    frames,
    pitch,
    zoom,
    bearing_offset,
    lookahead_m,
):
    cameras: list[FrameCamera] = []
    for frame in range(frames):
        t = frame / (frames - 1) if frames > 1 else 0.0
        target_m = t * total_distance
        next_target = min(total_distance, target_m + lookahead_m)

        curr = interpolate_along_route(route_points, distances, target_m)
        nxt = interpolate_along_route(route_points, distances, next_target)

        bearing = bearing_deg(curr, nxt) + bearing_offset
        cameras.append(
            FrameCamera(
                center=[curr.lon, curr.lat],
                bearing=bearing % 360.0,
                pitch=pitch,
                zoom=zoom,
                progress=target_m / total_distance,
            )
        )
    return cameras


def _intro_frames(
    start_point,
    frames,
    base_bearing,
    pitch,
    zoom,
    orbit_degrees,
    zoom_out,
    pitch_drop,
):
    if frames <= 0:
        return []

    zoom_start = max(0.0, zoom - zoom_out)
    pitch_start = max(0.0, pitch - pitch_drop)
    cameras: list[FrameCamera] = []
    for idx in range(frames):
        t = _ease_in_out((idx + 1) / frames)
        bearing = (base_bearing + orbit_degrees * (1 - t)) % 360.0
        cameras.append(
            FrameCamera(
                center=[start_point.lon, start_point.lat],
                bearing=bearing,
                pitch=pitch_start + (pitch - pitch_start) * t,
                zoom=zoom_start + (zoom - zoom_start) * t,
                progress=0.0,
            )
        )
    return cameras


def _outro_frames(
    end_point,
    frames,
    base_bearing,
    pitch,
    zoom,
    orbit_degrees,
    zoom_out,
    pitch_drop,
):
    if frames <= 0:
        return []

    zoom_end = max(0.0, zoom - zoom_out)
    pitch_end = max(0.0, pitch - pitch_drop)
    cameras: list[FrameCamera] = []
    for idx in range(frames):
        t = _ease_in_out((idx + 1) / frames)
        bearing = (base_bearing + orbit_degrees * t) % 360.0
        cameras.append(
            FrameCamera(
                center=[end_point.lon, end_point.lat],
                bearing=bearing,
                pitch=pitch + (pitch_end - pitch) * t,
                zoom=zoom + (zoom_end - zoom) * t,
                progress=1.0,
            )
        )
    return cameras


def _smooth_follow_frames(frames: list[FrameCamera], factor: float) -> list[FrameCamera]:
    if not frames:
        return frames

    alpha = min(1.0, max(0.01, factor))
    smooth_center = frames[0].center[:]
    x = math.cos(math.radians(frames[0].bearing))
    y = math.sin(math.radians(frames[0].bearing))
    smooth_bearing = frames[0].bearing

    smoothed: list[FrameCamera] = []
    for frame in frames:
        smooth_center[0] = smooth_center[0] * (1 - alpha) + frame.center[0] * alpha
        smooth_center[1] = smooth_center[1] * (1 - alpha) + frame.center[1] * alpha

        bx = math.cos(math.radians(frame.bearing))
        by = math.sin(math.radians(frame.bearing))
        x = x * (1 - alpha) + bx * alpha
        y = y * (1 - alpha) + by * alpha
        smooth_bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

        smoothed.append(
            FrameCamera(
                center=[smooth_center[0], smooth_center[1]],
                bearing=smooth_bearing,
                pitch=frame.pitch,
                zoom=frame.zoom,
                progress=frame.progress,
            )
        )

    return smoothed


def _ensure_frames_dir(target: Path | None) -> Path:
    if target:
        target.mkdir(parents=True, exist_ok=True)
        return target
    return Path(tempfile.mkdtemp(prefix="trailgen_frames_"))


def _build_renderer_config(map_cfg: MapConfig, options: RenderOptions, start_center):
    return {
        "styleUrl": map_cfg.style_url,
        "styleAttribution": map_cfg.style_attribution,
        "rasterTiles": map_cfg.raster_tiles,
        "rasterAttribution": map_cfg.raster_attribution,
        "terrainTiles": map_cfg.terrain_tiles,
        "terrainAttribution": map_cfg.terrain_attribution,
        "blankStyle": map_cfg.blank_style,
        "width": options.width,
        "height": options.height,
        "initialCenter": start_center,
        "initialZoom": options.zoom,
        "pitch": options.pitch,
    }


def render_video(options: RenderOptions) -> None:
    points = load_gpx(options.gpx_path)
    route_points = to_route_points(points)

    route_points = resample_by_distance(route_points, step_m=10.0)
    route_points = chaikin_smooth(route_points, iterations=2)
    if len(route_points) < 2:
        raise ValueError("Route must contain at least two distinct points.")

    distances = cumulative_distances(route_points)
    total_distance = distances[-1]
    if total_distance <= 0:
        raise ValueError("Route distance is zero.")

    if options.duration is not None:
        duration = max(1.0, options.duration)
    else:
        speed_mps = max(0.1, options.speed_kmh) * 1000 / 3600
        duration = total_distance / speed_mps

    total_frames = max(2, int(duration * options.fps))

    intro_frames = max(0, int(options.intro_seconds * options.fps))
    outro_frames = max(0, int(options.outro_seconds * options.fps))
    if intro_frames + outro_frames > total_frames - 2:
        scale = (total_frames - 2) / max(1, intro_frames + outro_frames)
        intro_frames = int(intro_frames * scale)
        outro_frames = int(outro_frames * scale)

    main_frames = max(2, total_frames - intro_frames - outro_frames)

    route_coords = [[p.lon, p.lat] for p in route_points]
    route_geojson = _build_route_geojson(route_coords)
    marker_geojson = _build_marker_geojson(route_coords)

    map_cfg = map_config(options.map_provider)
    renderer_cfg = _build_renderer_config(map_cfg, options, route_coords[0])
    if options.no_terrain:
        renderer_cfg["terrainTiles"] = None
        renderer_cfg["terrainAttribution"] = None

    start_bearing = bearing_deg(route_points[0], route_points[1]) + options.bearing_offset
    end_bearing = bearing_deg(route_points[-2], route_points[-1]) + options.bearing_offset

    cameras = []
    cameras.extend(
        _intro_frames(
            route_points[0],
            intro_frames,
            start_bearing,
            options.pitch,
            options.zoom,
            options.orbit_degrees,
            options.zoom_out,
            options.pitch_drop,
        )
    )
    follow_frames = _follow_route_frames(
        route_points,
        distances,
        total_distance,
        main_frames,
        options.pitch,
        options.zoom,
        options.bearing_offset,
        options.lookahead_m,
    )
    follow_frames = _smooth_follow_frames(follow_frames, options.smooth_factor)
    cameras.extend(follow_frames)
    cameras.extend(
        _outro_frames(
            route_points[-1],
            outro_frames,
            end_bearing,
            options.pitch,
            options.zoom,
            options.orbit_degrees,
            options.zoom_out,
            options.pitch_drop,
        )
    )

    frames_dir = _ensure_frames_dir(options.frames_dir)
    renderer_dir = (Path(__file__).resolve().parent.parent / ".." / "renderer").resolve()

    print(f"Rendering {total_frames} frames to {frames_dir}...")

    with RendererServer(renderer_dir, map_cfg.raster_tiles, map_cfg.terrain_tiles) as server:
        if server.raster_url_template:
            renderer_cfg["rasterTiles"] = server.raster_url_template
        if server.terrain_url_template:
            renderer_cfg["terrainTiles"] = server.terrain_url_template

        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=[
                    "--use-gl=swiftshader",
                    "--enable-webgl",
                    "--ignore-gpu-blocklist",
                ]
            )
            page = browser.new_page(viewport={"width": options.width, "height": options.height})
            page.set_default_timeout(120_000)
            page.on("console", lambda msg: print(f"[browser {msg.type}] {msg.text}"))
            page.on("pageerror", lambda err: print(f"[browser error] {err}"))
            def log_request_failed(request) -> None:
                failure = request.failure
                error_text = None
                try:
                    if callable(failure):
                        info = failure()
                        if isinstance(info, dict):
                            error_text = info.get("errorText")
                    elif isinstance(failure, dict):
                        error_text = failure.get("errorText")
                    else:
                        error_text = getattr(failure, "error_text", None)
                except Exception:
                    error_text = None

                if not error_text:
                    error_text = "request failed"
                print(f"[request failed] {error_text} {request.url}")

            page.on("requestfailed", log_request_failed)
            page.add_init_script(f"window.__CONFIG__ = {json.dumps(renderer_cfg)};")
            page.goto(f"{server.base_url}/index.html", wait_until="load")
            page.wait_for_function("window.__READY__ === true || window.__READY__ === 'error'")
            ready_state = page.evaluate("window.__READY__")
            if ready_state != True:
                error_message = page.evaluate("window.__ERROR__") or "Renderer failed to initialize."
                raise RuntimeError(error_message)

            page.evaluate("data => window.__setRoute(data)", route_geojson)
            page.evaluate("data => window.__setMarkers(data)", marker_geojson)
            page.wait_for_function("window.__ROUTE_READY__ === true")

            for idx, cam in enumerate(cameras, start=1):
                page.evaluate("data => window.__renderFrame(data)", cam.__dict__)
                frame_path = frames_dir / f"frame_{idx:06d}.png"
                page.screenshot(path=str(frame_path))
                if idx % 120 == 0 or idx == total_frames:
                    print(f"  Frame {idx}/{total_frames}")

            browser.close()

    print("Encoding video...")
    try:
        encode_video(frames_dir, options.out_path, options.fps, options.crf, options.preset)
    except FFmpegError as exc:
        raise RuntimeError(str(exc)) from exc

    if not options.keep_frames and options.frames_dir is None:
        for frame in frames_dir.glob("frame_*.png"):
            frame.unlink(missing_ok=True)
        frames_dir.rmdir()

    print(f"Done: {options.out_path}")
