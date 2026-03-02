import sys
import os
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

def get_client():
    # Credentials should be provided via environment variables or ~/.aws/credentials
    return boto3.client('s3')

def list_objects(bucket, prefix=None):
    s3_client = get_client()
    try:
        kwargs = {'Bucket': bucket}
        if prefix:
            kwargs['Prefix'] = prefix
        
        response = s3_client.list_objects_v2(**kwargs)
        
        if 'Contents' in response:
            print(f"Objects in {bucket}/{prefix or ''}:")
            for obj in response['Contents']:
                print(f"  {obj['Key']} ({obj['Size']} bytes)")
        else:
            print(f"No objects found in {bucket}/{prefix or ''}")
    except Exception as e:
        print(f"Error listing objects: {e}")

def upload_files(file_paths, bucket, prefix=""):
    s3_client = get_client()
    for file_path in file_paths:
        object_name = prefix + os.path.basename(file_path)
        try:
            s3_client.upload_file(file_path, bucket, object_name)
            print(f"Successfully uploaded {file_path} to {bucket}/{object_name}")
        except Exception as e:
            print(f"Error uploading {file_path}: {e}")

def download_objects(bucket, object_keys, local_dir="."):
    s3_client = get_client()
    if not os.path.exists(local_dir):
        os.makedirs(local_dir)
        
    for key in object_keys:
        local_path = os.path.join(local_dir, os.path.basename(key))
        try:
            s3_client.download_file(bucket, key, local_path)
            print(f"Successfully downloaded {bucket}/{key} to {local_path}")
        except Exception as e:
            print(f"Error downloading {key}: {e}")

def delete_objects(bucket, object_keys):
    s3_client = get_client()
    try:
        delete_dict = {'Objects': [{'Key': k} for k in object_keys]}
        response = s3_client.delete_objects(Bucket=bucket, Delete=delete_dict)
        print(f"Deleted {len(response.get('Deleted', []))} objects from {bucket}")
    except Exception as e:
        print(f"Error deleting objects: {e}")

def generate_url(bucket, object_key, expiration=3600):
    s3_client = get_client()
    try:
        url = s3_client.generate_presigned_url('get_object',
                                              Params={'Bucket': bucket, 'Key': object_key},
                                              ExpiresIn=expiration)
        print(f"Presigned URL (valid for {expiration}s):\n{url}")
    except Exception as e:
        print(f"Error generating URL: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python s3_op.py <command> ...")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        list_objects(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "upload":
        # python s3_op.py upload <bucket> <prefix> <file1> <file2> ...
        bucket = sys.argv[2]
        prefix = sys.argv[3]
        files = sys.argv[4:]
        upload_files(files, bucket, prefix)
    elif cmd == "download":
        # python s3_op.py download <bucket> <local_dir> <key1> <key2> ...
        bucket = sys.argv[2]
        local_dir = sys.argv[3]
        keys = sys.argv[4:]
        download_objects(bucket, keys, local_dir)
    elif cmd == "delete":
        # python s3_op.py delete <bucket> <key1> <key2> ...
        delete_objects(sys.argv[2], sys.argv[3:])
    elif cmd == "url":
        # python s3_op.py url <bucket> <key> [expiration]
        exp = int(sys.argv[4]) if len(sys.argv) > 4 else 3600
        generate_url(sys.argv[2], sys.argv[3], exp)
    else:
        print(f"Unknown command: {cmd}")
