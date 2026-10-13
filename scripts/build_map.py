"""Build the static site: the landing page (index.html) and the base map (map/index.html).

Reads the district and village GeoJSON plus the two Shuinan CSV tables from
data/raw, fills templates/index.html and templates/basemap.html, and writes
self-contained HTML pages ready for GitHub Pages (deploy from branch, root).

Usage:
    python3 scripts/build_map.py                     # writes index.html and map/index.html
    python3 scripts/build_map.py --fragment out.html # also writes a body-only map fragment
                                                     # without the OSM basemap (for Artifact publish)

Standard library only.
"""

import argparse
import csv
import html
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TEMPLATES = ROOT / "templates"
MAP_OUT = ROOT / "map" / "index.html"
LANDING_OUT = ROOT / "index.html"

DISTRICTS = RAW / "context_xitun_beitun_districts.geojson"
VILLAGES = RAW / "context_xitun_beitun_villages.geojson"
ZONING = RAW / "shuinan_zoning_areas_2024.csv"
PROJECTS = RAW / "shuinan_major_projects_2026.csv"
REFS = RAW / "reference_points.csv"
PLAN_DXF = RAW / "Figure_7-1_Detailed_Plan_A3_English_CAD.dxf"
# Georeferenced trace of the detailed plan; regenerate with scripts/georef_plan.py.
PLAN = ROOT / "data" / "derived" / "shuinan_detailed_plan_traced.geojson"

# Status chip per project, keyed by project_zh in shuinan_major_projects_2026.csv:
# "open" = opened / in use / in service / existing, "pending" = not yet open.
# This grouping is ours, read from status_en; unlisted projects show "unknown".
PROJECT_PHASE = {
    "臺中綠美圖": "open",
    "臺中國際會展中心": "open",
    "水湳轉運中心": "open",
    "臺中流行影音中心（原中臺灣電影中心）": "pending",
    "臺中超巨蛋": "pending",
    "中央公園": "open",
    "捷運綠線文華高中站": "open",
    "園區停車供給": "open",
}

UNOFFICIAL = re.compile(r"\s*\(unofficial translation\)\s*$", re.I)

# Landing-page download table: (file, description).
DOWNLOADS = [
    (DISTRICTS, "西屯區、北屯區區界"),
    (VILLAGES, "西屯區、北屯區81個里界"),
    (ZONING, "水湳機場原址細部計畫土地使用分區面積（2024）"),
    (PROJECTS, "水湳經貿園區重大建設進度（2026）"),
    (PLAN, "細部計畫描圖（已概略定位，誤差約100–200公尺）"),
    (PLAN_DXF, "細部計畫圖英文參考版CAD（A3圖紙座標，未定位）"),
    (REFS, "參考點座標與出處"),
]

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def read_csv(path):
    # utf-8-sig: the source CSVs are saved with a byte-order mark (Excel-friendly).
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_data():
    districts = read_json(DISTRICTS)
    villages = read_json(VILLAGES)

    zoning = []
    for row in read_csv(ZONING):
        zoning.append({
            "zh": row["zone_zh"],
            "en": row["zone_en"],
            "ha": float(row["area_ha"]),
            "pct": float(row["share_of_plan_area_pct"]),
            "source": row["source"],
        })

    projects = []
    for row in read_csv(PROJECTS):
        en = row["project_en"]
        projects.append({
            "zh": row["project_zh"],
            # "(unofficial translation)" becomes a flag so the English name reads cleanly
            "en": UNOFFICIAL.sub("", en),
            "en_unofficial": bool(UNOFFICIAL.search(en)),
            "status": row["status_en"],
            "figures": row["key_figures_en"],
            "phase": PROJECT_PHASE.get(row["project_zh"], "unknown"),
            "source": row["source"],
        })

    # Drop properties the page never reads to keep the inline payload small.
    keep_v = ("village_code", "village_zh", "village_en", "district_code",
              "district_zh", "district_en", "area_km2", "label_lon", "label_lat")
    keep_d = ("district_code", "district_zh", "district_en", "area_km2",
              "village_count", "label_lon", "label_lat")
    boundary_source = villages["features"][0]["properties"]["source"]
    for fc, keep in ((villages, keep_v), (districts, keep_d)):
        for f in fc["features"]:
            f["properties"] = {k: f["properties"][k] for k in keep}
        fc.pop("crs", None)

    return {
        "districts": districts,
        "villages": villages,
        "zoning": zoning,
        "projects": projects,
        "boundary_source": boundary_source,
        "plan": read_json(PLAN),
        "refs": read_csv(REFS),
    }


def inline_json(obj):
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # Keep the payload from closing the surrounding <script> element.
    return text.replace("</", "<\\/")


def fill(template, values):
    for marker, value in values.items():
        if marker not in template:
            raise SystemExit(f"marker {marker!r} not found in template")
        template = template.replace(marker, value)
    return template


def wrap_page(fragment, lang):
    return (
        "<!doctype html>\n"
        f'<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        # OSM tile servers expect a Referer from web pages; keep the browser default explicit.
        '<meta name="referrer" content="strict-origin-when-cross-origin">\n'
        "</head>\n<body>\n" + fragment + "\n</body>\n</html>\n"
    )


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({len(text.encode('utf-8')) / 1024:.0f} KB)")


