"""
Document Storage & Fetch Helpers (Compression Removed).

Files are stored in their native raw format (PDF, PNG, JPG, etc.) directly on
Cloudflare R2 or local disk without Zstandard compression.
Legacy helper functions remain for backwards compatibility.
"""
import io
import os
from typing import Optional, Tuple, Union

from django.core.files.base import ContentFile, File
from django.core.files.storage import Storage

from apps.documents.storage import (
    get_runtime_storage,
    read_file_payload,
    resolve_mime_type,
)

ZSTD_MAGIC_HEADER = b'\x28\xb5\x2f\xfd'


def is_zstd_compressed(data_bytes: bytes) -> bool:
    """Returns True if the byte sequence begins with the Zstandard frame header."""
    return bool(data_bytes and data_bytes.startswith(ZSTD_MAGIC_HEADER))


class NativeDocumentStorageService:
    """
    Object-oriented service for saving and retrieving native uncompressed files
    to/from Django storage, with legacy transparent decompression fallback.
    """

    @classmethod
    def store_native(
        cls,
        file_input: Union[bytes, io.BytesIO, File],
        storage_path: str,
        storage: Optional[Storage] = None,
    ) -> dict:
        """Stores a native uncompressed file directly into storage."""
        target_storage = storage or get_runtime_storage()
        raw_bytes, original_name, original_size = read_file_payload(file_input, default_name=storage_path)

        if original_name.endswith('.zst'):
            original_name = original_name[:-4]

        target_path = storage_path[:-4] if storage_path.lower().endswith('.zst') else storage_path
        saved_path = target_storage.save(target_path, ContentFile(raw_bytes))

        return {
            "storage_path": saved_path,
            "original_name": os.path.basename(original_name),
            "original_size": original_size,
            "compressed_size": original_size,
            "file_size": original_size,
            "compression_ratio": 1.0,
            "space_saved_percent": 0.0,
            "is_compressed": False,
        }

    @classmethod
    def fetch_native(
        cls,
        storage_path_or_file: Union[str, File],
        storage: Optional[Storage] = None,
        original_filename: Optional[str] = None,
    ) -> Tuple[bytes, str, str]:
        """Fetches raw native file bytes from storage without compression."""
        if storage is None:
            if hasattr(storage_path_or_file, 'storage') and storage_path_or_file.storage:
                target_storage = storage_path_or_file.storage
            else:
                target_storage = get_runtime_storage()
        else:
            target_storage = storage

        if isinstance(storage_path_or_file, str):
            path = storage_path_or_file
            file_obj = target_storage.open(path, 'rb')
        elif hasattr(storage_path_or_file, 'read'):
            path = getattr(storage_path_or_file, 'name', 'document')
            file_obj = storage_path_or_file
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
        else:
            raise ValueError(f"Unsupported storage_path_or_file type: {type(storage_path_or_file)}")

        try:
            raw_stored_bytes = file_obj.read()
        finally:
            if hasattr(file_obj, 'close') and isinstance(storage_path_or_file, str):
                file_obj.close()

        # Legacy fallback: decompress if previously compressed with zstd
        if is_zstd_compressed(raw_stored_bytes):
            try:
                import zstandard as zstd
                decompressor = zstd.ZstdDecompressor()
                raw_bytes = decompressor.decompress(raw_stored_bytes)
            except Exception:
                raw_bytes = raw_stored_bytes
        else:
            raw_bytes = raw_stored_bytes

        if original_filename:
            clean_filename = original_filename
        else:
            filename = os.path.basename(path)
            clean_filename = filename[:-4] if filename.lower().endswith('.zst') else filename

        mime_type = resolve_mime_type(clean_filename)
        return raw_bytes, clean_filename, mime_type


# ── Backward-Compatible Functional API ────────────────────────────────────────

def compress_and_store(
    file_input: Union[bytes, io.BytesIO, File],
    storage_path: str,
    storage: Optional[Storage] = None,
    **kwargs
) -> dict:
    """Stores raw uncompressed file content directly to active storage."""
    return NativeDocumentStorageService.store_native(file_input, storage_path, storage=storage)


def decompress_and_fetch(
    storage_path_or_file: Union[str, File],
    storage: Optional[Storage] = None,
    original_filename: Optional[str] = None
) -> Tuple[bytes, str, str]:
    """Fetches raw native file bytes from storage without compression."""
    return NativeDocumentStorageService.fetch_native(
        storage_path_or_file, storage=storage, original_filename=original_filename
    )
