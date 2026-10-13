"""Fetch the road and rail network for the study area from OpenStreetMap.

Queries the Overpass API for
  * major roads (motorway to tertiary, with their links) across the Xitun and
    Beitun bounding box, plus rail, metro and light rail;
  * minor streets (residential, unclassified, living street, service roads
    excluded) only around the Shuinan site, where the plan overlay needs them;
simplifies each line (Douglas-Peucker, 2.5 m) and writes
data/derived/roads_osm.geojson.

Run it wherever Overpass is reachable, e.g. the "Fetch OSM road network"
GitHub Actions workflow, then rebuild with scripts/build_map.py.

Data (c) OpenStreetMap contributors, available under the Open Database
License (ODbL) 1.0: https://www.openstreetmap.org/copyright

Standard library only.
"""

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "derived" / "roads_osm.geojson"

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "HYD2026_Taichung base map (https://github.com/yunching0513/HYD2026_Taichung)"

# (south, west, north, east): the two districts, padded by ~500 m
STUDY_BBOX = (24.150, 120.579, 24.224, 120.807)
# around the Shuinan site (traced plan bbox, padded by ~800 m)
SITE_BBOX = (24.166, 120.629, 24.206, 120.669)

MAJOR = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link"
MINOR = "residential|unclassified|living_street"
RAIL = "rail|subway|light_rail"

TOLERANCE_M = 2.5


def bbox(b):
    return ",".join(str(v) for v in b)


QUERY = f"""
[out:json][timeout:180];
(
  way["highway"~"^({MAJOR})$"]({bbox(STUDY_BBOX)});
  way["highway"~"^({MINOR})$"]({bbox(SITE_BBOX)});
  way["railway"~"^({RAIL})$"]({bbox(STUDY_BBOX)});
);
out tags geom;
"""


def overpass(query):
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for attempt in range(3):
        for url in ENDPOINTS:
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=240) as resp:
                    return json.load(resp), url
            except Exception as err:  # try the next mirror, then back off
                last = err
                print(f"  {url}: {err}")
        time.sleep(10 * (attempt + 1))
    raise SystemExit(f"Overpass failed: {last}")


def simplify(pts, tol):
    """Douglas-Peucker on [lon, lat] points, tolerance in metres."""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(sum(p[1] for p in pts) / len(pts))
    kx, ky = 111320 * math.cos(lat0), 110574
    xy = [(p[0] * kx, p[1] * ky) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, idx = 0.0, None
        for k in range(i + 1, j):
            d = abs(dy * (xy[k][0] - x1) - dx * (xy[k][1] - y1)) / norm
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def kind_of(tags):
    if "railway" in tags:
        return "metro" if tags["railway"] in ("subway", "light_rail") else "rail"
    hw = tags["highway"]
    base = hw.replace("_link", "")
    if base in ("motorway", "trunk"):
        kind = base
    elif base in ("primary", "secondary", "tertiary"):
        kind = base
    else:
        kind = "minor"
    return kind + ("_link" if hw.endswith("_link") else "")


def main():
    print("querying Overpass ...")
    result, used = overpass(QUERY)
    features = []
    npts = 0
    for el in result.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        tags = el.get("tags", {})
        coords = [[round(g["lon"], 6), round(g["lat"], 6)] for g in el["geometry"]]
        coords = [[round(x, 5), round(y, 5)] for x, y in simplify(coords, TOLERANCE_M)]
        if len(coords) < 2:
            continue
        props = {"kind": kind_of(tags), "osm_id": el["id"]}
        for key, out in (("name", "name"), ("name:en", "name_en"), ("ref", "ref")):
            if tags.get(key):
                props[out] = tags[key]
        if tags.get("bridge") == "yes" or tags.get("layer", "0").lstrip("-").isdigit() and int(tags.get("layer", "0")) > 0:
            props["elevated"] = True
        if tags.get("tunnel") == "yes":
            props["tunnel"] = True
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": "LineString", "coordinates": coords}})
        npts += len(coords)

    out = {
        "type": "FeatureCollection",
        "name": "roads_osm",
        "attribution": "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "osm_base": result.get("osm3s", {}).get("timestamp_osm_base"),
        "endpoint": used,
        "query": QUERY.strip(),
        "simplify_tolerance_m": TOLERANCE_M,
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kinds = {}
    for f in features:
        kinds[f["properties"]["kind"]] = kinds.get(f["properties"]["kind"], 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)}: {len(features)} ways, {npts} points, "
          f"{OUT.stat().st_size / 1024:.0f} KB  {kinds}")


if __name__ == "__main__":
    main()
