import os
import uuid
import mimetypes
from django.db import models
from django.conf import settings
from simple_history.models import HistoricalRecords

import logging
from apps.documents.storage import get_runtime_storage, format_file_size, resolve_mime_type

logger = logging.getLogger(__name__)


def proof_upload_path(instance, filename):
    """Stores files under media/proofs/{activity_id}/{uuid}_{clean_filename}"""
    clean_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    return f"proofs/{instance.activity.id}/{clean_name}"


class DocumentType(models.TextChoices):
    PUBLISHED_PAPER = 'published_paper', 'Full Published Paper / Reprint'
    ACCEPTANCE_LETTER = 'acceptance_letter', 'Letter of Acceptance'
    INDEXING_PROOF = 'indexing_proof', 'Indexing Proof (Scopus / WoS Screenshot)'
    PATENT_GRANT_CERTIFICATE = 'patent_grant_certificate', 'Patent Grant / Gazette Publication'
    FDP_ATTENDANCE_CERTIFICATE = 'fdp_attendance_certificate', 'FDP / Workshop Certificate'
    OTHER = 'other', 'Supporting Evidence / Other'


class ActivityDocument(models.Model):
    """
    1:N Document proof attachments for faculty achievements.
    Stores native, uncompressed documents (PDF, PNG, JPG, WEBP) directly in Cloudflare R2
    (or local storage) with dynamic runtime storage resolution.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity = models.ForeignKey(
        'activities.Activity',
        on_delete=models.CASCADE,
        related_name='documents'
    )
    document_type = models.CharField(
        max_length=50,
        choices=DocumentType.choices,
        default=DocumentType.PUBLISHED_PAPER
    )
    title = models.CharField(max_length=255, blank=True, help_text="Optional descriptive title for this proof")
    file = models.FileField(upload_to=proof_upload_path)
    file_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    file_size = models.BigIntegerField(default=0, help_text="File size in Bytes")
    is_verified = models.BooleanField(default=False, help_text="Marked true when coordinator verifies document authenticity")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_documents'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = "Proof Document"
        verbose_name_plural = "Proof Documents"

    def __str__(self):
        return f"[{self.get_document_type_display()}] {self.file_name or self.title or str(self.id)}"

    def save(self, *args, **kwargs):
        # 1. Capture original filename and MIME type
        if self.file and not self.file_name:
            orig_base = os.path.basename(self.file.name)
            self.file_name = orig_base[:-4] if orig_base.lower().endswith('.zst') else orig_base

        if not self.mime_type and self.file_name:
            self.mime_type = mimetypes.guess_type(self.file_name)[0] or 'application/octet-stream'

        # 2. Capture accurate file size safely without raising FileNotFoundError on pending files
        if self.file and not self.file_size:
            try:
                if hasattr(self.file, 'storage') and self.file.storage.exists(self.file.name):
                    self.file_size = self.file.size
                elif hasattr(self.file, 'seek'):
                    self.file.seek(0)
                    self.file_size = len(self.file.read())
                    self.file.seek(0)
            except Exception:
                pass

        super().save(*args, **kwargs)

    @property
    def formatted_size(self):
        return format_file_size(self.file_size)

    @property
    def is_pdf(self):
        fn = (self.file_name or getattr(self.file, 'name', '')).lower()
        return self.mime_type == 'application/pdf' or fn.endswith('.pdf')

    @property
    def is_image(self):
        fn = (self.file_name or getattr(self.file, 'name', '')).lower()
        if self.mime_type and self.mime_type.startswith('image/'):
            return True
        return any(fn.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp'))

    @property
    def direct_url(self):
        return f"/api/documents/{self.id}/view_file/"

    def get_file_bytes(self):
        """Fetches raw uncompressed document bytes directly from Cloudflare R2."""
        if not self.file or not getattr(self.file, 'name', None):
            return b'', '', ''

        clean_name = self.file_name or os.path.basename(self.file.name)
        mime = self.mime_type or resolve_mime_type(clean_name)

        # 1. Fetch directly from Cloudflare R2
        try:
            from apps.documents.r2 import R2StorageService
            r2_service = R2StorageService.get_default()
            if r2_service.is_configured:
                raw, fn, resolved_mime = r2_service.fetch_file(self.file.name, original_filename=clean_name)
                return raw, fn, resolved_mime or mime
        except Exception as e:
            logger.debug(f"Direct R2 fetch attempted for {self.file.name}: {e}")

        # 2. File storage backend fallback (e.g. S3Boto3Storage or test mock)
        try:
            self.file.open('rb')
            raw = self.file.read()
            return raw, clean_name, mime
        except Exception as e:
            logger.warning(f"Unable to read file from storage for document {self.id}: {e}")
            return b'', clean_name, mime
        finally:
            try:
                self.file.close()
            except Exception:
                pass

    def get_decompressed_bytes(self):
        """Backward-compatible alias for get_file_bytes (no compression used)."""
        return self.get_file_bytes()
