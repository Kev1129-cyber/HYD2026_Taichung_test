"""Build the Xitun/Beitun base map (map/index.html) from data/raw.

Reads the district and village GeoJSON plus the two Shuinan CSV tables,
inlines them into map/basemap.template.html, and writes a self-contained
HTML page that opens directly from disk (no server, no external data).

Usage:
    python3 scripts/build_map.py                     # writes map/index.html
    python3 scripts/build_map.py --fragment out.html # also writes a body-only
                                                     # fragment (for Artifact publish)

Standard library only.
"""

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TEMPLATE = ROOT / "map" / "basemap.template.html"
OUT = ROOT / "map" / "index.html"

# Traditional Chinese renderings of status_en / key_figures_en in
# shuinan_major_projects_2026.csv, keyed by project_zh. `phase` drives the
# status chip: "open" = opened / in use / in service / existing,
# "pending" = not yet open. Projects missing here fall back to the English text.
PROJECT_ZH = {
    "臺中綠美圖": {
        "phase": "open",
        "status_zh": "2025年12月開館",
    },
    "臺中國際會展中心": {
        "phase": "open",
        "status_zh": "2026-03-23正式開幕；二期原訂2026年設計、2027年起施工",
    },
    "水湳轉運中心": {
        "phase": "open",
        "status_zh": "2026-08-05啟用；國道客運與市區公車路線分階段進駐；地下層預留未來捷運橘線介面",
    },
    "臺中流行影音中心（原中臺灣電影中心）": {
        "phase": "pending",
        "status_zh": "2025年9月報告預計2026年底開幕；尚待確認",
    },
    "臺中超巨蛋": {
        "phase": "pending",
        "status_zh": "已選出最優申請人",
        "key_figures_zh": "基地約15.79公頃；約45,000席",
    },
    "中央公園": {
        "phase": "open",
        "status_zh": "使用中",
        "key_figures_zh": "約67公頃",
    },
    "捷運綠線文華高中站": {
        "phase": "open",
        "status_zh": "營運中；位於中央公園南側",
    },
    "園區停車供給": {
        "phase": "open",
        "status_zh": "既有",
        "key_figures_zh": "汽車位近8,000格；機車位逾4,500格",
    },
}


def read_csv(path):
    # utf-8-sig: the source CSVs are saved with a byte-order mark (Excel-friendly).
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_data():
    districts = json.loads((RAW / "context_xitun_beitun_districts.geojson").read_text(encoding="utf-8"))
    villages = json.loads((RAW / "context_xitun_beitun_villages.geojson").read_text(encoding="utf-8"))

    zoning = []
    for row in read_csv(RAW / "shuinan_zoning_areas_2024.csv"):
        zoning.append({
            "zh": row["zone_zh"],
            "en": row["zone_en"],
            "ha": float(row["area_ha"]),
            "pct": float(row["share_of_plan_area_pct"]),
            "source": row["source"],
        })

    projects = []
    for row in read_csv(RAW / "shuinan_major_projects_2026.csv"):
        zh = PROJECT_ZH.get(row["project_zh"], {})
        projects.append({
            "zh": row["project_zh"],
            "en": row["project_en"],
            "status_en": row["status_en"],
            "status_zh": zh.get("status_zh", row["status_en"]),
            "key_figures_en": row["key_figures_en"],
            "key_figures_zh": zh.get("key_figures_zh", row["key_figures_en"]),
            "phase": zh.get("phase", "unknown"),
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
    }


def inline_json(obj):
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # Keep the payload from closing the surrounding <script> element.
    return text.replace("</", "<\\/")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fragment", type=Path,
                        help="also write a body-only fragment (no doctype/html/head) to this path")
    args = parser.parse_args()

    template = TEMPLATE.read_text(encoding="utf-8")
    marker = "/*__DATA__*/null"
    if marker not in template:
        raise SystemExit(f"data marker {marker!r} not found in {TEMPLATE}")
    fragment = template.replace(marker, inline_json(load_data()))

    page = (
        "<!doctype html>\n"
        '<html lang="zh-Hant-TW">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        "</head>\n<body>\n" + fragment + "\n</body>\n</html>\n"
    )
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(page.encode('utf-8')) / 1024:.0f} KB)")

    if args.fragment:
        args.fragment.write_text(fragment, encoding="utf-8")
        print(f"wrote {args.fragment}")


if __name__ == "__main__":
    main()
