"""
Storage Engine for Faculty Achievement Proofs.

Uses Django's configured default_storage (Cloudflare R2 S3Boto3Storage or Local)
determined strictly by environment settings (.env).
Does not query the database during startup, preventing app initialization warnings.
"""
import io
import mimetypes
import os
from typing import Optional, Tuple, Union

from django.core.files.base import File
from django.core.files.storage import Storage, default_storage


def get_runtime_storage() -> Storage:
    """
    Returns the configured active storage backend (Cloudflare R2 or Local).
    Uses Django's default_storage without accessing the database at import time.
    """
    return default_storage


def format_file_size(size_bytes: Optional[int]) -> str:
    """Converts bytes into a human-readable string (e.g. 245.5 KB, 1.8 MB)."""
    if not size_bytes:
        return "0 B"
    num = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}" if unit != 'B' else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} TB"


def resolve_mime_type(filename_or_path: str, default: str = 'application/octet-stream') -> str:
    """
    Robustly resolves the MIME type for a given filename or storage key.
    Provides standard fallbacks for common document formats.
    """
    if not filename_or_path:
        return default

    clean_name = os.path.basename(filename_or_path)
    mime_type, _ = mimetypes.guess_type(clean_name)
    if mime_type:
        return mime_type

    lower = clean_name.lower()
    if lower.endswith('.pdf'):
        return 'application/pdf'
    if lower.endswith(('.jpg', '.jpeg')):
        return 'image/jpeg'
    if lower.endswith('.png'):
        return 'image/png'
    if lower.endswith('.webp'):
        return 'image/webp'
    return default


def read_file_payload(
    file_input: Union[bytes, io.BytesIO, File],
    default_name: str = "file"
) -> Tuple[bytes, str, int]:
    """
    Extracts raw bytes, derives original filename, and computes byte length
    from raw bytes, BytesIO buffer, or Django File/UploadedFile object.

    Returns:
        tuple of (raw_bytes: bytes, original_filename: str, byte_length: int)
    """
    if isinstance(file_input, bytes):
        raw_bytes = file_input
        original_name = os.path.basename(default_name)
    elif hasattr(file_input, 'read'):
        if hasattr(file_input, 'seek'):
            file_input.seek(0)
        raw_bytes = file_input.read()
        original_name = getattr(file_input, 'name', os.path.basename(default_name))
    else:
        raise ValueError(f"Unsupported file_input type: {type(file_input)}")

    return raw_bytes, os.path.basename(original_name), len(raw_bytes)

