from __future__ import annotations

import configparser
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path


MAPTILER_STYLE = "https://api.maptiler.com/maps/hybrid-v4/style.json?key={key}"
MAPTILER_TERRAIN_TILES = (
    "https://api.maptiler.com/tiles/terrain-rgb-v2/{{z}}/{{x}}/{{y}}.webp?key={key}"
)
MAPTILER_TERRAIN_ENCODING = "mapbox"

MAPBOX_STYLE_URL = (
    "https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12"
    "?access_token={token}"
)
MAPBOX_TERRAIN_TILES = (
    "https://api.mapbox.com/raster/v1/mapbox.mapbox-terrain-dem-v1"
    "/{z}/{x}/{y}.png?access_token={token}"
)

DEFAULT_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_PROVIDER = "maptiler"


@dataclass(frozen=True)
class AppConfig:
    map_provider: str
    maptiler_key: str | None
    mapbox_token: str | None
    style_url: str | None
    terrain_tiles: str | None
    terrain_encoding: str | None
    terrain_exaggeration: float | None
    max_zoom: float | None
    cache_dir: Path
    cache_max_bytes: int


@dataclass(frozen=True)
class MapConfig:
    style_url: str | None
    style_attribution: str | None
    raster_tiles: str | None
    raster_attribution: str | None
    terrain_tiles: str | None
    terrain_attribution: str | None
    terrain_encoding: str | None
    terrain_exaggeration: float | None
    max_zoom: float | None
    map_provider: str
    mapbox_token: str | None
    blank_style: bool = False


def _default_config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "trailgen"


