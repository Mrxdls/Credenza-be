import uuid
from django.db import models


class Tenant(models.Model):
    """
    Core Multi-Tenant Institution entity.
    Represents an independent university, college, or campus on the SaaS platform.
    Platform-level Supreme Admin manages tenant provisioning and access activation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Institution / College name (e.g. Poornima University, Poornima College of Engineering)"
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Short unique institutional code (e.g. PU, PCE, PIET)"
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Unique URL identifier for multi-tenant routing"
    )
    domain = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Custom domain or subdomain (e.g. pu.poornima.org)"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Platform access toggle. When False, all users of this tenant are locked out."
    )
    subscription_tier = models.CharField(
        max_length=50,
        default='standard',
        choices=[
            ('trial', 'Trial'),
            ('standard', 'Standard Institutional'),
            ('enterprise', 'Enterprise Multi-Campus'),
        ]
    )
    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    max_users = models.PositiveIntegerField(
        default=1000,
        help_text="User seat limit allocated to this tenant"
    )
    max_storage_mb = models.PositiveIntegerField(
        default=50000,
        help_text="Proof document storage quota in Megabytes (MB)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Tenant / Institution"
        verbose_name_plural = "Tenants / Institutions"

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.name} ({self.code}) - {status}"

    @property
    def current_session(self):
        """Returns the single active current academic session for this tenant, if configured."""
        return self.academic_sessions.filter(is_current=True).first()

    @property
    def users_count(self):
        return self.users.count()

    @property
    def activities_count(self):
        return self.activities.count()
