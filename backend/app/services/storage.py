import io
import logging
from minio import Minio
from minio.error import S3Error
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class DocumentStorage:
    def __init__(self):
        self._client = None
        self.bucket = settings.minio_bucket

    @property
    def client(self):
        if self._client is None:
            logger.info("[storage] Initializing MinIO client for endpoint=%s", settings.minio_endpoint)
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=False,
            )
            self._ensure_bucket()
        return self._client

    def _ensure_bucket(self):
        try:
            if not self._client.bucket_exists(self.bucket):
                logger.info("[storage] Creating bucket: %s", self.bucket)
                self._client.make_bucket(self.bucket)
            else:
                logger.debug("[storage] Bucket already exists: %s", self.bucket)
        except S3Error as e:
            logger.error("[storage] Failed to ensure bucket %s: %s", self.bucket, e)
            raise

    def upload(self, key: str, data: bytes, content_type: str) -> str:
        logger.info("[storage] Uploading object: %s (size=%s, content_type=%s)", key, len(data), content_type)
        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info("[storage] Upload complete: %s", key)
        return key

    def download(self, key: str) -> bytes:
        logger.info("[storage] Downloading object: %s", key)
        response = self.client.get_object(self.bucket, key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        logger.info("[storage] Downloaded %s bytes from %s", len(data), key)
        return data

    def delete(self, key: str):
        logger.info("[storage] Deleting object: %s", key)
        try:
            self.client.remove_object(self.bucket, key)
            logger.info("[storage] Deleted object: %s", key)
        except S3Error as e:
            logger.warning("[storage] Failed to delete object %s: %s", key, e)
            raise


storage = DocumentStorage()
