"""Small geospatial helpers shared by tools and routers (shapely + pyproj)."""
from __future__ import annotations

from functools import lru_cache

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

# Dubai demonstration area is in UTM zone 40N; metric operations use EPSG:32640.
METRIC_CRS = "EPSG:32640"
WGS84 = "EPSG:4326"

# Approximate bounds of the demonstration area (all synthetic assets live here).
DEMO_BOUNDS = {"minx": 55.20, "miny": 25.05, "maxx": 55.45, "maxy": 25.30}
UAE_BOUNDS = {"minx": 51.5, "miny": 22.6, "maxx": 56.4, "maxy": 26.1}


@lru_cache
def _tf(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def to_metric(geom: BaseGeometry) -> BaseGeometry:
    return shp_transform(_tf(WGS84, METRIC_CRS).transform, geom)


def to_wgs84(geom: BaseGeometry, src: str = METRIC_CRS) -> BaseGeometry:
    return shp_transform(_tf(src, WGS84).transform, geom)


def bbox_of(geojson: dict | None) -> tuple[float | None, float | None, float | None, float | None]:
    if not geojson:
        return (None, None, None, None)
    b = shape(geojson).bounds
    return (b[0], b[1], b[2], b[3])


def apply_bbox(obj, geojson: dict | None) -> None:
    obj.geometry = geojson
    obj.bbox_minx, obj.bbox_miny, obj.bbox_maxx, obj.bbox_maxy = bbox_of(geojson)


def within_bounds(geojson: dict, bounds: dict = UAE_BOUNDS) -> bool:
    minx, miny, maxx, maxy = bbox_of(geojson)
    if minx is None:
        return False
    return bounds["minx"] <= minx and maxx <= bounds["maxx"] and bounds["miny"] <= miny and maxy <= bounds["maxy"]


def validate_geometry(geojson: dict) -> list[str]:
    problems: list[str] = []
    try:
        g = shape(geojson)
    except Exception as e:  # noqa: BLE001
        return [f"invalid GeoJSON geometry: {e}"]
    if g.is_empty:
        problems.append("empty geometry")
    if not g.is_valid:
        problems.append("geometry is not valid (self-intersection or ring error)")
    if not within_bounds(geojson):
        problems.append("geometry falls outside UAE bounds")
    return problems


def area_m2(geojson: dict) -> float:
    return float(to_metric(shape(geojson)).area)


def length_m(geojson: dict) -> float:
    return float(to_metric(shape(geojson)).length)


def buffer_m(geojson: dict, metres: float) -> dict:
    return mapping(to_wgs84(to_metric(shape(geojson)).buffer(metres)))


def distance_m(a: dict, b: dict) -> float:
    return float(to_metric(shape(a)).distance(to_metric(shape(b))))


def point(lon: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [lon, lat]}


def rect(minx: float, miny: float, maxx: float, maxy: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]]}
