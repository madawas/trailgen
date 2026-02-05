from __future__ import annotations

import os
from dataclasses import dataclass


TERRAIN_TILES = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
TERRAIN_ATTRIBUTION = "Terrain tiles from Mapzen, hosted on AWS Open Data"

@dataclass(frozen=True)
class MapConfig:
    style_url: str | None
    style_attribution: str | None
    raster_tiles: str | None
    raster_attribution: str | None
    terrain_tiles: str | None
    terrain_attribution: str | None
    blank_style: bool = False


def map_config(provider: str) -> MapConfig:
    provider = provider.lower().replace("_", "-")

    if provider == "auto":
        if os.getenv("MAPTILER_KEY"):
            provider = "maptiler"
        else:
            provider = "flat"

    if provider == "maptiler":
        key = os.getenv("MAPTILER_KEY")
        if not key:
            raise ValueError("MAPTILER_KEY is required for maptiler provider")
        style_url = f"https://api.maptiler.com/maps/topo/style.json?key={key}"
        return MapConfig(
            style_url=style_url,
            style_attribution=None,
            raster_tiles=None,
            raster_attribution=None,
            terrain_tiles=TERRAIN_TILES,
            terrain_attribution=TERRAIN_ATTRIBUTION,
        )

    if provider == "maptiler-satellite":
        key = os.getenv("MAPTILER_KEY")
        if not key:
            raise ValueError("MAPTILER_KEY is required for maptiler-satellite provider")
        style_url = f"https://api.maptiler.com/maps/satellite/style.json?key={key}"
        return MapConfig(
            style_url=style_url,
            style_attribution=None,
            raster_tiles=None,
            raster_attribution=None,
            terrain_tiles=TERRAIN_TILES,
            terrain_attribution=TERRAIN_ATTRIBUTION,
        )

    if provider == "flat":
        return MapConfig(
            style_url=None,
            style_attribution=None,
            raster_tiles=None,
            raster_attribution=None,
            terrain_tiles=None,
            terrain_attribution=None,
            blank_style=True,
        )

    raise ValueError(f"Unknown map provider: {provider}")
