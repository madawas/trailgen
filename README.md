# 3D Trail Video Generator

Generate 3D trail videos from GPX files using a Python CLI, MapLibre GL, and ffmpeg.

## Quickstart

1. Install dependencies with `uv`:

```bash
uv venv
uv pip install -e ".[dev]"
```

2. Add your map provider credentials in `.env`:

```bash
# MapTiler (default)
MAPTILER_KEY=your_key_here
# Optional: terrain exaggeration (MapDirector uses ~1.5)
# MAP_TERRAIN_EXAGGERATION=1.5

# Mapbox (optional, MapDirector-like satellite labels)
# MAP_PROVIDER=mapbox
# MAPBOX_TOKEN=your_token_here
# MAPBOX_STYLE_URL=https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12?access_token={token}
# MAPBOX_TERRAIN_TILES=https://api.mapbox.com/raster/v1/mapbox.mapbox-terrain-dem-v1/{z}/{x}/{y}.png?access_token={token}
# MAP_MAX_ZOOM=18
```

3. Install Playwright browser binaries (one-time):

```bash
uv run playwright install chromium
```

Note: Installing the Python package does not install Playwright browser binaries. You must run the command above on each machine.

4. Render a video (vertical 720p @ 30 fps):

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route.mp4 --fps 30 --resolution 720p --orientation portrait --duration 45
```

Note: `uv init` is only for creating new projects. This repo already has `pyproject.toml`, so you can go straight to `uv venv`/`uv run`.

## Tile Cache

Tiles are cached on disk at `~/.trailgen/cache`.

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

The renderer uses MapTiler's `hybrid-v4` style by default and a terrain DEM for 3D relief. To match MapDirector's look, switch to Mapbox:

```bash
MAP_PROVIDER=mapbox
MAPBOX_TOKEN=your_token_here
MAP_MAX_ZOOM=18
```

If you have access to the MapDirector style, you can set:

```bash
MAPBOX_STYLE_URL=https://api.mapbox.com/styles/v1/brunomapdirector/cm7uf30u5019501s21cdtbe2c?access_token={token}
```

## Route Styling

Customize colors and widths:

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route.mp4 --route-color \"#22c55e\" --route-width 5
```

## Output Notes

- The renderer writes PNG frames and then encodes to H.264 MP4 using ffmpeg.
- Use `--keep-frames` to keep PNGs for debugging.
- Use `--frames-dir` to direct frames to a specific folder.
- Fly-in/out tuning options: `--intro-seconds`, `--outro-seconds`, `--orbit-deg`, `--zoom-out`, `--pitch-drop`.
- The renderer serves a local HTTP page and proxies tiles to avoid CORS issues with tile requests.

## Camera Modes

Use `--camera-mode auto` (default) for adaptive terrain-aware framing, or `--camera-mode follow` to match a fixed distance/pitch style (similar to MapDirector).

Example follow mode:

```bash
uv run trailgen render --gpx /path/to/route.gpx --out outputs/route-follow.mp4 \\
  --camera-mode follow --follow-distance-m 500 --follow-pitch 60 \\
  --follow-lookahead-m 120 --follow-bearing-sensitivity 3 \\
  --follow-panning-sensitivity 1.5 --follow-smoothing-s 0.5
```

## Troubleshooting

- If you see `ffmpeg not found`, install ffmpeg and ensure it is on your PATH.
- If Playwright cannot launch, re-run `playwright install chromium`.
- To enable verbose network/debug logs, set `TRAILGEN_DEBUG=1`.

## Development

Install pre-commit hooks:

```bash
uv run pre-commit install
```

Run format/lint:

```bash
make format
make lint
make precommit
```

Release build and tag:

```bash
make release VERSION=0.1.0
```

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See `LICENSE`.
