from __future__ import annotations

import io
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from trailgen.geo import EARTH_RADIUS_M


_TILE_SIZE = 256


def _decode_height_mapbox(r: int, g: int, b: int) -> float:
    return -10000.0 + (r * 256 * 256 + g * 256 + b) * 0.1


def _decode_height_terrarium(r: int, g: int, b: int) -> float:
    return (r * 256 + g + b / 256.0) - 32768.0


def _tile_xyz(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    )
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def _tile_pixel(lon: float, lat: float, zoom: int) -> tuple[int, int, int, int]:
    lat_rad = math.radians(lat)
    n = 2**zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    tile_x = max(0, min(n - 1, int(x)))
    tile_y = max(0, min(n - 1, int(y)))
    px = int((x - tile_x) * _TILE_SIZE)
    py = int((y - tile_y) * _TILE_SIZE)
    px = max(0, min(_TILE_SIZE - 1, px))
    py = max(0, min(_TILE_SIZE - 1, py))
    return tile_x, tile_y, px, py


def select_dem_zoom(lat: float, target_resolution_m: float = 30.0) -> int:
    meters_per_pixel = target_resolution_m
    value = (
        math.cos(math.radians(lat))
        * 2
        * math.pi
        * EARTH_RADIUS_M
        / (_TILE_SIZE * meters_per_pixel)
    )
    zoom = int(round(math.log(value, 2)))
    return max(8, min(14, zoom))


@dataclass
class TerrainSampler:
    url_template: str
    encoding: str
    cache_dir: Path
    zoom: int
    exaggeration: float = 1.0

    def __post_init__(self) -> None:
        self._encoding = (self.encoding or "mapbox").lower()
        self._cache_dir = self.cache_dir
        self._tile_cache: dict[tuple[int, int, int], Image.Image] = {}
        self._ext = self._infer_extension(self.url_template)

    def height_at(self, lon: float, lat: float) -> float | None:
        tile_x, tile_y, px, py = _tile_pixel(lon, lat, self.zoom)
        tile = self._load_tile(tile_x, tile_y)
        if tile is None:
            return None
        r, g, b = tile.getpixel((px, py))
        if self._encoding == "terrarium":
            height = _decode_height_terrarium(r, g, b)
        else:
            height = _decode_height_mapbox(r, g, b)
        return height * self.exaggeration

    def _infer_extension(self, template: str) -> str:
        match = re.search(r"\{y\}\.(\w+)", template)
        if match:
            return match.group(1)
        path = urllib.parse.urlparse(template).path
        suffix = Path(path).suffix
        if suffix:
            return suffix.lstrip(".")
        return "png"

    def _load_tile(self, x: int, y: int) -> Image.Image | None:
        key = (self.zoom, x, y)
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached

        cache_path = self._cache_dir / "terrain_rgb" / str(self.zoom) / str(x)
        cache_path.mkdir(parents=True, exist_ok=True)
        tile_path = cache_path / f"{y}.{self._ext}"
        data = None
        if tile_path.is_file():
            try:
                data = tile_path.read_bytes()
            except OSError:
                data = None

        if data is None:
            url = self.url_template.format(z=self.zoom, x=x, y=y)
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "trailgen/0.1"}
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                try:
                    tile_path.write_bytes(data)
                except OSError:
                    pass
            except Exception:
                return None

        try:
            tile = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            return None

        self._tile_cache[key] = tile
        if len(self._tile_cache) > 64:
            self._tile_cache.pop(next(iter(self._tile_cache)))
        return tile
