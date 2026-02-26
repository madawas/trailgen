from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trailgen",
        description="Generate 3D trail videos from GPX files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

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
