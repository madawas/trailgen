from __future__ import annotations

import json
import logging
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from trailgen.camera_auto import (
    AutoCameraConfig,
    FreeCameraFrame,
    build_auto_camera_frames,
)
from trailgen.config import MapConfig, map_config
from trailgen.ffmpeg import FFmpegError, encode_video
from trailgen.geo import (
    RoutePoint,
    chaikin_smooth,
    cumulative_distances,
    resample_by_distance,
    to_route_points,
)
from trailgen.gpx import load_gpx
from trailgen.server import RendererServer
from trailgen.terrain import TerrainSampler, select_dem_zoom

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderOptions:
    gpx_path: Path
    out_path: Path
    fps: int
    width: int
    height: int
    duration: float | None
    speed_kmh: float
    quality: str
    lookahead_m: float | None
    intro_seconds: float
    outro_seconds: float
    route_smooth: int
    route_color: str
    route_width: float
    frames_dir: Path | None
    keep_frames: bool
    crf: int
    preset: str


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


def _ensure_frames_dir(target: Path | None) -> Path:
    if target:
        target.mkdir(parents=True, exist_ok=True)
        return target
    return Path(tempfile.mkdtemp(prefix="trailgen_frames_"))


def _build_renderer_config(
    map_cfg: MapConfig,
    options: RenderOptions,
    start_center,
    initial_zoom: float,
    initial_pitch: float,
    max_zoom: float,
    frame_wait: str,
    frame_delay_ms: int,
    frame_timeout_ms: int,
):
    return {
        "styleUrl": map_cfg.style_url,
        "styleAttribution": map_cfg.style_attribution,
        "rasterTiles": map_cfg.raster_tiles,
        "rasterAttribution": map_cfg.raster_attribution,
        "terrainTiles": map_cfg.terrain_tiles,
        "terrainAttribution": map_cfg.terrain_attribution,
        "terrainEncoding": map_cfg.terrain_encoding,
        "terrainExaggeration": map_cfg.terrain_exaggeration,
        "blankStyle": map_cfg.blank_style,
        "routeColor": options.route_color,
        "routeWidth": options.route_width,
        "width": options.width,
        "height": options.height,
        "initialCenter": start_center,
        "initialZoom": initial_zoom,
        "pitch": initial_pitch,
        "maxZoom": max_zoom,
        "frameWait": frame_wait,
        "frameDelayMs": frame_delay_ms,
        "frameTimeoutMs": frame_timeout_ms,
    }


