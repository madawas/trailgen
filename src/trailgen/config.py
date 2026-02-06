from __future__ import annotations

import os
from dataclasses import dataclass


TERRAIN_TILES = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
TERRAIN_ATTRIBUTION = "Terrain tiles from Mapzen, hosted on AWS Open Data"
MAPTILER_STYLE = "https://api.maptiler.com/maps/hybrid-v4/style.json?key={key}"

@dataclass(frozen=True)
class MapConfig:
    style_url: str | None
    style_attribution: str | None
    raster_tiles: str | None
    raster_attribution: str | None
    terrain_tiles: str | None
    terrain_attribution: str | None
    blank_style: bool = False


def map_config() -> MapConfig:
    key = os.getenv("MAPTILER_KEY")
    if not key:
        raise ValueError("MAPTILER_KEY is required (set it in .env).")
    style_url = MAPTILER_STYLE.format(key=key)
    return MapConfig(
        style_url=style_url,
        style_attribution=None,
        raster_tiles=None,
        raster_attribution=None,
        terrain_tiles=TERRAIN_TILES,
        terrain_attribution=TERRAIN_ATTRIBUTION,
    )
