"""Fit the traced detailed plan (drawing mm) to OpenStreetMap road centrelines.

Searches scale, rotation and translation for the similarity transform used by
scripts/georef_plan.py and prints the best parameters. Cost for a candidate:
  * patch boundary samples should sit near a road (half a street width away):
    mean(min(distance to road, 40 m));
  * interior samples (patches inset by ~12 m) should not have a road through
    them: + 60 * share of interior samples within 6 m of a road;
  * a weak prior keeps the scale near the zone-area estimate of 12.5 m/mm.

Needs data/derived/roads_osm.geojson (scripts/fetch_roads.py) and
numpy, scipy and shapely:  pip install numpy scipy shapely
Takes about a minute.

Usage:
    python3 scripts/register_plan.py
"""
import sys, json, math, itertools
from pathlib import Path
import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon, Point
sys.path.insert(0, str(Path(__file__).resolve().parent))
import georef_plan as G  # reuses the DXF reader and constants

LON0, LAT0, MX, MY = G.LON0, G.LAT0, G.M_PER_DEG_LON, G.M_PER_DEG_LAT
roads = json.load(open(Path(__file__).resolve().parent.parent / "data" / "derived" / "roads_osm.geojson"))

# ---- road distance raster (2 m cells) over the site
X0, X1, Y0, Y1, RES = -2600.0, 1600.0, -2000.0, 2200.0, 2.0
W, H = int((X1 - X0) / RES), int((Y1 - Y0) / RES)
mask = np.ones((H, W), dtype=bool)  # True = not road
use = {"motorway", "trunk", "primary", "secondary", "tertiary", "minor", "motorway_link", "trunk_link",
       "primary_link", "secondary_link", "tertiary_link"}
nseg = 0
for f in roads["features"]:
    if f["properties"]["kind"] not in use:
        continue
    pts = [((lon - LON0) * MX, (lat - LAT0) * MY) for lon, lat in f["geometry"]["coordinates"]]
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        n = max(2, int(math.hypot(xb - xa, yb - ya) / 1.0))
        xs = np.linspace(xa, xb, n); ys = np.linspace(ya, yb, n)
        cx = ((xs - X0) / RES).astype(int); cy = ((Y1 - ys) / RES).astype(int)
        ok = (cx >= 0) & (cx < W) & (cy >= 0) & (cy < H)
        mask[cy[ok], cx[ok]] = False
        nseg += 1
dist = ndimage.distance_transform_edt(mask) * RES
print("road segments", nseg, "raster", W, H)

def lookup(x, y):
    cx = ((x - X0) / RES).astype(int); cy = ((Y1 - y) / RES).astype(int)
    out = np.full(x.shape, 80.0)
    ok = (cx >= 0) & (cx < W) & (cy >= 0) & (cy < H)
    out[ok] = dist[cy[ok], cx[ok]]
    return out

# ---- samples from the drawing
bnd, inn = [], []
for layer, closed, pts in G.read_lwpolylines(G.DXF):
    if layer not in G.CLASSES or not closed or len(pts) < 3:
        continue
    poly = Polygon(pts).buffer(0)
    if poly.area < 4:  # skip slivers under 4 mm^2 (~600 m^2)
        continue
    ring = poly.exterior
    for t in np.arange(0, ring.length, 0.8):  # every 0.8 mm (~10 m)
        p = ring.interpolate(t); bnd.append((p.x, p.y))
    core = poly.buffer(-1.0)  # ~12 m inset
    if core.is_empty:
        continue
    minx, miny, maxx, maxy = core.bounds
    for x in np.arange(minx, maxx, 1.2):
        for y in np.arange(miny, maxy, 1.2):
            if core.contains(Point(x, y)):
                inn.append((x, y))
bnd = np.array(bnd); inn = np.array(inn)
print("boundary samples", len(bnd), "interior samples", len(inn))

def cost(s, th, tx, ty, detail=False):
    c, sn = math.cos(math.radians(th)), math.sin(math.radians(th))
    bx = s * (c * bnd[:, 0] - sn * bnd[:, 1]) + tx; by = s * (sn * bnd[:, 0] + c * bnd[:, 1]) + ty
    ix = s * (c * inn[:, 0] - sn * inn[:, 1]) + tx; iy = s * (sn * inn[:, 0] + c * inn[:, 1]) + ty
    db = np.minimum(lookup(bx, by), 40.0)
    di = lookup(ix, iy)
    through = np.mean(di < 6.0)
    prior = ((s - 12.5) / 0.6) ** 2
    J = db.mean() + 60.0 * through + prior
    if detail:
        return J, db.mean(), through, np.median(db)
    return J

s0, th0 = G.SCALE, G.ROTATION_DEG
t0x, t0y = G.fit_translation()  # current parameters, used as the search centre
print("current estimate: s=%.2f th=%.1f t=(%.0f, %.0f)  cost=%.2f  bnd=%.1f m  through=%.3f  median=%.1f" % ((s0, th0, t0x, t0y) + tuple(cost(s0, th0, t0x, t0y, True))))

best = None
# coarse: rotation and scale grid, translation +-500 m in 20 m steps around the drawing-centre position
cxm, cym = 130.0, 156.0  # drawing point kept as the rotation/scale anchor
gx0, gy0 = s0 * cxm + t0x, s0 * cym + t0y  # its ground position under the current estimate
results = []
for s in np.arange(11.8, 13.21, 0.2):
    for th in np.arange(-6, 6.1, 1.0):
        c, sn = math.cos(math.radians(th)), math.sin(math.radians(th))
        ax, ay = s * (c * cxm - sn * cym), s * (sn * cxm + c * cym)
        for dx in np.arange(-500, 501, 20):
            for dy in np.arange(-500, 501, 20):
                tx, ty = gx0 + dx - ax, gy0 + dy - ay
                J = cost(s, th, tx, ty)
                results.append((J, s, th, tx, ty))
results.sort()
print("coarse top 5:")
for r in results[:5]:
    print("  J=%.2f s=%.2f th=%.1f t=(%.0f, %.0f)" % r)

# fine: local search around the best few
def refine(J, s, th, tx, ty):
    steps = [(0.05, 0.25, 5.0), (0.02, 0.1, 2.0), (0.01, 0.05, 1.0)]
    for ds, dth, dt in steps:
        improved = True
        while improved:
            improved = False
            for a, b, cc, d in itertools.product((-ds, 0, ds), (-dth, 0, dth), (-dt, 0, dt), (-dt, 0, dt)):
                Jn = cost(s + a, th + b, tx + cc, ty + d)
                if Jn < J - 1e-6:
                    J, s, th, tx, ty = Jn, s + a, th + b, tx + cc, ty + d
                    improved = True
    return J, s, th, tx, ty

refined = sorted(refine(*r) for r in results[:6])
for r in refined[:3]:
    print("refined: J=%.3f s=%.3f th=%.2f t=(%.1f, %.1f)" % r, " detail:", tuple(round(v, 3) for v in cost(r[1], r[2], r[3], r[4], True)))
J, s, th, tx, ty = refined[0]
print("paste into scripts/georef_plan.py:  SCALE = %.2f, ROTATION_DEG = %.1f, TRANSLATION_M = (%.1f, %.1f)" % (s, th, tx, ty))
# shift of the plan centre
c, sn = math.cos(math.radians(th)), math.sin(math.radians(th))
gx, gy = s * (c * cxm - sn * cym) + tx, s * (sn * cxm + c * cym) + ty
print("plan-centre shift vs estimate: %.0f m east, %.0f m north" % (gx - gx0, gy - gy0))
