"""One-off QA: how much of each planning area stays the same between URA Master Plan versions.
Run locally (needs shapely, pyproj). Output uploaded to the UC Volume as geography/planning_area_boundary_overlap.csv."""
import json, sys
import pandas as pd
import pyproj
from shapely.geometry import shape
from shapely.ops import transform

GEO = sys.argv[1] if len(sys.argv) > 1 else "."
proj = pyproj.Transformer.from_crs(4326, 3414, always_xy=True).transform  # SVY21, metres

def load(v):
    g = json.load(open(f"{GEO}/ura_{v}_planning_areas.geojson"))
    return {f["properties"]["planning_area"]: transform(proj, shape(f["geometry"]).buffer(0)) for f in g["features"]}

a, b, c = load("mp2014"), load("mp2019"), load("mp2025")
rows = []
for pa in sorted(b):
    for x, y, lab in [(a, b, "MP2014->MP2019"), (b, c, "MP2019->MP2025")]:
        if pa in x and pa in y:
            rows.append(dict(pa=pa, change=lab, iou=x[pa].intersection(y[pa]).area / x[pa].union(y[pa]).area,
                             area_old_km2=x[pa].area / 1e6, area_new_km2=y[pa].area / 1e6))
pd.DataFrame(rows).to_csv("planning_area_boundary_overlap.csv", index=False)
