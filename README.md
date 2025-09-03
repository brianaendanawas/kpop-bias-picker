# K-Pop Bias Picker (Serverless)

A tiny serverless app to vote your bias and see live results.

## Architecture
- **Frontend**: Static HTML/JS (served locally or S3/CloudFront)
- **API Gateway** → **Lambda** (Python) → **DynamoDB** (votes table)

## Endpoints
- `GET /groups/{groupId}` → group name + members + current votes
- `POST /groups/{groupId}/vote` → body: `{ "memberId": "..." }`
- `GET /groups/{groupId}/results` → aggregated results (or derived from group)

## Frontend Setup
1. Set `API_BASE` and `GROUP_ID` in `index.html`.
2. Run:
   ```bash
   cd frontend
   python -m http.server 5173

## Demo
Here’s the website:

![Kpop Bias Picker Screenshot](images/frontend-screenshot.png)