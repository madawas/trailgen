from __future__ import annotations

import argparse
import getpass
import logging
import os
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from trailgen.config import (
    load_app_config,
    parse_size,
    resolve_config_path,
    save_app_config,
)
from trailgen.render import RenderOptions, render_video

RESOLUTION_DIMENSIONS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}

_DEBUG_VALUES = {"1", "true", "yes", "on"}


def _parse_log_level(value: str | None) -> int | None:
    if not value:
        return None
    level = logging.getLevelName(value.upper())
    return level if isinstance(level, int) else None


def configure_logging() -> None:
    level = _parse_log_level(os.getenv("TRAILGEN_LOG_LEVEL"))
    if level is None:
        debug = os.getenv("TRAILGEN_DEBUG", "").lower() in _DEBUG_VALUES
        level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def resolve_dimensions(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[int, int]:
    width = args.width
    height = args.height

    if (width is None) ^ (height is None):
        parser.error("Both --width and --height must be set together.")

    if width is not None and height is not None:
        return width, height

    base_width, base_height = RESOLUTION_DIMENSIONS[args.resolution]
    if args.orientation == "portrait":
        return base_height, base_width
    return base_width, base_height


def _format_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{int(value)} B"


def _prompt_value(
    label: str,
    current,
    *,
    secret: bool = False,
    parser=None,
    display: str | None = None,
):
    while True:
        if secret:
            current_hint = "set" if current else "not set"
            prompt = f"{label} [{current_hint}]: "
            value = getpass.getpass(prompt)
        else:
            current_hint = "" if current is None else (display or str(current))
            prompt = f"{label} [{current_hint}]: " if current_hint else f"{label}: "
            value = input(prompt)
        if value == "":
            return current
        if parser:
            try:
                return parser(value)
            except ValueError as exc:
                print(f"Invalid {label}: {exc}")
                continue
        return value


def _prompt_provider(current: str) -> str:
    def parse_provider(value: str) -> str:
        lowered = value.strip().lower()
        if lowered not in {"maptiler", "mapbox"}:
            raise ValueError("Use 'maptiler' or 'mapbox'.")
        return lowered

    return _prompt_value(
        "Map provider (maptiler|mapbox)", current or "maptiler", parser=parse_provider
    )


def _validate_provider(value: str) -> str:
    lowered = value.strip().lower()
    if lowered not in {"maptiler", "mapbox"}:
        raise ValueError("Map provider must be 'maptiler' or 'mapbox'.")
    return lowered


def handle_configure(args: argparse.Namespace) -> None:
    config_path = resolve_config_path(args.config_path)
    current = load_app_config(config_path, include_env=False)

    updates: dict[str, object] = {}

    def set_value(field: str, value):
        if value is not None:
            updates[field] = value

    if args.non_interactive:
        if args.cache_max is not None:
            updates["cache_max_bytes"] = parse_size(
                args.cache_max, current.cache_max_bytes
            )
        if args.map_provider is not None:
            updates["map_provider"] = _validate_provider(args.map_provider)
        set_value("maptiler_key", args.maptiler_key)
        set_value("mapbox_token", args.mapbox_token)
        set_value("style_url", args.style_url)
        set_value("terrain_tiles", args.terrain_tiles)
        set_value("terrain_encoding", args.terrain_encoding)
        set_value("terrain_exaggeration", args.terrain_exaggeration)
        set_value("max_zoom", args.max_zoom)
        set_value("cache_dir", args.cache_dir)

        if not updates:
            raise SystemExit("No configuration values provided.")
    else:
        provider = (
            _validate_provider(args.map_provider)
            if args.map_provider is not None
            else _prompt_provider(current.map_provider)
        )

        def parse_encoding(value: str) -> str:
            lowered = value.strip().lower()
            if lowered not in {"mapbox", "terrarium"}:
                raise ValueError("Use 'mapbox' or 'terrarium'.")
            return lowered

        def parse_exaggeration(value: str) -> float:
            parsed = float(value)
            if parsed <= 0:
                raise ValueError("Value must be greater than 0.")
            return parsed

        def parse_max_zoom(value: str) -> float:
            parsed = float(value)
            if parsed <= 0:
                raise ValueError("Value must be greater than 0.")
            return parsed

        maptiler_key = current.maptiler_key
        mapbox_token = current.mapbox_token
        if provider == "maptiler":
            maptiler_key = (
                args.maptiler_key
                if args.maptiler_key is not None
                else _prompt_value(
                    "MapTiler API key", current.maptiler_key, secret=True
                )
            )
        else:
            mapbox_token = (
                args.mapbox_token
                if args.mapbox_token is not None
                else _prompt_value("Mapbox token", current.mapbox_token, secret=True)
            )

        cache_dir = (
            args.cache_dir
            if args.cache_dir is not None
            else Path(_prompt_value("Cache directory", current.cache_dir)).expanduser()
        )
        cache_max_bytes = (
            parse_size(args.cache_max, current.cache_max_bytes)
            if args.cache_max is not None
            else _prompt_value(
                "Cache max size",
                current.cache_max_bytes,
                display=_format_bytes(current.cache_max_bytes),
                parser=lambda v: parse_size(v, current.cache_max_bytes),
            )
        )
        style_url = (
            args.style_url
            if args.style_url is not None
            else _prompt_value("Map style URL (optional)", current.style_url)
        )
        terrain_tiles = (
            args.terrain_tiles
            if args.terrain_tiles is not None
            else _prompt_value("Terrain tiles URL (optional)", current.terrain_tiles)
        )
        terrain_encoding = (
            args.terrain_encoding
            if args.terrain_encoding is not None
            else _prompt_value(
                "Terrain encoding (mapbox|terrarium)",
                current.terrain_encoding or "mapbox",
                parser=parse_encoding,
            )
        )
        terrain_exaggeration = (
            args.terrain_exaggeration
            if args.terrain_exaggeration is not None
            else _prompt_value(
                "Terrain exaggeration",
                (
                    current.terrain_exaggeration
                    if current.terrain_exaggeration is not None
                    else 1.2
                ),
                parser=parse_exaggeration,
            )
        )
        max_zoom = (
            args.max_zoom
            if args.max_zoom is not None
            else _prompt_value(
                "Max zoom (optional)",
                current.max_zoom,
                parser=parse_max_zoom,
            )
        )

        updates = {
            "map_provider": provider,
            "maptiler_key": maptiler_key,
            "mapbox_token": mapbox_token,
            "style_url": style_url,
            "terrain_tiles": terrain_tiles,
            "terrain_encoding": terrain_encoding,
            "terrain_exaggeration": terrain_exaggeration,
            "max_zoom": max_zoom,
            "cache_dir": cache_dir,
            "cache_max_bytes": cache_max_bytes,
        }

    updated = replace(current, **updates)
    path = save_app_config(updated, config_path)
    print(f"Saved config to {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trailgen",
        description="Generate 3D trail videos from GPX files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    configure = sub.add_parser(
        "configure", help="Configure default settings (stored on disk)."
    )
    configure.add_argument(
        "--config-path",
        type=Path,
        default=None,
        help="Optional config file path override.",
    )
    configure.add_argument(
        "--map-provider",
        choices=["maptiler", "mapbox"],
        default=None,
        help="Map provider (maptiler or mapbox).",
    )
    configure.add_argument(
        "--maptiler-key", type=str, default=None, help="MapTiler API key."
    )
    configure.add_argument(
        "--mapbox-token", type=str, default=None, help="Mapbox access token."
    )
    configure.add_argument(
        "--style-url",
        type=str,
        default=None,
        help="Map style URL template (supports {key} or {token}).",
    )
    configure.add_argument(
        "--terrain-tiles",
        type=str,
        default=None,
        help="Terrain tiles URL template (supports {key} or {token}).",
    )
    configure.add_argument(
        "--terrain-encoding",
        type=str,
        choices=["mapbox", "terrarium"],
        default=None,
        help="Terrain tile encoding.",
    )
    configure.add_argument(
        "--terrain-exaggeration",
        type=float,
        default=None,
        help="Terrain exaggeration multiplier.",
    )
    configure.add_argument(
        "--max-zoom",
        type=float,
        default=None,
        help="Override map max zoom.",
    )
    configure.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Cache directory for tiles.",
    )
    configure.add_argument(
        "--cache-max",
        type=str,
        default=None,
        help="Cache size limit (bytes or KB/MB/GB/TB).",
    )
    configure.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; only use provided flags.",
        default=False,
    )

    render = sub.add_parser("render", help="Render a 3D trail video from a GPX file.")
    render.add_argument("--gpx", required=True, type=Path, help="Path to a GPX file.")
    render.add_argument(
        "--out", required=True, type=Path, help="Output video path (mp4)."
    )
    render.add_argument("--fps", type=int, default=30, help="Frames per second.")
    render.add_argument(
        "--resolution",
        choices=["720p", "1080p", "4k"],
        default="720p",
        help="Preset resolution (ignored if --width/--height are set).",
    )
    render.add_argument(
        "--orientation",
        choices=["portrait", "landscape"],
        default="portrait",
        help="Orientation for preset resolutions.",
    )
    render.add_argument(
        "--width", type=int, default=None, help="Frame width in pixels."
    )
    render.add_argument(
        "--height", type=int, default=None, help="Frame height in pixels."
    )
    render.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Target video duration in seconds. Overrides --speed-kmh if set.",
    )
    render.add_argument(
        "--quality",
        choices=["preview", "final"],
        default="final",
        help="Quality preset (preview renders faster, final renders with full tiles).",
    )
    render.add_argument(
        "--lookahead-m",
        type=float,
        default=None,
        help="Override auto camera lookahead distance in meters.",
    )
    render.add_argument(
        "--speed-kmh",
        type=float,
        default=20.0,
        help="Route speed in km/h for computing duration.",
    )
    render.add_argument(
        "--camera-mode",
        choices=["auto", "follow"],
        default="auto",
        help="Camera mode (auto for adaptive, follow for fixed distance/pitch).",
    )
    render.add_argument(
        "--follow-distance-m",
        type=float,
        default=500.0,
        help="Follow mode camera distance from target (meters).",
    )
    render.add_argument(
        "--follow-pitch",
        type=float,
        default=60.0,
        help="Follow mode camera pitch in degrees (0=top-down, 60=oblique).",
    )
    render.add_argument(
        "--follow-lookahead-m",
        type=float,
        default=120.0,
        help="Follow mode lookahead distance for bearing (meters).",
    )
    render.add_argument(
        "--follow-bearing-sensitivity",
        type=float,
        default=3.0,
        help="Follow mode bearing responsiveness (higher = more reactive).",
    )
    render.add_argument(
        "--follow-panning-sensitivity",
        type=float,
        default=1.5,
        help="Follow mode target responsiveness (higher = more reactive).",
    )
    render.add_argument(
        "--follow-smoothing-s",
        type=float,
        default=0.5,
        help="Follow mode smoothing window in seconds.",
    )
    render.add_argument(
        "--follow-min-clearance-m",
        type=float,
        default=30.0,
        help="Minimum camera clearance above terrain in follow mode (meters).",
    )
    render.add_argument(
        "--route-smooth",
        type=int,
        default=1,
        help="Chaikin smoothing iterations for the route line.",
    )
    render.add_argument(
        "--route-color",
        type=str,
        default="#3b82f6",
        help="Route line color.",
    )
    render.add_argument(
        "--route-width",
        type=float,
        default=4.0,
        help="Route line width.",
    )
    render.add_argument(
        "--intro-seconds",
        type=float,
        default=2.5,
        help="Intro fly-in duration in seconds.",
    )
    render.add_argument(
        "--outro-seconds",
        type=float,
        default=2.0,
        help="Outro fly-out duration in seconds.",
    )
    render.add_argument(
        "--frames-dir",
        type=Path,
        default=None,
        help="Directory to write frames to. Defaults to a temp directory.",
    )
    render.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep frame PNGs after encoding.",
        default=False,
    )
    render.add_argument(
        "--crf",
        type=int,
        default=18,
        help="H.264 CRF value (lower is higher quality).",
    )
    render.add_argument(
        "--preset",
        type=str,
        default="slow",
        help="FFmpeg preset (e.g., veryfast, fast, medium, slow).",
    )

    return parser


