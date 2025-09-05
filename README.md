# K-Pop Bias Picker (Serverless)

A tiny serverless app to vote your bias and see live results.

## Architecture
- **Frontend**: Static HTML/JS (S3 static website)
- **API Gateway** → **Lambda** (Python) → **DynamoDB** (votes table)

## Endpoints
- `GET /groups/{groupId}`
- `POST /groups/{groupId}/vote`
- `GET /groups/{groupId}/results`

## Deploy (Frontend)
1. Create S3 bucket (public access off) + enable static website hosting (index.html).
2. Add bucket policy for public read:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": "*",
       "Action": "s3:GetObject",
       "Resource": "arn:aws:s3:::bias-picker-briana-2025/*"
     }]
   }
3. Upload index.html (console or aws s3 cp).
4. Update Lambda env var:
ALLOWED_ORIGIN=http://bias-picker-briana-2025.s3-website-us-east-1.amazonaws.com

## Demo
Here’s the website:

![Kpop Bias Picker Screenshot](images/frontend-screenshot.png)