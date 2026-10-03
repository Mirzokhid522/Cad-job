import io
import zipfile
import pandas as pd
import requests
from flask import Flask, jsonify, render_template

app = Flask(__name__)

STATCAN_API_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/14100287/en"


def fetch_latest_labor_data():
  print("-> Requesting download link from StatCan API...")
  response = requests.get(STATCAN_API_URL, timeout=20)
  response.raise_for_status()
  api_result = response.json()

  csv_zip_url = api_result.get("object")
  if not csv_zip_url:
    raise ValueError(f"StatCan API response missing 'object' key: {api_result}")

  print(f"-> Downloading bulk CSV zip from: {csv_zip_url}")
  zip_resp = requests.get(csv_zip_url, timeout=60)
  zip_resp.raise_for_status()

  print("-> Extracting zip archive in memory...")
  with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
    csv_filename = [
        name for name in z.namelist() if name.endswith(".csv") and "sub" not in name
    ][0]
    print(f"-> Reading CSV file inside zip: {csv_filename}")
    with z.open(csv_filename) as f:
      df = pd.read_csv(f, low_memory=False)

  print(f"-> Raw DataFrame loaded with {len(df):,} rows. Cleaning & filtering...")

  # Ensure date column is standard datetime
  df["REF_DATE"] = pd.to_datetime(df["REF_DATE"])

  # Filter criteria verified by check_data.py
  filtered_df = df[
      (df["GEO"] == "Canada")
      & (df["Gender"] == "Total - Gender")
      & (df["Age group"] == "15 years and over")
      & (df["REF_DATE"] >= "2025-01-01")
      & (
          df["Data type"].str.contains(
              "Seasonally adjusted", case=False, na=False
          )
      )
  ]

  indicators = ["Unemployment rate", "Participation rate", "Employment rate"]
  sub_df = filtered_df[
      filtered_df["Labour force characteristics"]
      .str.strip()
      .isin(indicators)
  ]

  print(f"-> Filtered rows remaining: {len(sub_df)}")

  if sub_df.empty:
    raise ValueError(
        "Filtering resulted in 0 rows! Check unique column values."
    )

  # Use pivot_table with aggfunc='first' to safely handle any duplicate rows
  pivot_df = (
      sub_df.pivot_table(
          index="REF_DATE",
          columns="Labour force characteristics",
          values="VALUE",
          aggfunc="first",
      )
      .reset_index()
  )

  pivot_df["Month"] = pivot_df["REF_DATE"].dt.strftime("%b %Y")
  pivot_df = pivot_df.sort_values("REF_DATE")

  data_payload = {
      "months": pivot_df["Month"].tolist(),
      "unemployment_rate": pivot_df["Unemployment rate"].tolist(),
      "participation_rate": pivot_df["Participation rate"].tolist(),
      "employment_rate": pivot_df["Employment rate"].tolist(),
  }
  print("-> Data payload successfully prepared!")
  return data_payload


@app.route("/")
def index():
  return render_template("index.html")


@app.route("/api/labor-data")
def get_labor_data():
  try:
    data = fetch_latest_labor_data()
    return jsonify(data)
  except Exception as e:
    print(f"[ERROR] Failed in fetch_latest_labor_data: {e}")
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
  app.run(debug=True, port=5034)