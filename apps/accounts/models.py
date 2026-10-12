import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from simple_history.models import HistoricalRecords


class Department(models.Model):
    """Academic Department (e.g. Advance Computing, CSE)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='departments',
        help_text="Institutional tenant this department belongs to"
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, help_text="Short code e.g. AC, AD, CE")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Department"
        verbose_name_plural = "Departments"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'], name='unique_tenant_department_code'),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Designation(models.Model):
    """Faculty Designation (e.g. Professor, Associate Professor)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='designations',
        help_text="Institutional tenant this designation belongs to"
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, blank=True)
    priority = models.IntegerField(default=10, help_text="Order hierarchy, lower is more senior")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'name']
        verbose_name = "Designation"
        verbose_name_plural = "Designations"

    def __str__(self):
        return self.name


class Module(models.Model):
    """System Module for granular RBAC (e.g. activities, approvals, reports)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, unique=True, help_text="Unique programmatic slug")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Module"
        verbose_name_plural = "Modules"

    def __str__(self):
        return self.name


class Role(models.Model):
    """Institutional Role (e.g. Super Admin, Dean, HOD, Coordinator, Faculty)."""
    SCOPE_CHOICES = (
        ('organization', 'Organization / All Departments'),
        ('department', 'Department Only'),
        ('self', 'Own Profile & Records Only'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='roles',
        help_text="Institutional tenant this role belongs to"
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, help_text="Role slug e.g. admin, hod, coordinator, faculty")
    description = models.TextField(blank=True)
    scope = models.CharField(
        max_length=20,
        choices=SCOPE_CHOICES,
        default='self',
        help_text="Data access boundary: organization, department, or self"
    )
    rank = models.IntegerField(
        default=10,
        help_text="Hierarchy seniority level: higher rank means greater administrative authority (e.g. 100=Admin, 50=HOD, 10=Faculty)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-rank', 'name']
        verbose_name = "Role & Permission Group"
        verbose_name_plural = "Roles & Permission Groups"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'], name='unique_tenant_role_code'),
        ]

    def save(self, *args, **kwargs):
        # Auto-assign sensible default scope and rank based on role code if at defaults
        if self.code:
            code_lower = self.code.lower()
            if self.scope == 'self' and self.rank == 10:
                if code_lower in ('admin', 'super_admin', 'org_admin'):
                    self.scope = 'organization'
                    self.rank = 100
                elif code_lower in ('dean', 'org_coordinator', 'director'):
                    self.scope = 'organization'
                    self.rank = 70
                elif code_lower in ('hod', 'department_head'):
                    self.scope = 'department'
                    self.rank = 50
                elif code_lower in ('coordinator', 'dept_coordinator'):
                    self.scope = 'department'
                    self.rank = 30
                elif code_lower in ('faculty', 'member'):
                    self.scope = 'self'
                    self.rank = 10
        super().save(*args, **kwargs)

    def __str__(self):
        t_prefix = f"[{self.tenant.code}] " if self.tenant else ""
        return f"{t_prefix}{self.name} (Rank: {self.rank}, Scope: {self.scope})"


class RolePermission(models.Model):
    """Module-level permission matrix for institutional roles."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='role_permissions')
    can_view = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('role', 'module')
        verbose_name = "Role Permission"
        verbose_name_plural = "Role Permissions"

    def __str__(self):
        return f"{self.role.name} -> {self.module.name}"


from django.core.exceptions import ValidationError
from django.db.models.functions import Lower


