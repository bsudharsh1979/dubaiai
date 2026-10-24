"""Sentinel-1 before/after change screening (baseline, documented, uncalibrated).

Input: two preprocessed, georeferenced, *calibrated* backscatter GeoTIFFs in dB
(sigma0 or gamma0, same polarisation, same relative orbit and preprocessing).
Output: a class mask preserving georeferencing and a spatial summary labelled
"candidate inundation at acquisition time".

Classes
    0  no change / dry
    1  candidate inundation (dark now, was not dark before: after < T_water and after-before < T_change)
    2  permanent water (dark in both scenes, or listed in the permanent-water mask)
    3  unknown / unreliable (nodata, shadow/layover mask, or ambiguous magnitude)

Low backscatter is *not* equated with water: pixels that were already dark, that
sit in a shadow/layover mask, or whose change is small are classed 2 or 3.  A
real segmentation model with IoU/precision/recall on labelled imagery would
replace the thresholds; until then the evaluation harness reports "not evaluated".
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine, array_bounds
from rasterio.warp import transform_bounds

TOOL_VERSION = "sar_change_screen/0.2.0"
WATER_DB = -18.0
CHANGE_DB = -3.0
AMBIGUOUS_DB = -1.5


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_pair(before_path: str, after_path: str, before_meta: dict, after_meta: dict) -> dict:
    """Validate CRS, overlap, pixel alignment, units, nodata and acquisition comparability."""
    problems: list[str] = []
    warnings: list[str] = []
    with rasterio.open(before_path) as b, rasterio.open(after_path) as a:
        if b.crs is None or a.crs is None:
            problems.append("missing CRS")
        elif b.crs != a.crs:
            problems.append(f"CRS mismatch: {b.crs} vs {a.crs}")
        if b.count != 1 or a.count != 1:
            problems.append("expected single-band backscatter rasters")
        if b.width != a.width or b.height != a.height:
            problems.append(f"shape mismatch {b.width}x{b.height} vs {a.width}x{a.height}")
        if not _affine_close(b.transform, a.transform):
            problems.append("pixel grids are not aligned (transform mismatch); resample onto a common grid first")
        if b.nodata is None or a.nodata is None:
            warnings.append("nodata not declared; NaN treated as nodata")
        try:
            bb, ab = b.bounds, a.bounds
            ix = (max(bb.left, ab.left), max(bb.bottom, ab.bottom), min(bb.right, ab.right), min(bb.top, ab.top))
            if ix[0] >= ix[2] or ix[1] >= ix[3]:
                problems.append("rasters do not overlap")
        except Exception as e:  # noqa: BLE001
            problems.append(f"bounds error: {e}")
        for tag_src, nm in ((b, "before"), (a, "after")):
            units = (tag_src.tags().get("units") or tag_src.tags().get("UNITS") or "").lower()
            if units not in {"db", "decibel"}:
                sample = tag_src.read(1, masked=True)
                if sample.count() and (sample.max() > 10 or sample.min() < -60):
                    problems.append(f"{nm}: values are not plausible dB backscatter and no units tag found")
                else:
                    warnings.append(f"{nm}: units tag missing; value range consistent with dB")
        info = {"crs": str(b.crs), "width": b.width, "height": b.height, "pixel_size_m": _pixel_size_m(b), "nodata": b.nodata}
    for key in ("orbit", "polarisation", "preprocessing"):
        if before_meta.get(key) != after_meta.get(key):
            problems.append(f"{key} differs between scenes ({before_meta.get(key)!r} vs {after_meta.get(key)!r})")
    for key in ("acquisition_at", "available_at", "source_id", "provenance_uri", "license_class"):
        for nm, m in (("before", before_meta), ("after", after_meta)):
            if not m.get(key):
                problems.append(f"{nm}: missing metadata field {key}")
    return {"ok": not problems, "problems": problems, "warnings": warnings, "raster": info, "tool_version": TOOL_VERSION}


def _affine_close(a: Affine, b: Affine, tol: float = 1e-6) -> bool:
    return all(abs(x - y) <= tol * max(1.0, abs(x)) for x, y in zip(a, b))


def _pixel_size_m(ds) -> float | None:
    t = ds.transform
    if ds.crs and ds.crs.is_projected:
        return float(abs(t.a))
    return None


def change_mask(before_path: str, after_path: str, out_path: str, permanent_water_path: str | None = None, shadow_mask_path: str | None = None) -> dict:
    with rasterio.open(before_path) as b, rasterio.open(after_path) as a:
        before = b.read(1).astype("float32")
        after = a.read(1).astype("float32")
        nod_b = b.nodata if b.nodata is not None else np.nan
        nod_a = a.nodata if a.nodata is not None else np.nan
        invalid = np.isnan(before) | np.isnan(after)
        if not np.isnan(nod_b):
            invalid |= before == nod_b
        if not np.isnan(nod_a):
            invalid |= after == nod_a
        profile = a.profile.copy()
        transform, crs = a.transform, a.crs
        pixel_area_m2 = (abs(transform.a) * abs(transform.e)) if crs and crs.is_projected else None

    diff = after - before
    dark_after = after < WATER_DB
    dark_before = before < WATER_DB
    permanent = dark_after & dark_before
    if permanent_water_path:
        with rasterio.open(permanent_water_path) as p:
            permanent |= p.read(1) > 0
    unreliable = invalid.copy()
    if shadow_mask_path:
        with rasterio.open(shadow_mask_path) as s:
            unreliable |= s.read(1) > 0
    candidate = dark_after & (diff < CHANGE_DB) & ~permanent & ~unreliable
    ambiguous = dark_after & (diff >= CHANGE_DB) & (diff < AMBIGUOUS_DB) & ~permanent & ~unreliable

    cls = np.zeros(after.shape, dtype="uint8")
    cls[candidate] = 1
    cls[permanent] = 2
    cls[unreliable | ambiguous] = 3

    profile.update(dtype="uint8", count=1, nodata=255, compress="deflate")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(cls, 1)
        dst.update_tags(classes="0=no_change,1=candidate_inundation,2=permanent_water,3=unknown", tool_version=TOOL_VERSION,
                        label="candidate inundation at acquisition time", thresholds=f"water<{WATER_DB}dB change<{CHANGE_DB}dB")

    total = cls.size
    counts = {int(k): int((cls == k).sum()) for k in range(4)}
    summary = {"pixels": counts, "fractions": {k: round(v / total, 4) for k, v in counts.items()}}
    if pixel_area_m2:
        summary["area_m2"] = {k: round(v * pixel_area_m2, 1) for k, v in counts.items()}
    bounds_wgs84 = None
    cand_bounds = None
    try:
        bounds_wgs84 = transform_bounds(crs, "EPSG:4326", *array_bounds(cls.shape[0], cls.shape[1], transform), densify_pts=4)
        ys, xs = np.where(cls == 1)
        if len(xs):
            x0, y0 = rasterio.transform.xy(transform, ys.max() + 1, xs.min(), offset="ul")
            x1, y1 = rasterio.transform.xy(transform, ys.min(), xs.max() + 1, offset="ul")
            cand_bounds = transform_bounds(crs, "EPSG:4326", min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), densify_pts=4)
    except Exception:  # noqa: BLE001
        pass
    unknown_frac = summary["fractions"][3]
    quality = "poor" if unknown_frac > 0.4 else "fair" if unknown_frac > 0.15 else "good"
    return {"tool_version": TOOL_VERSION, "label": "candidate inundation at acquisition time", "mask_path": out_path, "crs": str(crs),
            "summary": summary, "footprint_wgs84": bounds_wgs84, "candidate_bounds_wgs84": cand_bounds,
            "unknown_fraction": unknown_frac, "evidence_quality": quality,
            "thresholds": {"water_db": WATER_DB, "change_db": CHANGE_DB, "ambiguous_db": AMBIGUOUS_DB},
            "caveats": ["Thresholds are a documented baseline; no labelled accuracy has been established (not evaluated).",
                        "Candidate class cannot establish depth or flow; satellite scenes are intermittent evidence.",
                        "Low backscatter can also be smooth tarmac, sand or shadow; see unknown class."]}


def write_synthetic_pair(out_dir: str | Path, size: int = 128, pixel_m: float = 10.0, origin_xy: tuple[float, float] = (322000.0, 2790000.0),
                         flood_fraction: float = 0.12, seed: int = 7, crs: str = "EPSG:32640") -> dict:
    """Explicitly synthetic test fixture: urban-like clutter, a permanent lake, a shadow strip and a flooded patch."""
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = rng.normal(-9.0, 2.0, (size, size)).astype("float32")
    lake = np.zeros((size, size), dtype=bool)
    lake[int(size * 0.7):, : int(size * 0.25)] = True
    base[lake] = rng.normal(-22.0, 1.0, lake.sum())
    after = base + rng.normal(0.0, 0.7, (size, size)).astype("float32")
    r = int(size * (flood_fraction ** 0.5))
    y0, x0 = int(size * 0.3), int(size * 0.45)
    flood = np.zeros((size, size), dtype=bool)
    flood[y0:y0 + r, x0:x0 + r] = True
    after[flood] = rng.normal(-21.0, 1.0, flood.sum())
    shadow = np.zeros((size, size), dtype=bool)
    shadow[:, int(size * 0.9):] = True
    before_nd = base.copy()
    before_nd[:4, :] = -9999.0
    after_nd = after.copy()
    after_nd[:4, :] = -9999.0
    transform = Affine(pixel_m, 0, origin_xy[0], 0, -pixel_m, origin_xy[1] + size * pixel_m)
    profile = {"driver": "GTiff", "dtype": "float32", "count": 1, "width": size, "height": size, "crs": crs, "transform": transform, "nodata": -9999.0}
    paths = {}
    for name, arr in (("before", before_nd), ("after", after_nd)):
        p = out_dir / f"synthetic_s1_{name}.tif"
        with rasterio.open(p, "w", **profile) as dst:
            dst.write(arr, 1)
            dst.update_tags(units="dB", synthetic="true", description="SYNTHETIC fixture — not real Sentinel-1 data")
        paths[name] = str(p)
    mprof = dict(profile, dtype="uint8", nodata=255)
    for name, arr in (("permanent_water", lake), ("shadow", shadow), ("truth_flood", flood)):
        p = out_dir / f"synthetic_s1_{name}.tif"
        with rasterio.open(p, "w", **mprof) as dst:
            dst.write(arr.astype("uint8"), 1)
            dst.update_tags(synthetic="true")
        paths[name] = str(p)
    return paths
