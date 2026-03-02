import sys
import os
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

def upload_file(file_name, bucket, object_name=None):
    if object_name is None:
        object_name = os.path.basename(file_name)

    s3_client = boto3.client('s3')
    try:
        s3_client.upload_file(file_name, bucket, object_name)
        print(f"Successfully uploaded {file_name} to {bucket}/{object_name}")
    except FileNotFoundError:
        print(f"Error: The file {file_name} was not found")
    except NoCredentialsError:
        print("Error: AWS credentials not found.")
        print("\nPlease configure your credentials using one of these methods:")
        print("1. Run 'aws configure' (requires AWS CLI)")
        print("2. Set environment variables:")
        print("   export AWS_ACCESS_KEY_ID=your_key")
        print("   export AWS_SECRET_ACCESS_KEY=your_secret")
        print("   export AWS_DEFAULT_REGION=your_region")
    except ClientError as e:
        print(f"Error: {e}")

def download_file(bucket, object_name, file_name=None):
    if file_name is None:
        file_name = os.path.basename(object_name)

    s3_client = boto3.client('s3')
    try:
        s3_client.download_file(bucket, object_name, file_name)
        print(f"Successfully downloaded {bucket}/{object_name} to {file_name}")
    except NoCredentialsError:
        print("Error: AWS credentials not found.")
        print("\nPlease configure your credentials using one of these methods:")
        print("1. Run 'aws configure' (requires AWS CLI)")
        print("2. Set environment variables:")
        print("   export AWS_ACCESS_KEY_ID=your_key")
        print("   export AWS_SECRET_ACCESS_KEY=your_secret")
        print("   export AWS_DEFAULT_REGION=your_region")
    except ClientError as e:
        print(f"Error: {e}")

def list_buckets():
    s3_client = boto3.client('s3')
    try:
        response = s3_client.list_buckets()
        print("Buckets:")
        for bucket in response['Buckets']:
            print(f"  {bucket['Name']}")
    except NoCredentialsError:
        print("Error: AWS credentials not found.")
        print("\nPlease configure your credentials using one of these methods:")
        print("1. Run 'aws configure' (requires AWS CLI)")
        print("2. Set environment variables:")
        print("   export AWS_ACCESS_KEY_ID=your_key")
        print("   export AWS_SECRET_ACCESS_KEY=your_secret")
        print("   export AWS_DEFAULT_REGION=your_region")
    except ClientError as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python s3_op.py list-buckets")
        print("  python s3_op.py upload <file_name> <bucket> [object_name]")
        print("  python s3_op.py download <bucket> <object_name> [file_name]")
        sys.exit(1)

    command = sys.argv[1]
    if command == "list-buckets":
        list_buckets()
    elif command == "upload":
        if len(sys.argv) < 4:
            print("Usage: python s3_op.py upload <file_name> <bucket> [object_name]")
            sys.exit(1)
        file_name = sys.argv[2]
        bucket = sys.argv[3]
        object_name = sys.argv[4] if len(sys.argv) > 4 else None
        upload_file(file_name, bucket, object_name)
    elif command == "download":
        if len(sys.argv) < 4:
            print("Usage: python s3_op.py download <bucket> <object_name> [file_name]")
            sys.exit(1)
        bucket = sys.argv[2]
        object_name = sys.argv[3]
        file_name = sys.argv[4] if len(sys.argv) > 4 else None
        download_file(bucket, object_name, file_name)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
