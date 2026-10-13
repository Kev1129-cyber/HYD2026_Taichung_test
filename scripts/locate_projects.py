"""Place the major projects (data/raw/shuinan_major_projects_2026.csv) on the map.

Each project tries its rules in order and keeps the first that resolves:
  osm           a named OpenStreetMap feature (data/derived/landmarks_osm.geojson),
                filtered by the tags that fit the project (a building, a station,
                a park polygon) so that bus stops sharing the name are skipped;
  intersection  a road junction named in an official document, found in the OSM
                road network (data/derived/roads_osm.geojson);
  plan_block    a block of the traced detailed plan matched by area
                (data/derived/shuinan_detailed_plan_traced.geojson);
  ref           a published coordinate from data/raw/reference_points.csv.
Projects with no location (park-wide figures) are listed without a point.

Writes data/derived/project_locations.geojson. Standard library only.
"""

import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "data" / "raw" / "shuinan_major_projects_2026.csv"
REFS = ROOT / "data" / "raw" / "reference_points.csv"
LANDMARKS = ROOT / "data" / "derived" / "landmarks_osm.geojson"
ROADS = ROOT / "data" / "derived" / "roads_osm.geojson"
PLAN = ROOT / "data" / "derived" / "shuinan_detailed_plan_traced.geojson"
OUT = ROOT / "data" / "derived" / "project_locations.geojson"


def is_building(t):
    return any(k in t for k in ("building", "tourism", "amenity", "construction", "landuse")) and \
        t.get("highway") != "bus_stop" and t.get("public_transport") not in ("platform", "stop_position")


def is_bus_station(t):
    return t.get("amenity") == "bus_station" or (t.get("public_transport") == "station" and t.get("bus") == "yes") \
        or "building" in t


def is_rail_station(t):
    return t.get("railway") == "station" or (t.get("public_transport") == "station" and t.get("railway") != "platform")


def is_park(t):
    return t.get("leisure") == "park"


def is_site(t):
    return is_building(t) or is_park(t)


RULES = {
    "臺中綠美圖": [
        ("osm", r"綠美圖", is_site),  # OSM maps the grounds as a park polygon
        ("ref", "museumbrary"),
    ],
    "臺中國際會展中心": [
        ("osm", r"國際會展中心", is_building),
        ("ref", "exhibition"),
    ],
    "水湳轉運中心": [
        ("osm", r"水湳轉運", is_bus_station),
    ],
    "臺中流行影音中心（原中臺灣電影中心）": [
        ("osm", r"流行影音中心|中臺灣電影中心|中台灣電影中心", is_building),
        ("intersection", ("經貿路一段", "經貿一路"),
         "Taichung City Government News Bureau, council report 2024-08-21: at the corner of "
         "Jingmao Road Sec. 1 (經貿路一段) and Jingmao 1st Road (經貿一路)"),
    ],
    "臺中超巨蛋": [
        # OSM maps the BOT site in parts; they are merged. The city puts the site on
        # Innovation R&D Special Zone 1 (創研一), about 16.35 ha.
        ("osm", r"超巨蛋", is_site),
    ],
    "中央公園": [
        ("osm", r"^(臺中|台中)?中央公園$", is_park),
        ("plan_block", "AUTO_GREEN", "Largest park patch of the traced detailed plan"),
    ],
    "捷運綠線文華高中站": [
        ("osm", r"文華高中", is_rail_station),
        ("ref", "wenhua_station"),
    ],
    "園區停車供給": [],
}


def ring_area_centroid(ring):
    """Area (m^2) and centroid of a lon/lat ring, planar at its own latitude."""
    lat0 = sum(p[1] for p in ring) / len(ring)
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110574
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-15:
        return 0.0, ring[0]
    return abs(a) / 2 * kx * ky, [cx / (3 * a), cy / (3 * a)]


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def names(tags):
    return [tags.get(k, "") for k in ("name", "name:zh", "name:zh-Hant", "official_name", "alt_name", "old_name")]


def resolve_osm(landmarks, pattern, accept):
    if not landmarks:
        return None
    rx = re.compile(pattern)
    hits = [f for f in landmarks["features"]
            if any(rx.search(n) for n in names(f["properties"]["tags"])) and accept(f["properties"]["tags"])]
    if not hits:
        return None
    # prefer polygons (footprints), then the largest one
    hits.sort(key=lambda f: (f["geometry"]["type"] in ("Polygon", "MultiPolygon"), f["properties"].get("area_m2") or 0),
              reverse=True)
    f = hits[0]
    p = f["properties"]
    if f["geometry"]["type"] not in ("Polygon", "MultiPolygon"):
        return {"lonlat": p["centroid"], "footprint": None, "method": "osm",
                "source": f"OpenStreetMap {p['osm_type']} {p['osm_id']} ({p['tags'].get('name', '')})",
                "osm": f"https://www.openstreetmap.org/{p['osm_type']}/{p['osm_id']}"}
    # a site mapped in several polygons under one name is merged into one footprint
    same = [h for h in hits if h["geometry"]["type"] in ("Polygon", "MultiPolygon")
            and h["properties"]["tags"].get("name") == p["tags"].get("name")]
    polys = []
    for h in same:
        polys += [h["geometry"]["coordinates"]] if h["geometry"]["type"] == "Polygon" else h["geometry"]["coordinates"]
    parts = [ring_area_centroid(poly[0][:-1]) for poly in polys]
    total = sum(a for a, _ in parts) or 1.0
    lon = sum(a * c[0] for a, c in parts) / total
    lat = sum(a * c[1] for a, c in parts) / total
    ids = ", ".join(f"{h['properties']['osm_type']} {h['properties']['osm_id']}" for h in same)
    return {
        "lonlat": [round(lon, 7), round(lat, 7)], "footprint": polys if len(polys) > 1 else polys[0],
        "footprint_multi": len(polys) > 1, "area_ha": round(total / 1e4, 2), "method": "osm",
        "source": f"OpenStreetMap {ids} ({p['tags'].get('name', '')})",
        "osm": f"https://www.openstreetmap.org/{p['osm_type']}/{p['osm_id']}",
    }