def rings(geom):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def thumbnail_svg(data, width=560, pad=6):
    """Static outline of districts and villages for the landing page (Web Mercator, like the map)."""
    def merc(lon, lat):
        return math.radians(lon), math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    pts = [merc(lon, lat)
           for f in data["districts"]["features"]
           for poly in rings(f["geometry"]) for ring in poly for lon, lat in ring]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    scale = (width - 2 * pad) / (x1 - x0)
    height = (y1 - y0) * scale + 2 * pad

    def path(geom):
        out = []
        for poly in rings(geom):
            for ring in poly:
                cmds = []
                for i, (lon, lat) in enumerate(ring):
                    x, y = merc(lon, lat)
                    cmds.append(f"{'L' if i else 'M'}{pad + (x - x0) * scale:.1f} {pad + (y1 - y) * scale:.1f}")
                out.append("".join(cmds) + "Z")
        return "".join(out)

    order = {f["properties"]["district_code"]: i for i, f in enumerate(data["districts"]["features"])}
    parts = [f'<path class="v d{order[f["properties"]["district_code"]]}" d="{path(f["geometry"])}"/>'
             for f in data["villages"]["features"]]
    parts += [f'<path class="dist" d="{path(f["geometry"])}"/>' for f in data["districts"]["features"]]
    return (f'<svg class="thumb" viewBox="0 0 {width} {height:.0f}" role="img" '
            f'aria-label="西屯區與北屯區的里界輪廓">{"".join(parts)}</svg>')


def landing_values(data):
    villages = data["villages"]["features"]
    districts = data["districts"]["features"]
    area = sum(f["properties"]["area_km2"] for f in districts)
    names = "、".join(f["properties"]["district_zh"] for f in districts)

    m = re.search(r"village boundaries \((\d{4}-\d{2}-\d{2})\)", data["boundary_source"])
    boundary_date = f"國土測繪中心村里界{m.group(1)}" if m else "國土測繪中心村里界"
    zoning_src = data["zoning"][0]["source"]
    zd = DATE_RE.search(zoning_src)
    project_dates = sorted(d for p in data["projects"] for d in DATE_RE.findall(p["source"]))

    rows = []
    for path, desc in DOWNLOADS:
        rel = path.relative_to(ROOT).as_posix()
        size_kb = path.stat().st_size / 1024
        rows.append(
            f'<tr><td class="file"><a href="{rel}" download>{html.escape(path.name)}</a>'
            f'<span class="fmt">{path.suffix[1:].upper()}</span></td>'
            f"<td>{html.escape(desc)}</td>"
            f'<td class="size num">{size_kb:.1f} KB</td></tr>'
        )

    sources = [
        f"區界與里界：{html.escape(data['boundary_source'])}",
        "邊界為簡化版本，適合示意與脈絡判讀，不宜用於量測或精確套疊。",
        f"土地使用分區面積：{html.escape(zoning_src)}",
        "重大建設進度：臺中市政府專案報告與新聞報導，各列來源見CSV的source欄位。",
        "細部計畫疊圖：由Figure 7-1英文參考版（非官方翻譯）自動描繪的色塊，依分區面積推算比例、"
        "以綠美圖與中央公園禁飛區公告座標定位，誤差約100–200公尺；以中文計畫書與官方圖資為準。",
        '底圖：© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors，'
        '圖磚依<a href="https://operations.osmfoundation.org/policies/tiles/">OSM圖磚使用政策</a>使用。',
    ]

    return {
        "<!--__THUMB__-->": thumbnail_svg(data),
        "<!--__N_VILLAGES__-->": str(len(villages)),
        "<!--__EXTENT__-->": f'{html.escape(names)}・{len(villages)}里・<span class="num">{area:.2f}</span> km²',
        "<!--__BOUNDARY_DATE__-->": boundary_date,
        "<!--__ZONING_DATE__-->": f"第二次通盤檢討公開展覽說明會{zd.group(0) if zd else ''}",
        "<!--__PROJECT_DATE__-->": f"資料至{project_dates[-1]}" if project_dates else "",
        "<!--__DOWNLOADS__-->": "".join(rows),
        "<!--__SOURCES__-->": "".join(f"<li>{s}</li>" for s in sources),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fragment", type=Path,
                        help="also write a body-only map fragment (no doctype/html/head, no OSM basemap) to this path")
    args = parser.parse_args()

    data = load_data()
    map_template = (TEMPLATES / "basemap.html").read_text(encoding="utf-8")
    payload = inline_json(data)

    map_page = fill(map_template, {
        "/*__DATA__*/null": payload,
        "/*__BASEMAP__*/true": "true",
        "<!--__EYEBROW__-->": '<a href="../index.html">#HackYourDistrict 2026</a> · Taichung · Shuinan context layers',
    })
    write(MAP_OUT, wrap_page(map_page, "en"))  # English leads; Chinese spans carry lang="zh-Hant-TW"

    landing = fill((TEMPLATES / "index.html").read_text(encoding="utf-8"), landing_values(data))
    write(LANDING_OUT, wrap_page(landing, "zh-Hant-TW"))

    if args.fragment:
        fragment = fill(map_template, {
            "/*__DATA__*/null": payload,
            "/*__BASEMAP__*/true": "false",
            "<!--__EYEBROW__-->": "#HackYourDistrict 2026 · Taichung · Shuinan context layers",
        })
        args.fragment.write_text(fragment, encoding="utf-8")
        print(f"wrote {args.fragment}")


if __name__ == "__main__":
    main()