def render_video(options: RenderOptions) -> None:
    points = load_gpx(options.gpx_path)
    route_points = to_route_points(points)

    route_points = resample_by_distance(route_points, step_m=100.0)
    if options.route_smooth > 0:
        route_points = chaikin_smooth(route_points, iterations=options.route_smooth)
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

    route_coords = [[p.lon, p.lat] for p in route_points]
    route_geojson = _build_route_geojson(route_coords)

    map_cfg = map_config()
    scale = options.height / 1280.0
    scaled_route_width = max(1.0, options.route_width * scale)
    initial_zoom = max(2.0, min(16.0, 12.0 + math.log2(scale)))
    initial_pitch = 60.0

    quality = options.quality.lower()
    if quality not in {"preview", "final"}:
        raise ValueError(f"Unknown quality preset: {options.quality}")

    auto_params = {
        "side_offset_m": 400.0,
        "back_offset_m": 260.0,
        "base_clearance_m": 220.0,
        "lookahead_m": 320.0,
        "relief_factor": 0.35,
        "summit_boost_m": 220.0,
        "relief_window_m": 900.0,
        "summit_sigma_m": 450.0,
    }
    dem_zoom_bias = -2
    device_scale_factor = 1.0
    if quality == "preview":
        max_zoom = 14.0
        frame_wait = "render"
        frame_delay_ms = 150
        frame_timeout_ms = 6000
    else:
        max_zoom = 14.0
        frame_wait = "idle"
        frame_delay_ms = 0
        frame_timeout_ms = 20000
        device_scale_factor = 2.0

    renderer_cfg = _build_renderer_config(
        map_cfg,
        options,
        route_coords[0],
        initial_zoom,
        initial_pitch,
        max_zoom=max_zoom,
        frame_wait=frame_wait,
        frame_delay_ms=frame_delay_ms,
        frame_timeout_ms=frame_timeout_ms,
    )
    renderer_cfg["routeWidth"] = scaled_route_width
    renderer_cfg["initialZoom"] = initial_zoom

    cache_dir = Path("~/.trailgen/cache").expanduser()

    cameras: list[FreeCameraFrame] = []
    if map_cfg.terrain_tiles:
        avg_lat = sum(p.lat for p in route_points) / len(route_points)
        base_dem_zoom = select_dem_zoom(avg_lat)
        dem_zoom = max(8, min(14, base_dem_zoom + dem_zoom_bias))
        terrain = TerrainSampler(
            map_cfg.terrain_tiles,
            map_cfg.terrain_encoding or "mapbox",
            cache_dir=cache_dir,
            zoom=dem_zoom,
            exaggeration=map_cfg.terrain_exaggeration or 1.0,
        )

        elevations = [p.ele for p in route_points]
        if max(elevations) - min(elevations) < 5.0:
            sampled = []
            for pt in route_points:
                height = terrain.height_at(pt.lon, pt.lat)
                sampled.append(height if height is not None else pt.ele)
            elevations = sampled
            route_points = [
                RoutePoint(pt.lat, pt.lon, elevations[idx])
                for idx, pt in enumerate(route_points)
            ]

        summit_idx = max(range(len(elevations)), key=lambda idx: elevations[idx])
        summit_distance = distances[summit_idx]

        lookahead_m = (
            options.lookahead_m
            if options.lookahead_m is not None
            else auto_params["lookahead_m"]
        )
        auto_cfg = AutoCameraConfig(
            fps=options.fps,
            intro_frames=intro_frames,
            outro_frames=outro_frames,
            total_frames=total_frames,
            lookahead_m=lookahead_m,
            side_offset_m=auto_params["side_offset_m"],
            back_offset_m=auto_params["back_offset_m"],
            base_clearance_m=auto_params["base_clearance_m"],
            relief_factor=auto_params["relief_factor"],
            summit_boost_m=auto_params["summit_boost_m"],
            relief_window_m=auto_params["relief_window_m"],
            summit_sigma_m=auto_params["summit_sigma_m"],
        )
        cameras = build_auto_camera_frames(
            route_points,
            distances,
            total_distance,
            auto_cfg,
            terrain,
            summit_distance,
            elevations,
        )
    else:
        raise RuntimeError("Terrain tiles are required for auto camera mode.")

    frames_dir = _ensure_frames_dir(options.frames_dir)
    renderer_dir = (
        Path(__file__).resolve().parent.parent / ".." / "renderer"
    ).resolve()

    logger.info("Rendering %s frames to %s...", total_frames, frames_dir)

    debug = logger.isEnabledFor(logging.DEBUG)

    with RendererServer(
        renderer_dir,
        map_cfg.raster_tiles,
        map_cfg.terrain_tiles,
        cache_dir=cache_dir,
    ) as server:
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
            page = browser.new_page(
                viewport={"width": options.width, "height": options.height},
                device_scale_factor=device_scale_factor,
            )
            page.set_default_timeout(120_000)
            if debug:
                page.on(
                    "console",
                    lambda msg: logger.debug("[browser %s] %s", msg.type, msg.text),
                )
                page.on(
                    "pageerror", lambda err: logger.debug("[browser error] %s", err)
                )

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
                    logger.debug("[request failed] %s %s", error_text, request.url)

                page.on("requestfailed", log_request_failed)
            page.add_init_script(f"window.__CONFIG__ = {json.dumps(renderer_cfg)};")
            page.goto(f"{server.base_url}/index.html", wait_until="load")
            page.wait_for_function(
                "window.__READY__ === true || window.__READY__ === 'error'"
            )
            ready_state = page.evaluate("window.__READY__")
            if not ready_state:
                error_message = (
                    page.evaluate("window.__ERROR__")
                    or "Renderer failed to initialize."
                )
                raise RuntimeError(error_message)

            page.evaluate("data => window.__setRoute(data)", route_geojson)
            page.wait_for_function("window.__ROUTE_READY__ === true")

            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.percentage:>3.0f}%"),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                transient=False,
            ) as progress:
                task_id = progress.add_task("Rendering frames", total=total_frames)
                for idx, cam in enumerate(cameras, start=1):
                    page.evaluate("data => window.__renderFrame(data)", cam.__dict__)
                    frame_path = frames_dir / f"frame_{idx:06d}.png"
                    screenshot_kwargs = {"path": str(frame_path)}
                    if device_scale_factor > 1.0:
                        screenshot_kwargs["scale"] = "css"
                    try:
                        page.screenshot(**screenshot_kwargs)
                    except TypeError:
                        screenshot_kwargs.pop("scale", None)
                        page.screenshot(**screenshot_kwargs)
                    progress.update(task_id, advance=1)

            browser.close()

    logger.info("Encoding video...")
    try:
        encode_video(
            frames_dir, options.out_path, options.fps, options.crf, options.preset
        )
    except FFmpegError as exc:
        raise RuntimeError(str(exc)) from exc

    if not options.keep_frames and options.frames_dir is None:
        for frame in frames_dir.glob("frame_*.png"):
            frame.unlink(missing_ok=True)
        frames_dir.rmdir()

    logger.info("Done: %s", options.out_path)
