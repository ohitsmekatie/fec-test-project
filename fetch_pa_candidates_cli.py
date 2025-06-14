import json
import time
import requests
import argparse
from pathlib import Path
import logging

# --- Configuration ---
FEC_API_KEY = "YeYWj7o3aJNobZiVgprIiZYyFU6XPsMUnk7P4Y2u"
FEC_BASE_URL = "https://api.open.fec.gov/v1"
YEAR = 2024
RATE_LIMIT_DELAY = 0.25
MAX_RETRIES = 5

# --- Paths ---
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
CANDIDATES_OUT = DATA_DIR / "pa_candidates_with_donations.json"
ERRORS_OUT = DATA_DIR / "pa_candidates_errors.json"
RETRY_OUT = DATA_DIR / "retry_successes.json"
MERGED_OUT = DATA_DIR / "pa_candidates_with_donations_merged.json"

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- API Interaction ---
def safe_request_with_backoff(url, params, max_retries=MAX_RETRIES):
    """Make API request with exponential backoff for rate limiting."""
    delay = RATE_LIMIT_DELAY
    for attempt in range(max_retries):
        try:
            res = requests.get(url, params=params)
            if res.status_code == 429:
                retry_after = int(res.headers.get("Retry-After", delay))
                logger.warning(f"⏳ Rate limited. Retrying in {retry_after} seconds...")
                time.sleep(retry_after)
                continue
            res.raise_for_status()
            return res
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Request failed (attempt {attempt + 1}): {e}")
            time.sleep(delay)
            delay *= 2
    raise Exception(f"❌ Failed after {max_retries} retries.")

# --- Data Fetching ---
def fetch_all_pa_candidates():
    """Fetch all active PA candidates from recent election cycles."""
    page = 1
    all_candidates = []

    logger.info("Starting to fetch PA candidates...")
    while True:
        logger.info(f"📄 Fetching page {page}...")
        params = {
            "state": "PA",
            "api_key": FEC_API_KEY,
            "per_page": 100,
            "page": page,
            "candidate_status": "C"
        }

        try:
            res = safe_request_with_backoff(f"{FEC_BASE_URL}/candidates/search", params)
            data = res.json()
            results = data.get("results", [])

            # Filter for recent candidates (2022 or 2024 election years)
            recent = [c for c in results if set(c.get("election_years", [])) & {2022, 2024}]
            all_candidates.extend(recent)

            # Check if we've reached the last page
            if page >= data.get("pagination", {}).get("pages", 1):
                break

            page += 1
            time.sleep(RATE_LIMIT_DELAY)
        except Exception as e:
            logger.error(f"❌ Error on page {page}: {e}")
            break

    logger.info(f"✅ Found {len(all_candidates)} recent active candidates.")
    return all_candidates

def get_committees_for_candidate(candidate_id):
    """Get all committees associated with a candidate."""
    try:
        res = safe_request_with_backoff(
            f"{FEC_BASE_URL}/candidate/{candidate_id}/committees",
            {"api_key": FEC_API_KEY, "per_page": 100}
        )
        committees = [
            {
                "committee_id": c.get("committee_id"),
                "name": c.get("name")
            }
            for c in res.json().get("results", [])
        ]
        return committees
    except Exception as e:
        logger.warning(f"⚠️ Error fetching committees for {candidate_id}: {e}")
        return []

def filter_candidates_with_donations(candidates, log_errors=True):
    """Filter candidates to those with large donations and committees."""
    filtered = []
    errors = []

    total = len(candidates)
    logger.info(f"Filtering {total} candidates for those with donations...")

    for i, c in enumerate(candidates):
        name = c.get("name")
        cid = c.get("candidate_id")

        if not cid:
            continue

        logger.info(f"[{i+1}/{total}] Processing {name} ({cid})")

        params = {
            "api_key": FEC_API_KEY,
            "candidate_id": cid,
            "contributor_type": "individual",
            "min_amount": 5000,
            "per_page": 1,
            "two_year_transaction_period": YEAR
        }

        try:
            res = safe_request_with_backoff(f"{FEC_BASE_URL}/schedules/schedule_a", params)
            if res.status_code == 400:
                logger.warning(f"❌ Skipping {name} — 400 Bad Request")
                continue

            if res.json().get("results"):
                committees = get_committees_for_candidate(cid)
                if committees:
                    filtered.append({
                        "name": name,
                        "candidate_id": cid,
                        "committees": committees
                    })
                    logger.info(f"✅ {name} — {len(committees)} committees")
                else:
                    logger.warning(f"❌ Skipping {name} — No associated committees")
        except Exception as e:
            logger.error(f"⚠️ Error checking {name} ({cid}): {e}")
            if log_errors:
                errors.append({"name": name, "candidate_id": cid})

        time.sleep(RATE_LIMIT_DELAY)

    logger.info(f"Found {len(filtered)} candidates with donations and committees")
    return filtered, errors

# --- Recovery Operations ---
def retry_failed_candidates(error_file):
    """Retry candidates that failed in a previous run."""
    if not error_file.exists():
        logger.warning(f"⚠️ No error file found at {error_file}. Nothing to retry.")
        return []

    with open(error_file) as f:
        errors = json.load(f)

    if not errors:
        logger.warning("⚠️ Error file is empty. Nothing to retry.")
        return []

    logger.info(f"🔁 Retrying {len(errors)} failed candidates...")
    return filter_candidates_with_donations(errors, log_errors=False)[0]

def merge_results(main_file, retry_file, merged_file):
    """Merge original results with retry results, avoiding duplicates."""
    if not main_file.exists() or not retry_file.exists():
        logger.error("❌ Required files do not exist. Cannot merge.")
        return

    with open(main_file) as f1, open(retry_file) as f2:
        original = json.load(f1)
        recovered = json.load(f2)

    combined = {c["candidate_id"]: c for c in original + recovered}

    with open(merged_file, "w") as f:
        json.dump(list(combined.values()), f, indent=2)

    logger.info(f"✅ Merged {len(combined)} candidates to {merged_file}")

def save_json(data, filepath):
    """Save data to JSON file."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"✅ Data saved to {filepath}")

# --- CLI Entry ---
def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch PA candidates with $5K+ donations and their committees."
    )
    parser.add_argument("--fetch", action="store_true", help="Fetch and filter all candidates")
    parser.add_argument("--retry", action="store_true", help="Retry failed candidates from previous run")
    parser.add_argument("--merge", action="store_true", help="Merge original and retry results")
    args = parser.parse_args()

    # Create data directory if it doesn't exist
    DATA_DIR.mkdir(exist_ok=True)

    if args.fetch:
        logger.info("Starting fetch operation")
        all_candidates = fetch_all_pa_candidates()
        filtered, errors = filter_candidates_with_donations(all_candidates)

        save_json(filtered, CANDIDATES_OUT)
        logger.info(f"✅ Saved {len(filtered)} candidates to {CANDIDATES_OUT}")

        if errors:
            save_json(errors, ERRORS_OUT)
            logger.info(f"⚠️ Logged {len(errors)} errors to {ERRORS_OUT}")

    if args.retry:
        logger.info("Starting retry operation")
        recovered = retry_failed_candidates(ERRORS_OUT)
        save_json(recovered, RETRY_OUT)
        logger.info(f"✅ Recovered {len(recovered)} candidates written to {RETRY_OUT}")

    if args.merge:
        logger.info("Starting merge operation")
        merge_results(CANDIDATES_OUT, RETRY_OUT, MERGED_OUT)

if __name__ == "__main__":
    main()

