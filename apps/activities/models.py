import uuid
from django.db import models, transaction
from django.conf import settings
from simple_history.models import HistoricalRecords


class AcademicSession(models.Model):
    """
    Academic Year/Session (e.g. 2025-26, 2026-27).
    Enforces strictly ONE active current session per tenant at any given time.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='academic_sessions',
        help_text="Institutional tenant this academic session belongs to"
    )
    name = models.CharField(max_length=50, help_text="e.g. 2025-2026")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']
        verbose_name = "Academic Session"
        verbose_name_plural = "Academic Sessions"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'name'], name='unique_tenant_session_name'),
        ]

    def __str__(self):
        return f"{self.name} {'(Current)' if self.is_current else ''}".strip()

    @transaction.atomic
    def save(self, *args, **kwargs):
        """
        Guarantees that on each tenant level there is strictly ONE current session.
        If this session is marked current (is_current=True), all other sessions for this
        tenant are automatically and atomically marked inactive (is_current=False).
        """
        if self.is_current:
            qs = AcademicSession.objects.filter(is_current=True)
            if self.tenant_id:
                qs = qs.filter(tenant_id=self.tenant_id)
            else:
                qs = qs.filter(tenant__isnull=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            qs.update(is_current=False)
        super().save(*args, **kwargs)


class ActivityType(models.TextChoices):
    JOURNAL_PUBLICATION = 'journal_publication', 'Journal Publication'
    CONFERENCE_PUBLICATION = 'conference_publication', 'Conference Publication'
    PATENT = 'patent', 'Patent Publication / Grant'
    FACULTY_PARTICIPATION = 'faculty_participation', 'Faculty Development / Participation'


class ActivityStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    SUBMITTED = 'submitted', 'Submitted for Review'
    UNDER_REVIEW = 'under_review', 'Under Review'
    APPROVED = 'approved', 'Approved & Verified'
    REJECTED = 'rejected', 'Rejected'


class Activity(models.Model):
    """
    Polymorphic core entity representing any faculty achievement.
    
    ASCII State Machine:
    [draft] ──(submit)──▶ [submitted] ──(review)──▶ [under_review]
                                                           │
                                   ┌───────────────────────┴───────────────────────┐
                                   ▼                                               ▼
                              [approved]                                      [rejected]
                        (requires >=1 proof doc)                       (requires rejection_reason)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='activities',
        help_text="Institutional tenant this achievement belongs to"
    )
    faculty = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='activities',
        help_text="Primary submitting faculty member"
    )
    academic_session = models.ForeignKey(
        AcademicSession,
        on_delete=models.PROTECT,
        related_name='activities'
    )
    activity_type = models.CharField(
        max_length=40,
        choices=ActivityType.choices,
        db_index=True
    )
    title = models.CharField(max_length=600, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=ActivityStatus.choices,
        default=ActivityStatus.DRAFT,
        db_index=True
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Mandatory feedback when an activity is rejected"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Polymorphic achievement attributes based on activity_type"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_activities'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Faculty Achievement"
        verbose_name_plural = "Faculty Achievements"
        indexes = [
            models.Index(fields=['faculty', 'academic_session', 'activity_type']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.get_activity_type_display()}] {self.title[:80]} ({self.faculty.display_name})"

    def clean(self):
        super().clean()
        if self.pk:
            orig = Activity.objects.filter(pk=self.pk).values(
                'status', 'title', 'activity_type', 'faculty_id', 'academic_session_id', 'metadata'
            ).first()
            if orig and orig['status'] == ActivityStatus.APPROVED:
                if not getattr(self, '_skip_lock_check', False):
                    changed = []
                    if orig['title'] != self.title:
                        changed.append('title')
                    if orig['activity_type'] != self.activity_type:
                        changed.append('activity_type')
                    if orig['faculty_id'] != self.faculty_id:
                        changed.append('faculty')
                    if orig['academic_session_id'] != self.academic_session_id:
                        changed.append('academic_session')
                    if orig['metadata'] != self.metadata:
                        changed.append('metadata')
                    if changed:
                        from django.core.exceptions import ValidationError
                        raise ValidationError(
                            f"Locked Record: Approved achievements cannot be modified. Field(s) locked: {', '.join(changed)}"
                        )

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.faculty_id and hasattr(self.faculty, 'tenant_id') and self.faculty.tenant_id:
            self.tenant_id = self.faculty.tenant_id
        if not getattr(self, '_skip_lock_check', False) and not kwargs.get('update_fields'):
            self.clean()
        super().save(*args, **kwargs)

    @property
    def has_proof(self):
        """Returns True if this activity has at least one attached proof document."""
        return self.documents.exists()

    @property
    def department(self):
        return self.faculty.department



class ActivityAuthor(models.Model):
    """Relational co-authorship linking multiple university faculty or external authors."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name='activity_authors'
    )
    faculty = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='coauthored_activities',
        help_text="Internal faculty account if co-author is from Poornima University"
    )
    author_name = models.CharField(max_length=255, help_text="Verbatim author name as published")
    author_order = models.PositiveSmallIntegerField(default=1)
    is_corresponding = models.BooleanField(default=False)
    affiliation = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['author_order']
        verbose_name = "Activity Co-Author"
        verbose_name_plural = "Activity Co-Authors"

    def __str__(self):
        return f"{self.author_order}. {self.author_name} ({self.activity.title[:30]})"