class User(AbstractUser):
    """Extended User model representing Faculty, Coordinators, and Administrators."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users',
        help_text="Institutional tenant this user belongs to"
    )
    is_approved = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True if approved by tenant admin. Registered org users must be approved before access."
    )
    password_setup_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="One-time password setup token for newly onboarded users"
    )
    password_setup_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expiration timestamp for the one-time password setup link (7 days)"
    )
    employee_id = models.CharField(max_length=50, unique=True, null=True, blank=True, help_text="University Employee ID")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='faculty_members')
    designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, blank=True, related_name='faculty_members')
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    phone = models.CharField(max_length=20, blank=True)
    is_department_head = models.BooleanField(default=False, help_text="True if user is HOD")
    is_coordinator = models.BooleanField(default=False, help_text="True if user is Department Data Coordinator")

    history = HistoricalRecords()

    class Meta:
        ordering = ['first_name', 'last_name', 'username']
        verbose_name = "User & Faculty"
        verbose_name_plural = "Users & Faculty"
        constraints = [
            models.UniqueConstraint(
                Lower('username'),
                name='unique_case_insensitive_username'
            ),
        ]

    def get_scope(self) -> str:
        """Returns data access boundary: 'organization', 'department', or 'self'."""
        if self.is_superuser:
            return 'organization'
        if self.role:
            return self.role.scope or 'self'
        return 'self'

    def get_rank(self) -> int:
        """Returns hierarchy seniority rank (10-100). Higher rank means higher authority."""
        if self.is_superuser:
            return 1000
        if self.role:
            return self.role.rank or 10
        return 10

    def can_manage_user(self, target_user) -> bool:
        """
        Determines whether this user has hierarchical authorization to modify target_user.
        Rules:
        - Superuser can manage anyone.
        - Org Admin (scope='organization', rank >= 100) can manage any user in their tenant.
        - Department Head / Dept Scoped (scope='department'):
          * target must be in the same tenant and same department.
          * target's rank must be strictly lower than requester's rank (cannot edit peers or superiors).
        - Self Scoped:
          * can only manage own account (target_user.id == self.id).
        """
        if self.is_superuser:
            return True
        if not target_user:
            return False
        if getattr(self, 'tenant_id', None) and getattr(target_user, 'tenant_id', None):
            if self.tenant_id != target_user.tenant_id:
                return False
        if self.get_scope() == 'organization' and self.get_rank() >= 100:
            return True
        if self.get_scope() == 'organization':
            return target_user.get_rank() < self.get_rank()
        if self.get_scope() == 'department':
            if not self.department_id or self.department_id != target_user.department_id:
                return False
            return target_user.get_rank() < self.get_rank()
        if self.get_scope() == 'self':
            return self.id == target_user.id
        return False

    def clean(self):
        super().clean()
        if self.username:
            qs = User.objects.filter(username__iexact=self.username)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({'username': 'A user with that username already exists.'})

    def save(self, *args, **kwargs):
        # Auto-assign default faculty role if missing for non-superuser
        if not self.role_id and not self.is_superuser:
            default_role = None
            if self.tenant_id:
                default_role = Role.objects.filter(tenant_id=self.tenant_id, code='faculty').first()
            if not default_role:
                default_role = Role.objects.filter(code='faculty').first()
            if default_role:
                self.role = default_role

        super().save(*args, **kwargs)

        # Ensure user belongs to default Faculty auth Group
        from django.contrib.auth.models import Group
        try:
            faculty_group, _ = Group.objects.get_or_create(name='Faculty')
            if not self.groups.filter(id=faculty_group.id).exists():
                self.groups.add(faculty_group)
        except Exception:
            pass

    def __str__(self):
        full = self.get_full_name()
        emp = f" [{self.employee_id}]" if self.employee_id else ""
        return f"{full or self.username}{emp}"

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    def has_module_perm(self, module_code: str, action: str = 'view') -> bool:
        """
        Dynamically evaluates whether this user has permission to perform an action on a module.
        Actions: 'view', 'create', 'edit', 'delete', 'approve', 'export'.
        Superusers bypass all restrictions.
        """
        if not self.is_active or not self.is_approved:
            return False
        if self.is_superuser:
            return True
        if not self.role_id:
            return False
        if self.role and (self.role.rank >= 100 or self.role.code in ('admin', 'super_admin')):
            return True
        flag = f"can_{action}"
        valid_flags = {'can_view', 'can_create', 'can_edit', 'can_delete', 'can_approve', 'can_export'}
        if flag not in valid_flags:
            return False
        return self.role.permissions.filter(
            module__code=module_code,
            **{flag: True}
        ).exists()