def main() -> None:
    load_dotenv()
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "configure":
        handle_configure(args)
        return

    if args.command == "render":
        width, height = resolve_dimensions(args, parser)
        options = RenderOptions(
            gpx_path=args.gpx,
            out_path=args.out,
            fps=args.fps,
            width=width,
            height=height,
            duration=args.duration,
            speed_kmh=args.speed_kmh,
            quality=args.quality,
            lookahead_m=args.lookahead_m,
            intro_seconds=args.intro_seconds,
            outro_seconds=args.outro_seconds,
            route_smooth=args.route_smooth,
            route_color=args.route_color,
            route_width=args.route_width,
            frames_dir=args.frames_dir,
            keep_frames=args.keep_frames,
            crf=args.crf,
            preset=args.preset,
            camera_mode=args.camera_mode,
            follow_distance_m=args.follow_distance_m,
            follow_pitch_deg=args.follow_pitch,
            follow_lookahead_m=args.follow_lookahead_m,
            follow_bearing_sensitivity=args.follow_bearing_sensitivity,
            follow_panning_sensitivity=args.follow_panning_sensitivity,
            follow_smoothing_s=args.follow_smoothing_s,
            follow_min_clearance_m=args.follow_min_clearance_m,
        )
        render_video(options)


if __name__ == "__main__":
    main()
