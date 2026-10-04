import io
import zipfile
import threading
import pandas as pd
import requests
from flask import Flask, jsonify, render_template
from requests.adapters import HTTPAdapter, Retry

app = Flask(__name__)

STATCAN_API_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/14100287/en"
CACHED_DATA = None
DATA_LOADING = False

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session

def load_and_cache_data():
    global CACHED_DATA, DATA_LOADING
    if CACHED_DATA is not None or DATA_LOADING:
        return

    DATA_LOADING = True
    session = get_robust_session()
    try:
        print("-> [Background] Requesting download link from StatCan API...")
        response = session.get(STATCAN_API_URL, timeout=30)
        response.raise_for_status()
        api_result = response.json()

        csv_zip_url = api_result.get("object")
        if not csv_zip_url:
            print(f"[ERROR] StatCan API response missing 'object': {api_result}")
            DATA_LOADING = False
            return

        print("-> [Background] Downloading bulk CSV zip from StatCan...")
        zip_resp = session.get(csv_zip_url, timeout=120)
        zip_resp.raise_for_status()

        print("-> [Background] Extracting zip archive in memory...")
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
            csv_filename = [name for name in z.namelist() if name.endswith(".csv") and "sub" not in name][0]
            
            use_cols = ["REF_DATE", "GEO", "Labour force characteristics", "Gender", "Age group", "Data type", "VALUE"]
            indicators = ["Unemployment rate", "Participation rate", "Employment rate"]
            
            print("-> [Background] Processing CSV in low-memory chunks...")
            filtered_chunks = []
            
            with z.open(csv_filename) as f:
                for chunk in pd.read_csv(f, usecols=use_cols, dtype={"VALUE": "float32"}, chunksize=100000, low_memory=True):
                    chunk["REF_DATE"] = pd.to_datetime(chunk["REF_DATE"])
                    
                    mask = (
                        (chunk["GEO"] == "Canada") &
                        (chunk["Gender"] == "Total - Gender") &
                        (chunk["Age group"] == "15 years and over") &
                        (chunk["REF_DATE"] >= "2025-01-01") &
                        (chunk["Data type"].str.contains("Seasonally adjusted", case=False, na=False))
                    )
                    sub = chunk[mask]
                    sub = sub[sub["Labour force characteristics"].str.strip().isin(indicators)]
                    
                    if not sub.empty:
                        filtered_chunks.append(sub)

        if not filtered_chunks:
            print("[ERROR] Filtering resulted in 0 rows!")
            DATA_LOADING = False
            return

        sub_df = pd.concat(filtered_chunks, ignore_index=True)

        pivot_df = sub_df.pivot_table(
            index="REF_DATE",
            columns="Labour force characteristics",
            values="VALUE",
            aggfunc="first"
        ).reset_index()

        pivot_df["Month"] = pivot_df["REF_DATE"].dt.strftime("%b %Y")
        pivot_df = pivot_df.sort_values("REF_DATE")

        CACHED_DATA = {
            "months": pivot_df["Month"].tolist(),
            "unemployment_rate": pivot_df["Unemployment rate"].tolist(),
            "participation_rate": pivot_df["Participation rate"].tolist(),
            "employment_rate": pivot_df["Employment rate"].tolist(),
        }
        print("-> [Background] Data successfully processed and cached!")
    except Exception as e:
        print(f"[CRITICAL ERROR during background cache load]: {e}")
    finally:
        DATA_LOADING = False

# Kick off background data loading immediately without blocking startup
threading.Thread(target=load_and_cache_data, daemon=True).start()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/labor-data")
def get_labor_data():
    if CACHED_DATA is None:
        if DATA_LOADING:
            return jsonify({"status": "loading", "message": "Data is currently downloading in the background. Please try again in a few seconds."}), 202
        else:
            # Retry loading synchronously if it failed earlier
            load_and_cache_data()
            
    if CACHED_DATA is None:
        return jsonify({"error": "Data failed to initialize due to network or memory limits. Check Render logs."}), 500
        
    return jsonify(CACHED_DATA)

if __name__ == "__main__":
    app.run(debug=True, port=5034)