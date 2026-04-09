# Real-Time Scholarship Eligibility & Fund Allocation System

A cloud-native, high-concurrency scholarship allocation system with:
- FastAPI backend
- DynamoDB (or SQLite fallback)
- Static HTML dashboard (S3-friendly)

## 1) Folder Structure

```
cloudverse/
  backend/
    app/
      db/
      services/
      config.py
      main.py
      models.py
    requirements.txt
    .env.example
  frontend/
    index.html
    styles.css
    config.js
  sample_data/
    applications.json
  scripts/
    seed.py
```

## 2) Backend Setup (Local)

1. Create a virtual environment and install dependencies:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
```

2. Create `.env` in [backend](backend) from `.env.example` and keep `DB_BACKEND=sqlite` for local use.

3. Start the API:

```
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

## 3) Frontend Setup (Local)

1. Edit [frontend/config.js](frontend/config.js) and set the API base URL if needed.
2. Start a tiny static server to avoid CORS issues with file URLs:

```
python -m http.server 5500 --directory frontend
```

3. Open http://localhost:5500 in your browser.

## 4) Sample Data

Option A: Seed via Python script:

```
python scripts\seed.py http://localhost:8000
```

Option B: Curl example (multipart with certificate files):

```
curl -X POST http://localhost:8000/applications \
  -F "applicant_id=A2001" \
  -F "name=Ana" \
  -F "income=40000" \
  -F "cgpa=9.1" \
  -F "category=ews" \
  -F "income_certificate=@sample_data/income_certificate.txt" \
  -F "caste_certificate=@sample_data/caste_certificate.txt"
```

## 5) API Summary

- `POST /applications` Submit application (multipart with certificates)
- `GET /leaderboard` Sorted leaderboard
- `POST /allocate` Allocate funds atomically
- `GET /dashboard` Combined dashboard view
- `GET /rules` Selection rules used in allocation

## 6) DynamoDB Setup (AWS)

1. Create table **ScholarshipApplications** with partition key `applicant_id` (String).
2. Add a GSI for scalable ranking:
  - Index name: `LeaderboardIndex`
  - Partition key: `gsi_pk` (String)
  - Sort key: `gsi_sk` (String)
  - Projection: All
3. Set environment:

```
DB_BACKEND=dynamodb
AWS_REGION=us-east-1
DYNAMODB_TABLE=ScholarshipApplications
```

The system stores a budget record under `applicant_id="__BUDGET__"`.

## 7) AWS Deployment

### Backend on EC2

1. Launch a **t2.micro** (free tier) Ubuntu instance.
2. Security group:
  - Inbound: TCP 22 from your IP, TCP 8000 from your IP (or 0.0.0.0/0 for demo).
3. SSH in and install Python 3.10+.
4. Copy the backend folder and `.env` file.
5. Install dependencies:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

6. Run with `uvicorn` or `gunicorn`:

```
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

7. Optional: create a systemd service so it survives reboots.

### Frontend on S3

1. Create an S3 bucket for static hosting.
2. Enable static website hosting (index document: `index.html`).
3. Upload `frontend/` contents.
4. Update [frontend/config.js](frontend/config.js) with the EC2 public URL.
5. Bucket policy: allow public `GetObject` for demo.

### Free Tier Notes

- DynamoDB on-demand + low traffic stays within free tier.
- EC2 t2.micro fits demo traffic. For heavy load, move to autoscaling + ALB.

## 8) Scoring & Allocation Notes

- Score = (cgpa * 10 * 0.7) + (income_component * 0.2) + category bonus
- `income_component = max(0, 100 - income / 1000)`
- Allocation is atomic per student and stops when budget is insufficient.
- Selection enforces CGPA >= 8.5 and category caps.
- Allocation requires income <= 8,00,000 and an income certificate upload.
- Non-General categories require a caste certificate for eligibility.
- Grants are per-category (see rules endpoint).

## 9) Notes

- For DynamoDB, allocation uses a transaction to decrement budget and mark applicants selected.
- For SQLite, allocation uses `BEGIN IMMEDIATE` to prevent concurrent overspending.
