---
name: aws-s3-ops
description: Quick upload and download files to/from AWS S3 buckets. Use when the user asks to "upload to S3", "download from S3", or manage files in AWS storage. If credentials are not set, it guides the user to configure them.
---

# AWS S3 Operations

This skill provides a fast way to transfer files between your local environment and AWS S3 using a Python helper script.

## Initial Check

Before performing any S3 operation, the agent should verify if AWS credentials are set. If not, it MUST ask the user to configure them first.

## Prerequisites

- Python 3.x
- `boto3` library (`pip install boto3`)
- AWS Credentials configured (e.g., via `~/.aws/credentials` or environment variables)

## Capabilities

### 1. List Buckets
Lists all S3 buckets in the current account.
- **Script**: `scripts/s3_op.py`
- **Command**: `python3 scripts/s3_op.py list-buckets`

### 2. Upload File to S3
Uploads a local file to a specified S3 bucket.
- **Script**: `scripts/s3_op.py`
- **Command**: `python3 scripts/s3_op.py upload <file_path> <bucket_name> [object_key]`

### 3. Download File from S3
Downloads an object from an S3 bucket to the local filesystem.
- **Script**: `scripts/s3_op.py`
- **Command**: `python3 scripts/s3_op.py download <bucket_name> <object_key> [local_file_path]`

## Setup Guidance

If the user has not configured AWS, suggest one of these:
1. **Interactive Config**: `aws configure` (if AWS CLI is installed).
2. **Environment Variables**: Provide a template for `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION`.

## Usage Examples

- **List**: `python3 scripts/s3_op.py list-buckets`
- **Upload**: `python3 scripts/s3_op.py upload data.csv my-bucket`
- **Download**: `python3 scripts/s3_op.py download my-bucket images/logo.png ./logo.png`
