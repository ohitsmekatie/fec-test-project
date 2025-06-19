import json
import logging
import os
import requests
from flask import Flask, render_template, jsonify
from functools import lru_cache

app = Flask(__name__)

# Configuration constants
FEC_API_KEY = "YeYWj7o3aJNobZiVgprIiZYyFU6XPsMUnk7P4Y2u"
FEC_BASE_URL = "https://api.open.fec.gov/v1"
DATA_FILE_PATH = "data/pa_candidates_with_donations.json"

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load candidate data
def load_candidates():
    try:
        with open(DATA_FILE_PATH) as f:
            candidates = [c for c in json.load(f) if c.get("committees")]
        logger.info(f"Loaded {len(candidates)} candidates with committees")
        return candidates
    except Exception as e:
        logger.error(f"Failed to load candidates: {e}")
        return []

all_candidates = load_candidates()

@app.route("/")
def index():
    """Render the main application page."""
    return render_template("index.html", candidates=all_candidates)

@app.route("/get_committees/<candidate_id>")
def get_committees(candidate_id):
    """Return committees associated with a candidate."""
    candidate = next((c for c in all_candidates if c["candidate_id"] == candidate_id), None)
    if not candidate:
        logger.warning(f"No candidate found with ID: {candidate_id}")
        return jsonify([])

    committees = candidate.get("committees", [])
    logger.info(f"Found {len(committees)} committees for candidate {candidate_id}")
    return jsonify(committees)

@app.route("/get_reports/<committee_id>")
def get_reports(committee_id):
    """Fetch and return the latest report for a committee."""
    try:
        return jsonify(fetch_latest_report(committee_id))
    except requests.exceptions.HTTPError as e:
        logger.error(f"FEC API error for committee {committee_id}: {e}")
        return jsonify({"error": f"FEC API error: {e}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error for committee {committee_id}: {e}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@lru_cache(maxsize=100)
def fetch_latest_report(committee_id):
    """Fetch and return the latest report for a committee with caching."""
    logger.info(f"Fetching reports for committee: {committee_id}")

    res = requests.get(
        f"{FEC_BASE_URL}/committee/{committee_id}/reports",
        params={"api_key": FEC_API_KEY, "per_page": 10}
    )
    res.raise_for_status()

    reports = res.json().get("results", [])
    if not reports:
        logger.warning(f"No reports found for committee: {committee_id}")
        return {"error": f"No reports found for committee {committee_id}."}

    latest_report = sorted(
        reports,
        key=lambda r: r.get("coverage_end_date") or "",
        reverse=True
    )[0]

    logger.info(f"Found latest report for committee {committee_id}: {latest_report.get('report_type')}")
    return latest_report

if __name__ == "__main__":
    app.run(debug=True)
