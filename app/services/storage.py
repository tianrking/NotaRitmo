from datetime import timedelta
from io import BytesIO

from minio import Minio

from app.config import settings


def get_minio() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket() -> None:
    client = get_minio()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


def put_bytes(object_name: str, content: bytes, content_type: str) -> str:
    ensure_bucket()
    client = get_minio()
    client.put_object(
        settings.minio_bucket,
        object_name,
        BytesIO(content),
        length=len(content),
        content_type=content_type,
    )
    return f"minio://{settings.minio_bucket}/{object_name}"


def presigned_get(object_name: str, hours: int = 4) -> str:
    ensure_bucket()
    return get_minio().presigned_get_object(
        settings.minio_bucket,
        object_name,
        expires=timedelta(hours=hours),
    )