def resolve_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    env_path = os.getenv("TRAILGEN_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return _default_config_dir() / "config.ini"


def _default_cache_dir() -> Path:
    return Path("~/.trailgen/cache").expanduser()


def parse_size(value: str | None, default: int) -> int:
    if not value:
        return default
    text = value.strip().lower()
    if not text:
        return default
    if text.isdigit():
        return max(0, int(text))
    units = {"kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}
    for suffix, multiplier in units.items():
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            if not number:
                raise ValueError("Missing size value.")
            return max(0, int(float(number) * multiplier))
    raise ValueError(f"Unrecognized size '{value}'. Use bytes or KB/MB/GB/TB.")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_float(value: str | None, name: str) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"Invalid {name}: {value!r}") from None


def load_app_config(
    config_path: Path | None = None, include_env: bool = True
) -> AppConfig:
    path = resolve_config_path(config_path)
    parser = configparser.ConfigParser()
    if path.is_file():
        parser.read(path)
    section = parser["default"] if parser.has_section("default") else {}

    provider = _clean(section.get("map_provider")) or DEFAULT_PROVIDER
    maptiler_key = _clean(section.get("maptiler_key"))
    mapbox_token = _clean(section.get("mapbox_token"))
    style_url = _clean(section.get("style_url"))
    terrain_tiles = _clean(section.get("terrain_tiles"))
    terrain_encoding = _clean(section.get("terrain_encoding"))
    terrain_exaggeration = _parse_float(
        section.get("terrain_exaggeration"), "terrain_exaggeration"
    )
    max_zoom = _parse_float(section.get("max_zoom"), "max_zoom")

    cache_dir_value = section.get("cache_dir")
    if cache_dir_value is None or not cache_dir_value.strip():
        cache_dir_value = str(_default_cache_dir())
    cache_dir = Path(cache_dir_value).expanduser()

    cache_max = section.get("cache_max_bytes") or section.get("cache_max")
    cache_max_bytes = parse_size(cache_max, DEFAULT_CACHE_MAX_BYTES)

    if include_env:
        provider = os.getenv("MAP_PROVIDER", provider)
        maptiler_key = (
            os.getenv("TRAILGEN_MAPTILER_KEY")
            or os.getenv("MAPTILER_KEY")
            or maptiler_key
        )
        mapbox_token = os.getenv("MAPBOX_TOKEN") or mapbox_token

        style_url = os.getenv("TRAILGEN_STYLE_URL") or style_url
        terrain_tiles = os.getenv("TRAILGEN_TERRAIN_TILES") or terrain_tiles

        if provider.lower() == "mapbox":
            style_url = os.getenv("MAPBOX_STYLE_URL") or style_url
            terrain_tiles = os.getenv("MAPBOX_TERRAIN_TILES") or terrain_tiles

        terrain_encoding = os.getenv("TRAILGEN_TERRAIN_ENCODING") or terrain_encoding

        terrain_exaggeration_env = (
            os.getenv("TRAILGEN_TERRAIN_EXAGGERATION")
            or os.getenv("MAP_TERRAIN_EXAGGERATION")
            or os.getenv("TERRAIN_EXAGGERATION")
        )
        terrain_exaggeration = (
            _parse_float(terrain_exaggeration_env, "terrain_exaggeration")
            if terrain_exaggeration_env
            else terrain_exaggeration
        )

        max_zoom_env = os.getenv("TRAILGEN_MAX_ZOOM") or os.getenv("MAP_MAX_ZOOM")
        max_zoom = _parse_float(max_zoom_env, "max_zoom") if max_zoom_env else max_zoom

        cache_dir = Path(os.getenv("TRAILGEN_CACHE_DIR", str(cache_dir))).expanduser()
        cache_max_env = os.getenv("TRAILGEN_CACHE_MAX") or os.getenv(
            "TRAILGEN_CACHE_MAX_BYTES"
        )
        if cache_max_env:
            cache_max_bytes = parse_size(cache_max_env, cache_max_bytes)

    return AppConfig(
        map_provider=provider.lower(),
        maptiler_key=maptiler_key,
        mapbox_token=mapbox_token,
        style_url=style_url,
        terrain_tiles=terrain_tiles,
        terrain_encoding=terrain_encoding,
        terrain_exaggeration=terrain_exaggeration,
        max_zoom=max_zoom,
        cache_dir=cache_dir,
        cache_max_bytes=cache_max_bytes,
    )


def save_app_config(config: AppConfig, config_path: Path | None = None) -> Path:
    path = resolve_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser()
    parser["default"] = {
        "map_provider": config.map_provider,
        "maptiler_key": config.maptiler_key or "",
        "mapbox_token": config.mapbox_token or "",
        "style_url": config.style_url or "",
        "terrain_tiles": config.terrain_tiles or "",
        "terrain_encoding": config.terrain_encoding or "",
        "terrain_exaggeration": (
            ""
            if config.terrain_exaggeration is None
            else str(config.terrain_exaggeration)
        ),
        "max_zoom": "" if config.max_zoom is None else str(config.max_zoom),
        "cache_dir": str(config.cache_dir),
        "cache_max_bytes": str(config.cache_max_bytes),
    }
    buffer = io.StringIO()
    parser.write(buffer)
    content = buffer.getvalue()
    if os.name == "posix":
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _resolve_template(
    template: str | None,
    *,
    key: str | None = None,
    token: str | None = None,
    label: str,
) -> str | None:
    if not template:
        return None
    if "{key}" in template:
        if not key:
            raise ValueError(f"{label} requires MAPTILER_KEY.")
        return template.format(key=key)
    if "{token}" in template:
        if not token:
            raise ValueError(f"{label} requires MAPBOX_TOKEN.")
        return template.format(token=token)
    return template


def map_config(app_cfg: AppConfig) -> MapConfig:
    provider = (app_cfg.map_provider or DEFAULT_PROVIDER).lower()
    max_zoom = app_cfg.max_zoom
    terrain_exaggeration = app_cfg.terrain_exaggeration or 1.2

    if provider == "mapbox":
        token = app_cfg.mapbox_token
        if not token:
            raise ValueError("MAPBOX_TOKEN is required when MAP_PROVIDER=mapbox.")
        style_template = app_cfg.style_url or MAPBOX_STYLE_URL
        terrain_template = app_cfg.terrain_tiles or MAPBOX_TERRAIN_TILES
        style_url = _resolve_template(style_template, token=token, label="style_url")
        terrain_tiles = _resolve_template(
            terrain_template, token=token, label="terrain_tiles"
        )
        if max_zoom is None:
            max_zoom = 18.0
        terrain_encoding = app_cfg.terrain_encoding or "mapbox"
        return MapConfig(
            style_url=style_url,
            style_attribution=None,
            raster_tiles=None,
            raster_attribution=None,
            terrain_tiles=terrain_tiles,
            terrain_attribution=None,
            terrain_encoding=terrain_encoding,
            terrain_exaggeration=terrain_exaggeration,
            max_zoom=max_zoom,
            map_provider=provider,
            mapbox_token=token,
        )

    if provider != "maptiler":
        raise ValueError("MAP_PROVIDER must be 'maptiler' or 'mapbox'.")

    key = app_cfg.maptiler_key
    if not key:
        raise ValueError("MAPTILER_KEY is required (set it via configure).")

    style_template = app_cfg.style_url or MAPTILER_STYLE
    terrain_template = app_cfg.terrain_tiles or MAPTILER_TERRAIN_TILES

    style_url = _resolve_template(style_template, key=key, label="style_url")
    terrain_tiles = _resolve_template(terrain_template, key=key, label="terrain_tiles")

    terrain_encoding = app_cfg.terrain_encoding or MAPTILER_TERRAIN_ENCODING

    return MapConfig(
        style_url=style_url,
        style_attribution=None,
        raster_tiles=None,
        raster_attribution=None,
        terrain_tiles=terrain_tiles,
        terrain_attribution=None,
        terrain_encoding=terrain_encoding,
        terrain_exaggeration=terrain_exaggeration,
        max_zoom=max_zoom,
        map_provider=provider,
        mapbox_token=None,
    )
