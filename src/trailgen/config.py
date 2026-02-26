from __future__ import annotations

import os
from dataclasses import dataclass


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


def _env_float(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"Invalid {name}: {value!r}") from None


def map_config() -> MapConfig:
    provider = os.getenv("MAP_PROVIDER", "maptiler").lower()
    max_zoom = _env_float("MAP_MAX_ZOOM")
    terrain_exaggeration = (
        _env_float("MAP_TERRAIN_EXAGGERATION")
        or _env_float("TERRAIN_EXAGGERATION")
        or 1.2
    )

    if provider == "mapbox":
        token = os.getenv("MAPBOX_TOKEN")
        if not token:
            raise ValueError("MAPBOX_TOKEN is required when MAP_PROVIDER=mapbox.")
        style_url = os.getenv("MAPBOX_STYLE_URL", MAPBOX_STYLE_URL).format(token=token)
        terrain_tiles = os.getenv("MAPBOX_TERRAIN_TILES", MAPBOX_TERRAIN_TILES).format(
            token=token
        )
        if max_zoom is None:
            max_zoom = 18.0
        return MapConfig(
            style_url=style_url,
            style_attribution=None,
            raster_tiles=None,
            raster_attribution=None,
            terrain_tiles=terrain_tiles,
            terrain_attribution=None,
            terrain_encoding="mapbox",
            terrain_exaggeration=terrain_exaggeration,
            max_zoom=max_zoom,
            map_provider=provider,
            mapbox_token=token,
        )

    if provider != "maptiler":
        raise ValueError("MAP_PROVIDER must be 'maptiler' or 'mapbox'.")

    key = os.getenv("MAPTILER_KEY")
    if not key:
        raise ValueError("MAPTILER_KEY is required (set it in .env).")
    style_url = MAPTILER_STYLE.format(key=key)
    return MapConfig(
        style_url=style_url,
        style_attribution=None,
        raster_tiles=None,
        raster_attribution=None,
        terrain_tiles=MAPTILER_TERRAIN_TILES.format(key=key),
        terrain_attribution=None,
        terrain_encoding=MAPTILER_TERRAIN_ENCODING,
        terrain_exaggeration=terrain_exaggeration,
        max_zoom=max_zoom,
        map_provider=provider,
        mapbox_token=None,
    )
