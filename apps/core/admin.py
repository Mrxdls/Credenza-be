from django.contrib import admin, messages
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from .models import SystemConfiguration


@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(ModelAdmin):
    """
    Superuser-exclusive administrative console for runtime configuration.
    Controls institutional governance, accreditation policies, and file upload guardrails.
    Infrastructure credentials (Cloudflare R2, D1, database engines) are strictly
    managed via environment variables (.env) and never edited through the database.
    """
    readonly_fields = ('updated_at', 'updated_by')

    fieldsets = (
        (_("File Upload Limits & Guardrails"), {
            'description': _("Security policies for proof attachments and certificates."),
            'fields': (
                ('max_file_size_mb', 'allowed_file_extensions'),
            )
        }),
        (_("Accreditation & Institutional Governance"), {
            'description': _("Institutional headers and verification workflow controls for NAAC / NIRF reporting."),
            'fields': (
                ('institution_name', 'naac_criteria_code'),
                ('lock_approved_activities', 'require_proof_for_submission'),
            )
        }),
        (_("Audit & Change Tracking"), {
            'classes': ('collapse',),
            'fields': (
                ('updated_at', 'updated_by'),
            )
        }),
    )

    def changelist_view(self, request, extra_context=None):
        """Redirects directly to the singleton configuration change page."""
        config = SystemConfiguration.get_solo()
        return redirect(f"/admin/core/systemconfiguration/{config.id}/change/")

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        messages.success(request, _("Platform configuration updated successfully. All changes are active immediately."))

    # --- Strict Superuser-Only Permissions ---
    def has_module_permission(self, request):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)

    def has_add_permission(self, request):
        return False  # Singleton: already created

    def has_delete_permission(self, request, obj=None):
        return False  # Configuration cannot be deleted

