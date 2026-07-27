import hashlib
import hmac
import time
from datetime import timedelta
from io import BytesIO
from typing import Iterator
from urllib.parse import urlencode
from uuid import UUID

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


def parse_minio_uri(uri: str) -> str:
    prefix = f"minio://{settings.minio_bucket}/"
    if not uri.startswith(prefix):
        raise ValueError("not a NotaRitmo MinIO URI")
    return uri[len(prefix) :]


def provider_audio_url(meeting_id: UUID) -> str:
    expires = int(time.time()) + settings.provider_audio_url_ttl_seconds
    message = f"{meeting_id}:{expires}".encode()
    token = hmac.new(
        settings.provider_audio_secret.encode(), message, hashlib.sha256
    ).hexdigest()
    query = urlencode({"expires": expires, "token": token})
    return (
        f"{settings.public_api_base_url.rstrip('/')}/v1/providers/audio/"
        f"{meeting_id}?{query}"
    )


def verify_provider_audio_token(meeting_id: UUID, expires: int, token: str) -> bool:
    if expires < int(time.time()):
        return False
    message = f"{meeting_id}:{expires}".encode()
    expected = hmac.new(
        settings.provider_audio_secret.encode(), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, token)


def stream_object(object_name: str) -> tuple[Iterator[bytes], str | None, int | None]:
    client = get_minio()
    stat = client.stat_object(settings.minio_bucket, object_name)

    def iterator() -> Iterator[bytes]:
        response = client.get_object(settings.minio_bucket, object_name)
        try:
            for chunk in response.stream(1024 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    return iterator(), stat.content_type, stat.size
