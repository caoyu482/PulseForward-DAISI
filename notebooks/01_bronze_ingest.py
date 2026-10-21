# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze ingest
# MAGIC **HealthPulse — PulseForward, DAISI Challenge 2026**
# MAGIC
# MAGIC Raw sources → Bronze Delta tables, unchanged except for lineage columns (`_source_id`, `_source_file`, `_ingested_at`).
# MAGIC 1. Every CSV / GeoJSON file in the Unity Catalog Volume `healthpulse_bronze.raw_files` (SingStat, MOH, AIC, URA; OneMap-geocoded)
# MAGIC 2. data.gov.sg datastore API (paged, with back-off) for the official monthly hospital admissions & attendances series

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
CATALOG = dbutils.widgets.get("catalog")
BRONZE = f"{CATALOG}.healthpulse_bronze"
VOL = f"/Volumes/{CATALOG}/healthpulse_bronze/raw_files"

import json, re, time, os
import requests
import pandas as pd
from pyspark.sql import functions as F


def lineage(df, source_id, source_file):
    return (df.withColumn("_source_id", F.lit(source_id))
              .withColumn("_source_file", F.lit(source_file))
              .withColumn("_ingested_at", F.current_timestamp()))


def table_name(folder, fname):
    stem = re.sub(r"[^a-z0-9_]", "_", os.path.splitext(fname)[0].lower())
    return f"{BRONZE}.{folder}__{stem}"

# COMMAND ----------

# MAGIC %md ## A. Files in the Volume → one Bronze table per file

# COMMAND ----------

ingested = []
for folder in ["population", "healthcare", "supply", "geography"]:
    for name in sorted(os.listdir(f"{VOL}/{folder}")):
        path = f"{VOL}/{folder}/{name}"
        tbl = table_name(folder, name)
        if name.endswith(".csv"):
            df = (spark.read.option("header", True).option("inferSchema", True)
                  .option("multiLine", True).option("escape", '"').csv(path))
        elif name.endswith(".geojson"):
            with open(path) as fh:
                gj = json.load(fh)
            rows = [{**{k: (None if v is None else str(v)) for k, v in feat["properties"].items()},
                     "geometry_json": json.dumps(feat["geometry"])} for feat in gj["features"]]
            df = spark.createDataFrame(pd.DataFrame(rows))
        else:
            continue
        df = lineage(df, f"{folder}/{name}", path)
        df.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(tbl)
        ingested.append((tbl, spark.table(tbl).count()))

display(spark.createDataFrame(pd.DataFrame(ingested, columns=["table", "rows"])))

# COMMAND ----------

# MAGIC %md ## B. data.gov.sg datastore API

# COMMAND ----------

DATAGOV = {
    # Hospital admissions & attendances, monthly (MOH via SingStat) — named dataset in the A3 problem statement
    "datagov__hospital_admissions_monthly": "d_b1ac3356e23ecad918854bbfa3627952",
}


def fetch_datastore(resource_id, page=1000, max_pages=50, retries=5):
    rows, offset = [], 0
    for _ in range(max_pages):
        url = f"https://data.gov.sg/api/action/datastore_search?resource_id={resource_id}&limit={page}&offset={offset}"
        for attempt in range(retries):
            r = requests.get(url, timeout=30)
            if r.status_code != 429:
                break
            time.sleep(2 ** attempt)  # polite back-off on rate limiting
        r.raise_for_status()
        recs = r.json()["result"]["records"]
        rows += recs
        if len(recs) < page:
            break
        offset += page
    return pd.DataFrame(rows).astype(str)


for name, rid in DATAGOV.items():
    pdf = fetch_datastore(rid)
    sdf = lineage(spark.createDataFrame(pdf), rid, f"https://data.gov.sg/datasets/{rid}/view")
    sdf.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{BRONZE}.{name}")
    print(f"{BRONZE}.{name}: {len(pdf)} rows x {len(pdf.columns)} cols")
