from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class SystemConfiguration(models.Model):
    """
    Singleton system-wide institutional configuration.
    Accessible and editable EXCLUSIVELY by Superusers (is_superuser=True).
    Controls institutional governance, accreditation criteria, and upload guardrails.
    Infrastructure credentials (Cloudflare R2, D1, database engines) are strictly
    managed via environment variables (.env) and never stored in the database.
    """
    # 1. File Upload Guardrails
    max_file_size_mb = models.PositiveIntegerField(
        default=25,
        help_text="Maximum allowed single file upload size in Megabytes (MB)."
    )
    allowed_file_extensions = models.CharField(
        max_length=255,
        default=".pdf, .png, .jpg, .jpeg, .webp",
        help_text="Comma-separated allowed file extensions (e.g. .pdf, .png, .jpg)."
    )

    # 2. Institutional & Accreditation Compliance
    institution_name = models.CharField(
        max_length=255,
        default="Poornima University",
        help_text="University / Institution name shown on NAAC AQAR Criteria 3 and NIRF exports."
    )
    naac_criteria_code = models.CharField(
        max_length=100,
        default="NAAC AQAR Criteria 3.4.3 & 3.4.4",
        help_text="Official accreditation criteria reference."
    )
    lock_approved_activities = models.BooleanField(
        default=True,
        help_text="Prevent faculty members and coordinators from modifying achievements once approved."
    )
    require_proof_for_submission = models.BooleanField(
        default=False,
        help_text="Require faculty to attach at least one proof file before submitting for review."
    )

    # Audit tracking
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_system_configs'
    )

    class Meta:
        verbose_name = "Platform Configuration"
        verbose_name_plural = "Platform Configuration"

    def __str__(self):
        return f"Platform Configuration [{self.institution_name}]"

    @classmethod
    def get_solo(cls):
        """Returns the single instance of SystemConfiguration, creating it if not present."""
        obj, created = cls.objects.get_or_create(id=1)
        return obj
