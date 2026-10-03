import io
import zipfile
import pandas as pd
import requests

STATCAN_API_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/14100287/en"


def validate_statcan_data():
  print("-> Requesting download link from StatCan API...")
  response = requests.get(STATCAN_API_URL, timeout=20)
  response.raise_for_status()
  api_result = response.json()

  csv_zip_url = api_result.get("object")
  print(f"-> Downloading zip from: {csv_zip_url}")

  zip_resp = requests.get(csv_zip_url, timeout=60)
  zip_resp.raise_for_status()

  with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
    csv_filename = [
        name for name in z.namelist() if name.endswith(".csv") and "sub" not in name
    ][0]
    print(f"-> Reading CSV file inside zip: {csv_filename}")
    with z.open(csv_filename) as f:
      df = pd.read_csv(f, low_memory=False)

  print("\n" + "=" * 50)
  print(f"SUCCESS: Loaded {len(df):,} total rows.")
  print("=" * 50)

  print("\n[1] ALL COLUMN NAMES:")
  print(df.columns.tolist())

  print("\n[2] UNIQUE GEO VALUES:")
  print(df["GEO"].unique()[:10])

  print("\n[3] UNIQUE GENDER VALUES:")
  print(df["Gender"].unique())

  print("\n[4] UNIQUE AGE GROUP VALUES:")
  print(df["Age group"].unique())

  print("\n[5] UNIQUE DATA TYPE VALUES:")
  if "Data type" in df.columns:
    print(df["Data type"].unique())

  print("\n[6] UNIQUE LABOUR FORCE CHARACTERISTICS:")
  print(df["Labour force characteristics"].unique()[:15])

  # Test the filter live
  df["REF_DATE"] = pd.to_datetime(df["REF_DATE"])
  test_filtered = df[
      (df["GEO"] == "Canada")
      & (df["Gender"] == "Total - Gender")
      & (df["Age group"] == "15 years and over")
      & (df["REF_DATE"] >= "2025-01-01")
      & (df["Data type"].str.contains("Seasonally adjusted", case=False, na=False))
  ]

  print("\n" + "=" * 50)
  print(f"TEST FILTER RESULT: {len(test_filtered):,} matching rows found.")
  print("=" * 50)

  if len(test_filtered) > 0:
    print("Validation passed! Your filters are completely correct.")
  else:
    print("Validation failed: 0 rows matched. Check unique values above.")


if __name__ == "__main__":
  validate_statcan_data()