def segment_intersection(p1, p2, p3, p4):
    d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
    if abs(d) < 1e-18:
        return None
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    if 0 <= t <= 1 and 0 <= u <= 1:
        return [p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])]
    return None


def resolve_intersection(roads, pair, source):
    if not roads:
        return None
    a_name, b_name = pair
    ways_a = [f["geometry"]["coordinates"] for f in roads["features"] if f["properties"].get("name") == a_name]
    ways_b = [f["geometry"]["coordinates"] for f in roads["features"] if f["properties"].get("name") == b_name]
    if not ways_a or not ways_b:
        return None
    hits = []
    for wa in ways_a:
        for wb in ways_b:
            for p1, p2 in zip(wa, wa[1:]):
                for p3, p4 in zip(wb, wb[1:]):
                    x = segment_intersection(p1, p2, p3, p4)
                    if x:
                        hits.append(x)
    if not hits:
        # T-junctions: an end of one way lies on (or within ~8 m of) the other
        kx, ky = 101606.0, 110761.0
        best = None
        for wa in ways_a:
            for wb in ways_b:
                for end in (wb[0], wb[-1]):
                    for p1, p2 in zip(wa, wa[1:]):
                        dx, dy = (p2[0] - p1[0]) * kx, (p2[1] - p1[1]) * ky
                        L2 = dx * dx + dy * dy or 1e-9
                        t = max(0.0, min(1.0, ((end[0] - p1[0]) * kx * dx + (end[1] - p1[1]) * ky * dy) / L2))
                        q = [p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])]
                        dist = math.hypot((q[0] - end[0]) * kx, (q[1] - end[1]) * ky)
                        if dist < 8 and (best is None or dist < best[0]):
                            best = (dist, q)
        if best:
            hits.append(best[1])
    if not hits:
        return None
    lon = sum(h[0] for h in hits) / len(hits)
    lat = sum(h[1] for h in hits) / len(hits)
    return {"lonlat": [round(lon, 7), round(lat, 7)], "footprint": None, "method": "intersection",
            "source": f"{source}; junction located in the OSM road network"}


def resolve_plan_block(plan, layer, source):
    if not plan:
        return None
    blocks = [f for f in plan["features"] if f["properties"]["source_layer"] == layer]
    if not blocks:
        return None
    scored = [(ring_area_centroid(f["geometry"]["coordinates"][0][:-1]), f) for f in blocks]
    (area, c), f = max(scored, key=lambda s: s[0][0])
    return {"lonlat": [round(c[0], 7), round(c[1], 7)], "footprint": f["geometry"]["coordinates"],
            "area_ha": round(area / 1e4, 1), "method": "plan_block", "source": f"{source} (traced block {area / 1e4:.1f} ha)"}


def resolve_ref(refs, ref_id):
    r = refs.get(ref_id)
    if not r:
        return None
    return {"lonlat": [float(r["lon"]), float(r["lat"])], "footprint": None, "method": "ref", "source": r["source"]}


def main():
    landmarks, roads, plan = load(LANDMARKS), load(ROADS), load(PLAN)
    with REFS.open(encoding="utf-8-sig", newline="") as f:
        refs = {r["id"]: r for r in csv.DictReader(f)}
    with PROJECTS.open(encoding="utf-8-sig", newline="") as f:
        projects = list(csv.DictReader(f))

    features = []
    for i, p in enumerate(projects, start=1):
        loc = None
        for rule in RULES.get(p["project_zh"], []):
            kind = rule[0]
            if kind == "osm":
                loc = resolve_osm(landmarks, rule[1], rule[2])
            elif kind == "intersection":
                loc = resolve_intersection(roads, rule[1], rule[2])
            elif kind == "plan_block":
                loc = resolve_plan_block(plan, rule[1], rule[2])
            elif kind == "ref":
                loc = resolve_ref(refs, rule[1])
            if loc:
                break
        props = {"n": i, "project_zh": p["project_zh"], "project_en": p["project_en"]}
        if loc:
            props.update({k: v for k, v in loc.items() if k not in ("lonlat",) and v is not None})
            geom = {"type": "Point", "coordinates": [round(loc["lonlat"][0], 7), round(loc["lonlat"][1], 7)]}
        else:
            props["method"] = "none"
            props["source"] = "Park-wide figure with no single location" if not RULES.get(p["project_zh"]) \
                else "No location found"
            geom = None
        features.append({"type": "Feature", "properties": props, "geometry": geom})
        where = geom["coordinates"] if geom else "-"
        print(f"{i}. {p['project_zh']}: {props['method']} {where}  ({props['source'][:80]})")

    out = {"type": "FeatureCollection", "name": "project_locations",
           "landmarks_fetched": landmarks.get("fetched") if landmarks else None, "features": features}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
