"""Shared S3 client for SeaweedFS, configured entirely from environment variables.

Env vars (all required except AWS_REGION):
  S3_ENDPOINT            e.g. http://seaweedfs.data.svc.cluster.local:8333  (in cluster)
                         or   http://localhost:8333                         (host port-forward)
  AWS_ACCESS_KEY_ID      from the s3-credentials Secret
  AWS_SECRET_ACCESS_KEY  from the s3-credentials Secret
  AWS_REGION             default us-east-1 (SeaweedFS ignores it, boto3 wants it)

SeaweedFS needs path-style addressing and SigV4.
"""
import os

import boto3
from botocore.client import Config


def s3_client():
    endpoint = os.environ["S3_ENDPOINT"]
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket(client, bucket):
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)
    return bucket
