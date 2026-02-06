# 3D Trail Video Generator

Generate 3D trail videos from GPX files using a Python CLI, MapLibre GL, and ffmpeg.

## Quickstart

1. Install dependencies with `uv`:

```bash
uv venv
uv pip install -e .
```

2. Add your MapTiler API key in `.env`:

```bash
# MapTiler (required)
MAPTILER_KEY=your_key_here
```

3. Install Playwright browser binaries (one-time):

```bash
uv run playwright install chromium
```

4. Render a video (vertical 720p @ 30 fps):

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route.mp4 --fps 30 --resolution 720p --orientation portrait --duration 45
```

If terrain tiles are failing or slow, you can disable terrain:

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route.mp4 --no-terrain
```

Note: `uv init` is only for creating new projects. This repo already has `pyproject.toml`, so you can go straight to `uv venv`/`uv run`.

## Resolution and Orientation

- Presets: `--resolution 720p|1080p|4k`
- Orientation: `--orientation portrait|landscape`
- Override with explicit `--width` and `--height`

Example 1080p portrait @ 60 fps:

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route-1080.mp4 --fps 60 --resolution 1080p --orientation portrait --duration 45
```

## 4K Rendering

Use a 4K frame size:

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route-4k.mp4 --fps 60 --resolution 4k --orientation landscape --duration 45
```

## Maps

The renderer uses MapTiler's `hybrid-v4` style by default and a terrain DEM for 3D relief.

## Route Styling

By default the route animates in blue with no markers or outline. You can enable them:

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route.mp4 --show-markers --show-outline
```

Customize colors and widths:

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route.mp4 --route-color \"#22c55e\" --route-width 5 --outline-color \"#0f172a\" --outline-width 8
```

## Output Notes

- The renderer writes PNG frames and then encodes to H.264 MP4 using ffmpeg.
- Use `--keep-frames` to keep PNGs for debugging.
- Use `--frames-dir` to direct frames to a specific folder.
- Fly-in/out tuning options: `--intro-seconds`, `--outro-seconds`, `--orbit-deg`, `--zoom-out`, `--pitch-drop`.
- The renderer serves a local HTTP page and proxies tiles to avoid CORS issues with tile requests.

## Troubleshooting

- If you see `ffmpeg not found`, install ffmpeg and ensure it is on your PATH.
- If Playwright cannot launch, re-run `playwright install chromium`.

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See `LICENSE`.
