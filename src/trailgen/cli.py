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
        "--speed-kmh",
        type=float,
        default=20.0,
        help="Route speed in km/h for computing duration.",
    )
    render.add_argument(
        "--zoom",
        type=float,
        default=14.0,
        help="Camera zoom level.",
    )
    render.add_argument(
        "--pitch",
        type=float,
        default=60.0,
        help="Camera pitch angle in degrees.",
    )
    render.add_argument(
        "--lookahead-m",
        type=float,
        default=100.0,
        help="Lookahead distance in meters for camera bearing.",
    )
    render.add_argument(
        "--smooth-factor",
        type=float,
        default=0.05,
        help="Camera bearing smoothing factor (0-1). Higher = less smoothing.",
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
        "--bearing-offset",
        type=float,
        default=0.0,
        help="Extra degrees to add to the route bearing.",
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
        "--orbit-deg",
        type=float,
        default=110.0,
        help="Degrees to orbit during intro/outro.",
    )
    render.add_argument(
        "--zoom-out",
        type=float,
        default=1.8,
        help="Zoom-out amount for fly-in/out.",
    )
    render.add_argument(
        "--pitch-drop",
        type=float,
        default=15.0,
        help="Pitch drop amount for fly-in/out.",
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
    debug = os.getenv("TRAILGEN_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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
            zoom=args.zoom,
            pitch=args.pitch,
            bearing_offset=args.bearing_offset,
            intro_seconds=args.intro_seconds,
            outro_seconds=args.outro_seconds,
            orbit_degrees=args.orbit_deg,
            zoom_out=args.zoom_out,
            pitch_drop=args.pitch_drop,
            lookahead_m=args.lookahead_m,
            smooth_factor=args.smooth_factor,
            route_smooth=args.route_smooth,
            route_color=args.route_color,
            route_width=args.route_width,
            frames_dir=args.frames_dir,
            keep_frames=args.keep_frames,
            crf=args.crf,
            preset=args.preset,
        )
        render_video(options)


if __name__ == "__main__":
    main()
