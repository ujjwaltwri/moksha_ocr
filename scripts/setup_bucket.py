"""Create and lock down the S3 bucket for ID-card photos. Safe to run again.

    docker compose -f infra/docker-compose.prod.yml run --rm tools python /scripts/setup_bucket.py

Uses S3_BUCKET, S3_REGION, S3_ACCESS_KEY, S3_SECRET_KEY and CORS_ORIGINS from .env:
- creates the bucket in S3_REGION if it doesn't exist
- blocks all public access (photos are only reachable through short-lived signed links)
- default encryption at rest
- CORS: browsers on the website (CORS_ORIGINS) may upload with POST
"""

import json
import os

import boto3
from botocore.exceptions import ClientError

bucket = os.environ["S3_BUCKET"]
region = os.environ.get("S3_REGION", "ap-south-1")
origins = json.loads(os.environ.get("CORS_ORIGINS", "[]"))
s3 = boto3.client("s3", region_name=region, endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
                  aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
                  aws_secret_access_key=os.environ.get("S3_SECRET_KEY"))

try:
    s3.head_bucket(Bucket=bucket)
    print(f"bucket {bucket} exists")
except ClientError:
    s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
    print(f"created bucket {bucket} in {region}")

s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
    "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
if not origins:
    raise SystemExit("CORS_ORIGINS is empty: set it to the website's origin, e.g. [\"https://mokshansut.com\"]")
s3.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": [{
    "AllowedOrigins": origins, "AllowedMethods": ["POST", "GET"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3000}]})
print(f"public access blocked, encryption on, uploads allowed from {', '.join(origins)}")
