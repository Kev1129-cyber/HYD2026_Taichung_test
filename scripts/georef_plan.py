"""Georeference the traced Shuinan detailed plan (Figure 7-1 DXF) onto WGS84.

The DXF is drawn on an A3 sheet in millimetres and carries no coordinate
reference (its $LATITUDE/$LONGITUDE header values are AutoCAD's San Francisco
defaults). This script places it with a similarity transform

    ground metres = SCALE * drawing mm  (+ rotation)  + translation

where
  * SCALE comes from the zone areas: the traced patches of the five land-use
    special zones, de-overlapped, measure 7,906 mm^2 on the sheet against
    126.53 ha in the plan's area table, i.e. ~12.65 m/mm (12.24-12.87 per zone);
    traced outlines run slightly inside the true edges, so 12.5 m/mm is used;
  * ROTATION is 0 (north up): runway 18/36 of the former airport ran 175-355
    degrees, and the park that replaced it runs straight up the sheet;
  * the translation is a weighted fit to two control points (see CONTROL).

Expect errors of roughly 100-200 m. The map page lets a viewer drag, rotate
and scale the overlay against the OpenStreetMap basemap and copy the corrected
parameters, which can be pasted back into CONTROL / SCALE / ROTATION_DEG.

Usage:
    python3 scripts/georef_plan.py   # writes data/derived/shuinan_detailed_plan_traced.geojson

Standard library only (a minimal reader for the DXF's LWPOLYLINE entities).
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DXF = ROOT / "data" / "raw" / "Figure_7-1_Detailed_Plan_A3_English_CAD.dxf"
OUT = ROOT / "data" / "derived" / "shuinan_detailed_plan_traced.geojson"

# Local tangent plane used for the fit: ground metres per degree at 24.185 N (WGS84).
LON0, LAT0 = 120.654, 24.185
M_PER_DEG_LON = 101606.0
M_PER_DEG_LAT = 110761.0

SCALE = 12.5          # ground metres per drawing millimetre
ROTATION_DEG = 0.0    # counter-clockwise, drawing -> ground

# (drawing x mm, drawing y mm), (lon, lat), weight, description
CONTROL = [
    ((158.0, 221.0), (120.6523765, 24.1929213), 2.0,
     "Taichung Green Museumbrary (Chinese Wikipedia) at the north end of the traced Central Park"),
    ((175.0, 115.0), (120.6541, 24.1820), 1.0,
     "Mean centre of two Central Park no-fly zones in Taichung City notices, on the park's wide lawn"),
]

# Traced colour layers -> likely land-use class. The first five are matched by
# area against the plan's table (each lands within 7% at 12.5 m/mm); park,
# drainage and the blue patches follow the usual colour conventions only.
CLASSES = {
    "AUTO_PALE_YELLOW": "eco_res", "AUTO_YELLOW": "eco_res", "AUTO_ORANGE": "eco_res",
    "AUTO_MAGENTA": "cult_comm",
    "AUTO_PURPLE": "innov",
    "AUTO_PINK": "econ", "AUTO_RED": "econ", "AUTO_PEACH": "econ",
    "AUTO_LIGHT_PURPLE": "cult_edu",
    "AUTO_GREEN": "park",
    "AUTO_CYAN": "drain",
    "AUTO_BLUE": "other",
}
CLASS_INFO = {
    "eco_res": ("Ecological residential special zone", "生態住宅專用區", "#f2d43a", True),
    "cult_comm": ("Cultural and commercial special zone", "文化商業專用區", "#d14fa8", True),
    "innov": ("Innovation and R&D special zone", "創新研發專用區", "#8e5cc4", True),
    "econ": ("Economic and trade special zone", "經貿專用區", "#e8707f", True),
    "cult_edu": ("Cultural and educational zone", "文教區", "#c9b3e6", True),
    "park": ("Park and green space", "公園、綠地", "#7cc47c", False),
    "drain": ("Drainage channel site", "排水道用地", "#50c8d8", False),
    "other": ("Other public facility (blue in source)", "其他公共設施（原圖藍色）", "#4070e0", False),
}
LAYER_COLOR = {
    "AUTO_PALE_YELLOW": "#f6efa0", "AUTO_YELLOW": "#f2d43a", "AUTO_ORANGE": "#f0a030",
    "AUTO_MAGENTA": "#d14fa8", "AUTO_PURPLE": "#8e5cc4", "AUTO_PINK": "#f2a0b8",
    "AUTO_RED": "#e04040", "AUTO_PEACH": "#f5c6a0", "AUTO_LIGHT_PURPLE": "#c9b3e6",
    "AUTO_GREEN": "#7cc47c", "AUTO_CYAN": "#50c8d8", "AUTO_BLUE": "#4070e0",
}


def read_lwpolylines(path):
    """Yield (layer, closed, [(x, y), ...]) for every LWPOLYLINE in the ENTITIES section."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pairs = [(lines[i].strip(), lines[i + 1].rstrip("\r")) for i in range(0, len(lines) - 1, 2)]
    in_entities = False
    current = None
    for code, value in pairs:
        if code == "2" and value == "ENTITIES":
            in_entities = True
            continue
        if not in_entities:
            continue
        if code == "0":
            if current and current["type"] == "LWPOLYLINE":
                yield current["layer"], current["closed"], current["pts"]
            if value == "ENDSEC":
                return
            current = {"type": value, "layer": "", "closed": False, "pts": [], "x": None}
        elif current is not None and current["type"] == "LWPOLYLINE":
            if code == "8":
                current["layer"] = value
            elif code == "70":
                current["closed"] = bool(int(value) & 1)
            elif code == "10":
                current["x"] = float(value)
            elif code == "20" and current["x"] is not None:
                current["pts"].append((current["x"], float(value)))
                current["x"] = None


