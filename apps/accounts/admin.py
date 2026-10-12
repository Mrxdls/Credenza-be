from django.db.models import Q
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from simple_history.admin import SimpleHistoryAdmin

from .models import Department, Designation, Module, Role, RolePermission, User


class RolePermissionInline(TabularInline):
    model = RolePermission
    extra = 0
    fields = ('module', 'can_view', 'can_create', 'can_edit', 'can_delete', 'can_approve', 'can_export')


@admin.register(Department)
class DepartmentAdmin(ModelAdmin):
    list_display = ('name', 'code', 'tenant', 'is_active', 'faculty_count', 'created_at')
    search_fields = ('name', 'code', 'tenant__name')
    list_filter = ('tenant', 'is_active')

    def faculty_count(self, obj):
        return obj.faculty_members.count()
    faculty_count.short_description = "Faculty Count"

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('tenant')
        if request.user.is_superuser:
            return qs
        if getattr(request.user, 'tenant_id', None):
            return qs.filter(tenant_id=request.user.tenant_id)
        return qs

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not obj.tenant and getattr(request.user, 'tenant_id', None):
            obj.tenant = request.user.tenant
        super().save_model(request, obj, form, change)


@admin.register(Designation)
class DesignationAdmin(ModelAdmin):
    list_display = ('name', 'code', 'tenant', 'priority', 'is_active')
    search_fields = ('name', 'code', 'tenant__name')
    list_filter = ('tenant', 'is_active')

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('tenant')
        if request.user.is_superuser:
            return qs
        if getattr(request.user, 'tenant_id', None):
            return qs.filter(Q(tenant_id=request.user.tenant_id) | Q(tenant__isnull=True))
        return qs

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not obj.tenant and getattr(request.user, 'tenant_id', None):
            obj.tenant = request.user.tenant
        super().save_model(request, obj, form, change)


@admin.register(Module)
class ModuleAdmin(ModelAdmin):
    list_display = ('name', 'code', 'description')
    search_fields = ('name', 'code')


@admin.register(Role)
class RoleAdmin(ModelAdmin):
    list_display = ('name', 'code', 'tenant', 'description', 'user_count')
    list_filter = ('tenant',)
    search_fields = ('name', 'code', 'tenant__name')
    inlines = [RolePermissionInline]

    def user_count(self, obj):
        return obj.users.count()
    user_count.short_description = "Assigned Users"

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('tenant')
        if request.user.is_superuser:
            return qs
        if getattr(request.user, 'tenant_id', None):
            return qs.filter(Q(tenant_id=request.user.tenant_id) | Q(tenant__isnull=True))
        return qs

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not obj.tenant and getattr(request.user, 'tenant_id', None):
            obj.tenant = request.user.tenant
        super().save_model(request, obj, form, change)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin, SimpleHistoryAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    list_display = ('username', 'employee_id', 'get_full_name', 'tenant', 'department', 'designation', 'role', 'is_approved', 'is_staff', 'is_active')
    list_filter = ('tenant', 'is_approved', 'is_active', 'department', 'designation', 'role', 'is_staff', 'is_department_head', 'is_coordinator')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'employee_id', 'tenant__name')
    ordering = ('first_name', 'last_name', 'username')
    actions = [
        'approve_selected_users',
        'activate_selected_users',
        'deactivate_selected_users',
        'assign_faculty_role',
        'assign_coordinator_role',
        'assign_hod_role',
    ]

    @action(description="✓ Approve and Activate selected registered user(s)")
    def approve_selected_users(self, request, queryset):
        count = queryset.update(is_approved=True, is_active=True)
        self.message_user(request, f"Successfully approved and activated {count} user(s).", level=messages.SUCCESS)

    @action(description="✓ Activate login for selected user(s)")
    def activate_selected_users(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"Activated login for {count} user(s).", level=messages.SUCCESS)

    @action(description="✗ Suspend / Deactivate login for selected user(s)")
    def deactivate_selected_users(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {count} user(s).", level=messages.WARNING)

    @action(description="Assign Role: Faculty")
    def assign_faculty_role(self, request, queryset):
        self._assign_role(request, queryset, 'faculty')

    @action(description="Assign Role: Coordinator")
    def assign_coordinator_role(self, request, queryset):
        self._assign_role(request, queryset, 'coordinator')

    @action(description="Assign Role: HOD")
    def assign_hod_role(self, request, queryset):
        self._assign_role(request, queryset, 'hod')

    def _assign_role(self, request, queryset, role_code):
        tenant = getattr(request.user, 'tenant', None)
        role = Role.objects.filter(code=role_code, tenant=tenant).first() or Role.objects.filter(code=role_code, tenant__isnull=True).first()
        if not role:
            self.message_user(request, f"Role with code '{role_code}' does not exist.", level=messages.ERROR)
            return
        count = queryset.update(role=role)
        self.message_user(request, f"Successfully assigned role '{role.name}' to {count} user(s).", level=messages.SUCCESS)

    def get_fieldsets(self, request, obj=None):
        base_fieldsets = [
            (None, {'fields': ('username', 'password')}),
            ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'phone')}),
            ('Institutional Assignment', {
                'fields': ('employee_id', 'department', 'designation', 'role', 'is_department_head', 'is_coordinator')
            }),
            ('Permissions & Staff Status', {
                'fields': ('is_approved', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            }),
            ('Important dates', {'fields': ('last_login', 'date_joined')}),
        ]
        if request.user.is_superuser:
            base_fieldsets.insert(3, (
                'Platform & Multi-Tenancy (Super Admin)', {
                    'fields': ('tenant',),
                    'description': 'Super Admin controls institutional tenant mapping.'
                }
            ))
        return base_fieldsets

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('department', 'designation', 'role', 'tenant')
        if request.user.is_superuser:
            return qs
        if getattr(request.user, 'tenant_id', None):
            return qs.filter(tenant_id=request.user.tenant_id)
        return qs

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.is_superuser = False
            if getattr(request.user, 'tenant_id', None):
                obj.tenant = request.user.tenant
        super().save_model(request, obj, form, change)


