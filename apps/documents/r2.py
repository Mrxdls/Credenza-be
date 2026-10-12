"""
Cloudflare R2 Object Storage Service.

Provides zero-egress, S3-compatible cloud storage operations for faculty achievement
proofs, certificates, publications, and static media assets.
Zero compression overhead: files are stored and retrieved in their native formats (PDF, PNG, JPG).
Credentials are read securely from environment variables, never stored in the database.
"""
from dataclasses import dataclass
import io
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import boto3
import botocore.client
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.base import File
from storages.backends.s3boto3 import S3Boto3Storage

from apps.documents.storage import (
    read_file_payload,
    resolve_mime_type,
)


@dataclass(frozen=True)
class R2Config:
    """Immutable value object encapsulating Cloudflare R2 connection parameters."""
    account_id: str = ""
    bucket_name: str = "poornima-achievements-r2"
    access_key_id: str = ""
    secret_access_key: str = ""
    endpoint_url: str = ""
    public_domain: str = ""
    presigned_expiry: int = 3600

    @classmethod
    def from_settings(cls) -> "R2Config":
        """Builds configuration from Django environment settings."""
        account_id = getattr(settings, 'CLOUDFLARE_ACCOUNT_ID', '')
        bucket_name = getattr(settings, 'CLOUDFLARE_R2_BUCKET', 'poornima-achievements-r2')
        access_key_id = getattr(settings, 'CLOUDFLARE_R2_ACCESS_KEY_ID', '')
        secret_access_key = getattr(settings, 'CLOUDFLARE_R2_SECRET_ACCESS_KEY', '')
        public_domain = getattr(settings, 'CLOUDFLARE_R2_PUBLIC_DOMAIN', '')
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com" if account_id else ""

        return cls(
            account_id=account_id,
            bucket_name=bucket_name,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            endpoint_url=endpoint_url,
            public_domain=public_domain.strip('/') if public_domain else "",
            presigned_expiry=3600,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "R2Config":
        """Builds configuration from a plain dictionary with fallback defaults."""
        account_id = data.get("account_id", "")
        endpoint_url = data.get("endpoint_url") or (
            f"https://{account_id}.r2.cloudflarestorage.com" if account_id else ""
        )
        public_domain = data.get("public_domain", "")
        return cls(
            account_id=account_id,
            bucket_name=data.get("bucket_name", "poornima-achievements-r2"),
            access_key_id=data.get("access_key_id", ""),
            secret_access_key=data.get("secret_access_key", ""),
            endpoint_url=endpoint_url,
            public_domain=public_domain.strip('/') if public_domain else "",
            presigned_expiry=data.get("presigned_expiry", 3600),
        )

    def to_dict(self) -> dict:
        """Converts configuration to a dictionary for backward compatibility."""
        return {
            "account_id": self.account_id,
            "bucket_name": self.bucket_name,
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "endpoint_url": self.endpoint_url,
            "public_domain": self.public_domain,
            "presigned_expiry": self.presigned_expiry,
        }

    @property
    def is_valid(self) -> bool:
        """Checks if all required Cloudflare R2 credentials are present."""
        return bool(self.account_id and self.access_key_id and self.secret_access_key)


class R2StorageService:
    """
    Object-oriented Cloudflare R2 Object Storage Service.

    Encapsulates credentials, boto3 client management, bucket operations,
    presigned URL generation, and health checks.
    """

    def __init__(
        self,
        config: Optional[Union[R2Config, dict]] = None,
        client: Optional[Any] = None,
    ):
        if config is None:
            self.config = R2Config.from_settings()
        elif isinstance(config, dict):
            self.config = R2Config.from_dict(config)
        elif isinstance(config, R2Config):
            self.config = config
        else:
            raise TypeError(f"Invalid config type: {type(config)}")

        self._client = client

    @property
    def is_configured(self) -> bool:
        """Returns True if required credentials are present."""
        return self.config.is_valid

    @classmethod
    def is_active(cls) -> bool:
        """Returns True if Cloudflare R2 is configured and ready for object storage."""
        return cls.get_default().is_configured

    @property
    def client(self):
        """Lazily creates and caches the boto3 S3 client."""
        if self._client is None:
            self._client = get_r2_client(self.config.to_dict())
        return self._client

    def get_django_storage(self) -> S3Boto3Storage:
        """Returns a configured S3Boto3Storage instance tailored for Cloudflare R2."""
        custom_domain = None
        if self.config.public_domain:
            custom_domain = self.config.public_domain.replace('https://', '').replace('http://', '').strip('/')

        return S3Boto3Storage(
            access_key=self.config.access_key_id,
            secret_key=self.config.secret_access_key,
            bucket_name=self.config.bucket_name,
            endpoint_url=self.config.endpoint_url,
            region_name='auto',
            default_acl='private',
            signature_version='s3v4',
            querystring_auth=True,
            querystring_expire=self.config.presigned_expiry,
            custom_domain=custom_domain,
        )

    def upload_file(
        self,
        file_input: Union[bytes, io.BytesIO, File],
        target_path: str,
        content_type: Optional[str] = None,
    ) -> dict:
        """
        Stores a native uncompressed file directly to Cloudflare R2 bucket.

        Args:
            file_input: Raw bytes, BytesIO stream, or Django File.
            target_path: Storage key in R2 (e.g. 'proofs/act-101/cert.pdf').
            content_type: Optional MIME type override.

        Returns:
            dict with storage_path, bucket, original_name, file_size, content_type.
        """
        raw_bytes, original_name, original_size = read_file_payload(file_input, default_name=target_path)
        upload_content_type = content_type or resolve_mime_type(original_name)

        self.client.put_object(
            Bucket=self.config.bucket_name,
            Key=target_path,
            Body=raw_bytes,
            ContentType=upload_content_type,
            Metadata={
                'original-filename': os.path.basename(original_name),
                'original-size': str(original_size),
            }
        )

        return {
            "storage_path": target_path,
            "bucket": self.config.bucket_name,
            "original_name": os.path.basename(original_name),
            "file_size": original_size,
            "content_type": upload_content_type,
        }

    def fetch_file(
        self,
        storage_path: str,
        original_filename: Optional[str] = None,
    ) -> Tuple[bytes, str, str]:
        """
        Fetches raw file bytes directly from Cloudflare R2.

        Returns:
            tuple of (file_bytes, clean_filename, mime_type)
        """
        response = self.client.get_object(Bucket=self.config.bucket_name, Key=storage_path)
        raw_data = response['Body'].read()
        metadata = response.get('Metadata', {})

        meta_name = metadata.get('original-filename')
        clean_filename = original_filename or meta_name or os.path.basename(storage_path)
        mime_type = resolve_mime_type(clean_filename)

        return raw_data, clean_filename, mime_type

    def generate_presigned_download_url(
        self,
        storage_path: str,
        expiry: Optional[int] = None,
        download: bool = False,
        original_filename: Optional[str] = None,
    ) -> str:
        """
        Generates a pre-signed Cloudflare R2 GET URL for secure time-limited access.
        """
        exp = expiry or self.config.presigned_expiry
        params = {
            'Bucket': self.config.bucket_name,
            'Key': storage_path,
        }

        if download or original_filename:
            filename = original_filename or os.path.basename(storage_path)
            disposition = 'attachment' if download else 'inline'
            params['ResponseContentDisposition'] = f'{disposition}; filename="{filename}"'

        return self.client.generate_presigned_url(
            ClientMethod='get_object',
            Params=params,
            ExpiresIn=exp
        )

    def generate_presigned_upload_url(
        self,
        storage_path: str,
        content_type: str,
        expiry: int = 900,
    ) -> str:
        """
        Generates a pre-signed Cloudflare R2 PUT URL allowing the client/browser
        to upload the file directly to R2.
        """
        params = {
            'Bucket': self.config.bucket_name,
            'Key': storage_path,
            'ContentType': content_type,
        }

        return self.client.generate_presigned_url(
            ClientMethod='put_object',
            Params=params,
            ExpiresIn=expiry,
        )

    def head_file(self, storage_path: str) -> dict:
        """Queries object metadata (e.g. ContentLength) without fetching body bytes."""
        return self.client.head_object(Bucket=self.config.bucket_name, Key=storage_path)

    def list_files(self, prefix: str = "", max_keys: int = 1000) -> List[dict]:
        """Lists files in the Cloudflare R2 bucket with given prefix."""
        response = self.client.list_objects_v2(
            Bucket=self.config.bucket_name,
            Prefix=prefix,
            MaxKeys=max_keys,
        )

        contents = response.get('Contents', [])
        return [
            {
                "key": item['Key'],
                "size": item['Size'],
                "last_modified": item['LastModified'].isoformat(),
                "etag": item.get('ETag', '').strip('"'),
            }
            for item in contents
        ]

    def delete_file(self, storage_path: str) -> bool:
        """Deletes an object from Cloudflare R2."""
        self.client.delete_object(Bucket=self.config.bucket_name, Key=storage_path)
        return True

    def test_connection(self) -> Tuple[bool, str]:
        """Validates Cloudflare R2 credentials by probing bucket existence."""
        try:
            self.client.head_bucket(Bucket=self.config.bucket_name)
            return True, f"Successfully connected to Cloudflare R2 bucket '{self.config.bucket_name}'."
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            return False, f"Cloudflare R2 error ({error_code}): {error_msg}"
        except Exception as e:
            return False, f"Failed to connect to Cloudflare R2: {str(e)}"

    @classmethod
    def get_default(cls) -> "R2StorageService":
        """Instantiates default service bound to dynamic environment settings."""
        return cls()


# ── Backward-Compatible Module-Level Functional API ───────────────────────────

def get_r2_config() -> dict:
    """Resolves Cloudflare R2 credentials and bucket settings as a dictionary."""
    return R2Config.from_settings().to_dict()


def get_r2_client(config: Optional[dict] = None):
    """Instantiates an authenticated boto3 S3 client configured for Cloudflare R2."""
    cfg = config or get_r2_config()
    if not cfg.get("account_id") or not cfg.get("access_key_id") or not cfg.get("secret_access_key"):
        raise ValueError(
            "Cloudflare R2 is not fully configured. "
            "Please configure CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_R2_ACCESS_KEY_ID, and "
            "CLOUDFLARE_R2_SECRET_ACCESS_KEY in your server environment (.env)."
        )

    boto_config = botocore.client.Config(
        signature_version='s3v4',
        retries={'max_attempts': 3, 'mode': 'standard'},
    )

    return boto3.client(
        service_name='s3',
        endpoint_url=cfg["endpoint_url"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
        region_name='auto',
        config=boto_config,
    )


def get_r2_storage(config: Optional[dict] = None) -> S3Boto3Storage:
    """Returns an S3Boto3Storage instance tailored for Cloudflare R2."""
    return R2StorageService(config=config).get_django_storage()


def store_to_r2(
    file_input: Union[bytes, io.BytesIO, File],
    target_path: str,
    content_type: Optional[str] = None,
    client=None,
    config: Optional[dict] = None,
    **kwargs
) -> dict:
    """Stores a native raw file directly to Cloudflare R2 bucket without compression."""
    service = R2StorageService(config=config, client=client)
    return service.upload_file(file_input=file_input, target_path=target_path, content_type=content_type)


def fetch_from_r2(
    storage_path: str,
    original_filename: Optional[str] = None,
    client=None,
    config: Optional[dict] = None,
    **kwargs
) -> Tuple[bytes, str, str]:
    """Fetches raw native file bytes directly from Cloudflare R2."""
    service = R2StorageService(config=config, client=client)
    return service.fetch_file(storage_path=storage_path, original_filename=original_filename)


def get_r2_presigned_url(
    storage_path: str,
    expiry: Optional[int] = None,
    download: bool = False,
    original_filename: Optional[str] = None,
    client=None,
    config: Optional[dict] = None,
) -> str:
    """Generates a pre-signed Cloudflare R2 URL for secure time-limited access."""
    service = R2StorageService(config=config, client=client)
    return service.generate_presigned_download_url(
        storage_path=storage_path,
        expiry=expiry,
        download=download,
        original_filename=original_filename,
    )


def is_r2_configured() -> bool:
    """Checks if Cloudflare R2 credentials and bucket are configured in the environment."""
    return R2StorageService().is_configured


def is_r2_active() -> bool:
    """Checks if Cloudflare R2 is configured AND active in settings (STORAGE_BACKEND == 'r2')."""
    return R2StorageService.is_active()


def generate_r2_presigned_upload_url(
    storage_path: str,
    content_type: str,
    expiry: int = 900,
    client=None,
    config: Optional[dict] = None,
) -> str:
    """Generates a pre-signed Cloudflare R2 PUT URL for direct-to-bucket uploads."""
    service = R2StorageService(config=config, client=client)
    return service.generate_presigned_upload_url(
        storage_path=storage_path,
        content_type=content_type,
        expiry=expiry,
    )


def list_r2_files(
    prefix: str = "",
    max_keys: int = 1000,
    client=None,
    config: Optional[dict] = None,
) -> List[dict]:
    """Lists files in the Cloudflare R2 bucket with given prefix."""
    service = R2StorageService(config=config, client=client)
    return service.list_files(prefix=prefix, max_keys=max_keys)


def delete_from_r2(
    storage_path: str,
    client=None,
    config: Optional[dict] = None,
) -> bool:
    """Deletes an object from Cloudflare R2."""
    service = R2StorageService(config=config, client=client)
    return service.delete_file(storage_path=storage_path)


def test_r2_connection(config: Optional[dict] = None) -> Tuple[bool, str]:
    """Validates Cloudflare R2 credentials by probing bucket existence."""
    service = R2StorageService(config=config)
    return service.test_connection()
