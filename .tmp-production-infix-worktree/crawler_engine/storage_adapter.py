import os
import shutil
import tempfile
import hashlib
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

STORAGE_MODE = os.getenv("STORAGE_MODE", "hybrid").lower()
R2_ENABLED = os.getenv("R2_ENABLED", "false").lower() == "true"

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_PREFIX = os.getenv("R2_PREFIX", "raw_data").strip("/")

LOCAL_RAW_ROOT = os.getenv("LOCAL_RAW_ROOT", os.path.join(os.getcwd(), "raw_data"))
LOCAL_TEMP_ROOT = os.getenv("LOCAL_TEMP_ROOT", os.path.join(os.getcwd(), "tmp_storage"))

os.makedirs(LOCAL_TEMP_ROOT, exist_ok=True)

def _get_s3_client():
    if not R2_ENABLED:
        return None
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )

def is_r2_key(path_value: str) -> bool:
    if not path_value:
        return False
    path_value = str(path_value)
    return path_value.startswith("r2://") or (
        not os.path.isabs(path_value) and path_value.replace("\\", "/").startswith(f"{R2_PREFIX}/")
    )

def normalize_r2_key(path_value: str) -> str:
    if path_value.startswith("r2://"):
        return path_value[5:]
    return path_value.replace("\\", "/").lstrip("/")

def build_r2_key(*parts) -> str:
    cleaned = [str(p).strip("/\\") for p in parts if p is not None and str(p).strip("/\\")]
    return "/".join(cleaned)

def upload_file(local_path: str, r2_key: str) -> str:
    client = _get_s3_client()
    if not client:
        raise RuntimeError("R2 is not enabled")
    key = normalize_r2_key(r2_key)
    client.upload_file(local_path, R2_BUCKET, key)
    return key

def download_file(r2_key: str, local_path: str) -> str:
    client = _get_s3_client()
    if not client:
        raise RuntimeError("R2 is not enabled")
    key = normalize_r2_key(r2_key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    client.download_file(R2_BUCKET, key, local_path)
    return local_path

def object_exists(r2_key: str) -> bool:
    client = _get_s3_client()
    if not client:
        return False
    key = normalize_r2_key(r2_key)
    try:
        client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except ClientError:
        return False

def move_object(src_key: str, dst_key: str) -> str:
    client = _get_s3_client()
    if not client:
        raise RuntimeError("R2 is not enabled")
    src = normalize_r2_key(src_key)
    dst = normalize_r2_key(dst_key)
    client.copy({"Bucket": R2_BUCKET, "Key": src}, R2_BUCKET, dst)
    client.delete_object(Bucket=R2_BUCKET, Key=src)
    return dst

def delete_object(r2_key: str) -> None:
    client = _get_s3_client()
    if not client:
        raise RuntimeError("R2 is not enabled")
    key = normalize_r2_key(r2_key)
    client.delete_object(Bucket=R2_BUCKET, Key=key)

def ensure_local_file(path_value: str, temp_subdir: str = "resolved", force_refresh: bool = False) -> str:
    if not path_value:
        raise FileNotFoundError("Empty file path")
    if not is_r2_key(path_value):
        if not os.path.exists(path_value):
            raise FileNotFoundError(f"Local file not found: {path_value}")
        return path_value

    key = normalize_r2_key(path_value)
    filename = os.path.basename(key)
    local_dir = os.path.join(LOCAL_TEMP_ROOT, temp_subdir)
    key_hash = hashlib.sha1(key.encode("utf-8")).hexdigest()
    local_path = os.path.join(local_dir, f"{key_hash[:12]}_{filename}")

    if force_refresh and os.path.exists(local_path):
        os.remove(local_path)

    if not os.path.exists(local_path):
        download_file(key, local_path)

    return local_path
