from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display, action

from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(ModelAdmin):
    list_display = (
        'name_display',
        'code',
        'domain',
        'subscription_badge',
        'status_badge',
        'users_badge',
        'activities_badge',
        'created_at',
    )
    list_filter = (
        'is_active',
        'subscription_tier',
        'created_at',
    )
    search_fields = (
        'name',
        'code',
        'slug',
        'domain',
        'contact_name',
        'contact_email',
    )
    actions = [
        'activate_tenants',
        'deactivate_tenants',
    ]

    fieldsets = (
        ("Tenant Core Identity", {
            'fields': (
                ('name', 'code'),
                ('slug', 'domain'),
                ('is_active', 'subscription_tier'),
            )
        }),
        ("Contact & Administrative Details", {
            'fields': (
                ('contact_name', 'contact_email', 'contact_phone'),
                'address',
            )
        }),
        ("Resource Quotas & Limits", {
            'fields': (
                ('max_users', 'max_storage_mb'),
            )
        }),
    )

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    @display(description="Tenant / Institution", header=True)
    def name_display(self, obj):
        current_sess = obj.current_session
        sess_label = f"Current Session: {current_sess.name}" if current_sess else "No Active Session"
        return [
            obj.name,
            sess_label,
            obj.code[:3].upper() if obj.code else "TNT",
        ]

    @display(
        description="Access Status",
        label={
            True: "success",
            False: "danger",
        }
    )
    def status_badge(self, obj):
        return obj.is_active, "Active / Enabled" if obj.is_active else "Suspended / Inactive"

    @display(
        description="Tier",
        label={
            'trial': "default",
            'standard': "info",
            'enterprise': "primary",
        }
    )
    def subscription_badge(self, obj):
        return obj.subscription_tier, obj.get_subscription_tier_display()

    @display(description="Faculty / Users")
    def users_badge(self, obj):
        count = obj.users.count()
        return f"{count} / {obj.max_users}"

    @display(description="Achievements")
    def activities_badge(self, obj):
        count = obj.activities.count()
        return f"{count} records"

    @action(description="✓ Approve & Activate selected tenant(s) and administrators")
    def activate_tenants(self, request, queryset):
        count = queryset.update(is_active=True)
        from apps.accounts.models import User
        users_count = User.objects.filter(tenant__in=queryset, is_staff=True).update(is_approved=True, is_active=True)
        self.message_user(
            request,
            f"Successfully activated {count} tenant(s) and approved {users_count} administrator(s).",
            level=messages.SUCCESS
        )

    @action(description="✗ Suspend & Deactivate selected tenant(s)")
    def deactivate_tenants(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"Successfully deactivated {count} tenant(s). Users from these tenants are now locked out.", level=messages.WARNING)