def fit_translation():
    c, s = math.cos(math.radians(ROTATION_DEG)), math.sin(math.radians(ROTATION_DEG))
    tx = ty = wsum = 0.0
    for (dx, dy), (lon, lat), w, _ in CONTROL:
        gx, gy = (lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT
        rx, ry = SCALE * (c * dx - s * dy), SCALE * (s * dx + c * dy)
        tx += w * (gx - rx)
        ty += w * (gy - ry)
        wsum += w
    return tx / wsum, ty / wsum


def main():
    tx, ty = fit_translation()
    c, s = math.cos(math.radians(ROTATION_DEG)), math.sin(math.radians(ROTATION_DEG))

    def to_lonlat(x, y):
        gx = SCALE * (c * x - s * y) + tx
        gy = SCALE * (s * x + c * y) + ty
        return [round(LON0 + gx / M_PER_DEG_LON, 7), round(LAT0 + gy / M_PER_DEG_LAT, 7)]

    residuals = []
    for (dx, dy), (lon, lat), w, desc in CONTROL:
        plon, plat = to_lonlat(dx, dy)
        residuals.append({
            "description": desc, "drawing_mm": [dx, dy], "lon": lon, "lat": lat, "weight": w,
            "residual_m": [round((lon - plon) * M_PER_DEG_LON, 1), round((lat - plat) * M_PER_DEG_LAT, 1)],
        })

    features = []
    for layer, closed, pts in read_lwpolylines(DXF):
        cls = CLASSES.get(layer)
        if not cls or not closed or len(pts) < 3:
            continue  # sheet frame, image frame and anything unclassified
        ring = [to_lonlat(x, y) for x, y in pts]
        ring.append(ring[0])
        en, zh, _, matched = CLASS_INFO[cls]
        features.append({
            "type": "Feature",
            "properties": {
                "class": cls, "class_en": en, "class_zh": zh, "matched_by_area": matched,
                "source_layer": layer, "fill": LAYER_COLOR[layer],
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })

    lons = [p[0] for f in features for p in f["geometry"]["coordinates"][0]]
    lats = [p[1] for f in features for p in f["geometry"]["coordinates"][0]]
    out = {
        "type": "FeatureCollection",
        "name": "shuinan_detailed_plan_traced",
        "georeference": {
            "status": "approximate: expect errors of roughly 100-200 m",
            "source": "Figure 7-1 Detailed Plan after the Second Comprehensive Review (English reference, unofficial), "
                      "auto-traced colour patches; the Chinese plan and authoritative GIS/CAD data prevail",
            "method": "similarity transform; scale from zone areas, rotation from the north-south runway, "
                      "translation fitted to control points",
            "local_origin": [LON0, LAT0],
            "m_per_deg": [M_PER_DEG_LON, M_PER_DEG_LAT],
            "scale_m_per_mm": SCALE,
            "rotation_deg": ROTATION_DEG,
            "translation_m": [round(tx, 2), round(ty, 2)],
            "control_points": residuals,
            "bbox": [min(lons), min(lats), max(lons), max(lats)],
        },
        "classes": {k: {"en": v[0], "zh": v[1], "swatch": v[2], "matched_by_area": v[3]} for k, v in CLASS_INFO.items()},
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(features)} patches, bbox {out['georeference']['bbox']}")
    for r in residuals:
        print(f"  control residual {r['residual_m']} m  ({r['description'][:48]}...)")


if __name__ == "__main__":
    main()
