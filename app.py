from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

API_KEY = "YeYWj7o3aJNobZiVgprIiZYyFU6XPsMUnk7P4Y2u"
BASE_URL = "https://api.open.fec.gov/v1/"

@app.route("/")
def index():
    return render_template("index.html")

# Route to search candidates (case-insensitive)
@app.route("/search_candidate", methods=["GET"])
def search_candidate():
    name = request.args.get("name", "").strip().lower()
    
    if not name:
        return jsonify({"error": "Candidate name is required"}), 400

    url = f"{BASE_URL}candidates/search/?api_key={API_KEY}"
    response = requests.get(url)
    
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch data"}), 500

    data = response.json()
    candidates = [c for c in data.get("results", []) if name in c.get("name", "").lower()]

    if not candidates:
        return jsonify({"error": "No candidates found"}), 404

    return jsonify({"results": candidates})

# Route to get donations for a candidate with year filtering
@app.route("/get_donations", methods=["GET"])
def get_donations():
    candidate_id = request.args.get("candidate_id")
    year = request.args.get("year")

    if not candidate_id:
        return jsonify({"error": "Candidate ID is required"}), 400

    url = f"{BASE_URL}schedules/schedule_a/?candidate_id={candidate_id}&api_key={API_KEY}"
    
    if year:
        url += f"&two_year_transaction_period={year}"

    response = requests.get(url)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch donation data"}), 500

    donations = response.json().get("results", [])

    if not donations:
        return jsonify({"error": "No donations found for the selected year"}), 404

    return jsonify({"results": donations})

if __name__ == "__main__":
    app.run(debug=True)
