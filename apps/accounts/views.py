from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import update_session_auth_hash, authenticate, login, logout
from django.contrib import messages
from django.shortcuts import render, redirect
from django.db.models import Q
from rest_framework import viewsets, permissions, filters, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.tenants.permissions import is_super_admin, IsTenantActive
from .permissions import HasModulePermission
from .models import Department, Designation, User, Role, RolePermission, Module
from .serializers import (
    DepartmentSerializer,
    DesignationSerializer,
    UserMinimalSerializer,
    UserSerializer,
    RoleSerializer,
    RolePermissionSerializer,
    ModuleSerializer,
)


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.filter(is_active=True)
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'accounts'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'code', 'created_at']
    ordering = ('name', 'id')

    def get_queryset(self):
        user = self.request.user
        qs = Department.objects.filter(is_active=True).select_related('tenant')
        if user.is_superuser:
            return qs
        if getattr(user, 'tenant_id', None):
            qs = qs.filter(tenant_id=user.tenant_id)

        scope = user.get_scope()
        has_accounts_view = user.has_module_perm('accounts', 'view')
        # Org Admin, Dean, or anyone with accounts view sees all departments in the tenant
        if scope == 'organization' or user.get_rank() >= 70 or has_accounts_view:
            return qs
        # Department or self scope (HOD, Coordinator, Faculty):
        # Instead of 403, show their own assigned department
        elif scope in ('department', 'self'):
            if user.department_id:
                return qs.filter(id=user.department_id)
            return qs.none()
        return qs.none()

    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can create departments.")
        if getattr(user, 'tenant_id', None):
            serializer.save(tenant=user.tenant)
        else:
            serializer.save()

    def perform_update(self, serializer):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can modify departments.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can delete departments.")
        instance.delete()


class DesignationViewSet(viewsets.ModelViewSet):
    queryset = Designation.objects.filter(is_active=True)
    serializer_class = DesignationSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'accounts'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['priority', 'name', 'code']
    ordering = ('-priority', 'name', 'id')

    def get_queryset(self):
        user = self.request.user
        qs = Designation.objects.filter(is_active=True).select_related('tenant')
        if user.is_superuser:
            return qs
        if getattr(user, 'tenant_id', None):
            return qs.filter(Q(tenant_id=user.tenant_id) | Q(tenant__isnull=True))
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can create designations.")
        if getattr(user, 'tenant_id', None):
            serializer.save(tenant=user.tenant)
        else:
            serializer.save()

    def perform_update(self, serializer):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can modify designations.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can delete designations.")
        instance.delete()


class ModuleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Module.objects.all()
    serializer_class = ModuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'code']
    ordering = ('name', 'id')


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all().prefetch_related('permissions__module')
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'accounts'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'code']
    ordering = ('name', 'id')

    def get_queryset(self):
        user = self.request.user
        qs = Role.objects.all().prefetch_related('permissions__module').select_related('tenant')
        if user.is_superuser:
            return qs
        if getattr(user, 'tenant_id', None):
            qs = qs.filter(Q(tenant_id=user.tenant_id) | Q(tenant__isnull=True))

        scope = user.get_scope()
        has_accounts_view = user.has_module_perm('accounts', 'view')
        # Org admin, dean, coordinator, HOD or user with accounts perm can see tenant roles
        if scope == 'organization' or user.get_rank() >= 30 or has_accounts_view:
            return qs
        # Faculty (scope self) sees only their own role
        if user.role_id:
            return qs.filter(id=user.role_id)
        return qs.filter(code='faculty')

    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can create institutional roles.")
        role = serializer.save(tenant=getattr(user, 'tenant', None))
        # Ensure default permission records exist for each registered domain module
        for mod in Module.objects.all():
            RolePermission.objects.get_or_create(role=role, module=mod)

    def perform_update(self, serializer):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can modify institutional roles.")
        instance = serializer.instance
        if instance.tenant_id is None and not user.is_superuser:
            raise PermissionDenied("Default system roles cannot be modified directly. Use 'Clone' to customize for your institution.")
        if not user.is_superuser and getattr(user, 'tenant_id', None) != instance.tenant_id:
            raise PermissionDenied("You can only modify roles belonging to your institution.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if not user.is_superuser and user.get_rank() < 100:
            raise PermissionDenied("Only Organization Administrators can delete institutional roles.")
        if instance.tenant_id is None and not user.is_superuser:
            raise PermissionDenied("Default system roles cannot be deleted.")
        if not user.is_superuser and getattr(user, 'tenant_id', None) != instance.tenant_id:
            raise PermissionDenied("You can only delete roles belonging to your institution.")
        instance.delete()

    @action(detail=True, methods=['post'], url_path='clone')
    def clone(self, request, pk=None):
        """Clones a global standard role or existing role into a tenant-specific customizable role."""
        if not request.user.is_superuser and request.user.get_rank() < 100:
            return Response({"error": "Only Organization Administrators can clone institutional roles."}, status=status.HTTP_403_FORBIDDEN)
        source_role = self.get_object()
        tenant = getattr(request.user, 'tenant', None)
        if not tenant and not request.user.is_superuser:
            return Response({"error": "Tenant required to clone role."}, status=status.HTTP_400_BAD_REQUEST)

        # Generate a unique code
        base_code = f"{source_role.code}_custom"
        code = base_code
        counter = 1
        while Role.objects.filter(tenant=tenant, code=code).exists():
            code = f"{base_code}_{counter}"
            counter += 1

        new_role = Role.objects.create(
            tenant=tenant,
            name=f"{source_role.name} (Custom)",
            code=code,
            description=source_role.description or f"Customized version of {source_role.name}",
            scope=source_role.scope,
            rank=source_role.rank
        )
        for perm in source_role.permissions.all():
            RolePermission.objects.create(
                role=new_role,
                module=perm.module,
                can_view=perm.can_view,
                can_create=perm.can_create,
                can_edit=perm.can_edit,
                can_delete=perm.can_delete,
                can_approve=perm.can_approve,
                can_export=perm.can_export
            )
        serializer = self.get_serializer(new_role)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post', 'patch'], url_path='set-permissions')
    def set_permissions(self, request, pk=None):
        if not request.user.is_superuser and request.user.get_rank() < 100:
            return Response({"error": "Only Organization Administrators can configure role permissions."}, status=status.HTTP_403_FORBIDDEN)
        role = self.get_object()
        if role.tenant_id is None and not request.user.is_superuser:
            return Response({"error": "Cannot modify permissions on global default roles. Clone this role first to customize permissions."}, status=status.HTTP_403_FORBIDDEN)

        perms_data = request.data.get('permissions', [])
        for p in perms_data:
            mod_code = p.get('module_code')
            if not mod_code:
                continue
            module = Module.objects.filter(code=mod_code).first()
            if not module:
                continue
            RolePermission.objects.update_or_create(
                role=role,
                module=module,
                defaults={
                    'can_view': bool(p.get('can_view', False)),
                    'can_create': bool(p.get('can_create', False)),
                    'can_edit': bool(p.get('can_edit', False)),
                    'can_delete': bool(p.get('can_delete', False)),
                    'can_approve': bool(p.get('can_approve', False)),
                    'can_export': bool(p.get('can_export', False)),
                }
            )
        serializer = self.get_serializer(role)
        return Response(serializer.data)


class RolePermissionViewSet(viewsets.ModelViewSet):
    queryset = RolePermission.objects.all().select_related('role', 'module')
    serializer_class = RolePermissionSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'accounts'
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['role', 'module']
    ordering = ('role__name', 'module__name', 'id')

    def get_queryset(self):
        user = self.request.user
        qs = RolePermission.objects.all().select_related('role', 'module')
        if is_super_admin(self.request) or user.is_superuser:
            return qs
        if getattr(user, 'tenant_id', None):
            return qs.filter(Q(role__tenant_id=user.tenant_id) | Q(role__tenant__isnull=True))
        return qs


from rest_framework.renderers import BaseRenderer

class BinaryFileRenderer(BaseRenderer):
    media_type = '*/*'
    format = 'any'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class UserViewSet(viewsets.ModelViewSet):
    """
    User & Faculty directory listing with department, designation, and role scoping.
    Includes bulk onboarding, role assignment, and user approval workflows.
    """
    queryset = User.objects.all().select_related('department', 'designation', 'role', 'tenant')
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'accounts'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['department', 'designation', 'role', 'is_approved', 'is_active', 'is_department_head', 'is_coordinator']
    search_fields = ['username', 'first_name', 'last_name', 'employee_id', 'email']
    ordering_fields = ['first_name', 'last_name', 'employee_id', 'date_joined']
    ordering = ('first_name', 'last_name', 'id')

    def perform_content_negotiation(self, request, force=False):
        if getattr(self, 'action', None) == 'sample_template':
            return (BinaryFileRenderer(), BinaryFileRenderer.media_type)
        return super().perform_content_negotiation(request, force=force)

    def get_queryset(self):
        user = self.request.user
        qs = User.objects.all().select_related('department', 'designation', 'role', 'tenant')
        if user.is_superuser:
            return qs
        if getattr(user, 'tenant_id', None):
            qs = qs.filter(tenant_id=user.tenant_id)

        scope = user.get_scope()
        if scope == 'organization' or user.get_rank() >= 100:
            return qs
        elif scope == 'department':
            if user.department_id:
                return qs.filter(department_id=user.department_id)
            return qs.none()
        else:
            return qs.filter(id=user.id)

    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_superuser:
            if user.get_scope() == 'department' and user.get_rank() < 100:
                dept = serializer.validated_data.get('department')
                if dept and dept.id != user.department_id:
                    raise PermissionDenied("You can only onboard employees into your own department.")
                if not dept and user.department:
                    serializer.validated_data['department'] = user.department

                new_role = serializer.validated_data.get('role')
                if new_role and new_role.rank >= user.get_rank():
                    raise PermissionDenied(f"You cannot assign a role with seniority rank ({new_role.rank}) equal to or higher than your own ({user.get_rank()}).")

        if getattr(user, 'tenant_id', None):
            serializer.save(tenant=user.tenant)
        else:
            serializer.save()

    def perform_update(self, serializer):
        user = self.request.user
        target = serializer.instance
        if not user.is_superuser and getattr(user, 'tenant_id', None) and target.tenant_id != user.tenant_id:
            raise PermissionDenied("Cannot modify users from another institution.")

        if not user.can_manage_user(target):
            if user.get_scope() == 'department':
                if target.department_id != user.department_id:
                    raise PermissionDenied("You can only modify employees within your department.")
                raise PermissionDenied("You cannot modify users of equal or higher seniority rank.")
            raise PermissionDenied("You do not have permission to modify this user.")

        if not user.is_superuser:
            serializer.validated_data.pop('is_superuser', None)

        new_role = serializer.validated_data.get('role')
        if new_role and not user.is_superuser and user.get_rank() < 100:
            if new_role.rank >= user.get_rank():
                raise PermissionDenied(f"You cannot assign a role with seniority rank ({new_role.rank}) equal to or higher than your own ({user.get_rank()}).")

        new_dept = serializer.validated_data.get('department')
        if new_dept and user.get_scope() == 'department' and user.get_rank() < 100:
            if new_dept.id != user.department_id:
                raise PermissionDenied("You cannot transfer employees to another department.")

        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if not user.is_superuser and getattr(user, 'tenant_id', None) and instance.tenant_id != user.tenant_id:
            raise PermissionDenied("Cannot delete users from another institution.")
        if instance.id == user.id:
            raise PermissionDenied("Cannot delete your own account.")
        if not user.can_manage_user(instance):
            raise PermissionDenied("You do not have permission to delete this user.")
        instance.delete()

    @action(detail=False, methods=['get'], url_path='sample-template')
    def sample_template(self, request):
        """Downloads sample CSV or Excel file for bulk user import."""
        from django.http import HttpResponse
        from .services.user_import_service import UserImportService
        fmt = request.query_params.get('format', 'csv')
        buf, filename, content_type = UserImportService.generate_sample_template(fmt)
        response = HttpResponse(buf.getvalue(), content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request):
        """Bulk imports users from 3-column CSV/XLSX and sends 7-day one-time password setup links."""
        from .services.user_import_service import UserImportService
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({"error": "No file uploaded. Please upload a CSV or Excel file."}, status=status.HTTP_400_BAD_REQUEST)

        tenant = request.user.tenant
        if not tenant and not is_super_admin(request):
            return Response({"error": "No institutional tenant associated with your account."}, status=status.HTTP_400_BAD_REQUEST)

        base_url = f"{request.scheme}://{request.get_host()}"
        result = UserImportService.bulk_import_users(
            uploaded_file=uploaded_file,
            tenant=tenant,
            creator_user=request.user,
            base_url=base_url
        )
        return Response(result, status=status.HTTP_201_CREATED if result['created'] > 0 else status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='bulk-assign-role')
    def bulk_assign_role(self, request):
        """Batch assigns a role to multiple selected users within the institutional tenant."""
        user_ids = request.data.get('user_ids', [])
        role_id = request.data.get('role_id')
        if not user_ids or not isinstance(user_ids, list):
            return Response({"error": "Field 'user_ids' must be a non-empty list of UUIDs."}, status=status.HTTP_400_BAD_REQUEST)
        if not role_id:
            return Response({"error": "Field 'role_id' is required."}, status=status.HTTP_400_BAD_REQUEST)

        role = Role.objects.filter(id=role_id).first()
        if not role:
            return Response({"error": f"Role '{role_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

        # Enforce tenant isolation on role assignment
        if not is_super_admin(request) and request.user.tenant_id:
            if role.tenant_id and role.tenant_id != request.user.tenant_id:
                return Response({"error": "Cannot assign a role belonging to another institution."}, status=status.HTTP_403_FORBIDDEN)
            users_qs = User.objects.filter(id__in=user_ids, tenant_id=request.user.tenant_id)
        else:
            users_qs = User.objects.filter(id__in=user_ids)

        # Seniority & Departmental RBAC Guards
        if not request.user.is_superuser and request.user.get_rank() < 100:
            if role.rank >= request.user.get_rank():
                return Response(
                    {"error": f"You cannot assign a role with seniority rank ({role.rank}) equal to or higher than your own ({request.user.get_rank()})."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if request.user.get_scope() == 'department':
                invalid_dept_users = users_qs.exclude(department_id=request.user.department_id)
                if invalid_dept_users.exists():
                    return Response(
                        {"error": "You can only assign roles to employees within your own department."},
                        status=status.HTTP_403_FORBIDDEN
                    )

            # Prevent modifying peers or superiors
            for target in users_qs:
                if target.get_rank() >= request.user.get_rank():
                    return Response(
                        {"error": f"Cannot modify user '{target.username}' with equal or higher seniority rank."},
                        status=status.HTTP_403_FORBIDDEN
                    )

        updated = users_qs.update(role=role)
        return Response({
            "success": True,
            "updated_count": updated,
            "role": {"id": str(role.id), "name": role.name, "code": role.code},
            "message": f"Successfully assigned role '{role.name}' to {updated} user(s)."
        })

    @action(detail=True, methods=['post'], url_path='approve')
    def approve_user(self, request, pk=None):
        """Approves and activates a registered institutional user."""
        user = self.get_object()
        user.is_approved = True
        user.is_active = True
        user.save(update_fields=['is_approved', 'is_active'])
        return Response({
            "success": True,
            "message": f"User '{user.email}' has been approved and activated."
        })

    @action(detail=False, methods=['post'], url_path='bulk-approve')
    def bulk_approve(self, request):
        """Batch approves and activates registered institutional users."""
        user_ids = request.data.get('user_ids', [])
        if not user_ids or not isinstance(user_ids, list):
            return Response({"error": "Field 'user_ids' must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset().filter(id__in=user_ids)
        updated = qs.update(is_approved=True, is_active=True)
        return Response({
            "success": True,
            "updated_count": updated,
            "message": f"Successfully approved and activated {updated} user(s)."
        })


class SetupPasswordView(APIView):
    """
    Public endpoint for newly onboarded faculty to establish their password using a 7-day token.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from .services.user_import_service import UserImportService
        uid = request.data.get('uid')
        token = request.data.get('token')
        password = request.data.get('password')
        if not uid or not token or not password:
            return Response({"error": "Fields 'uid', 'token', and 'password' are required."}, status=status.HTTP_400_BAD_REQUEST)

        ok, msg, user = UserImportService.complete_password_setup(uid, token, password)
        if not ok:
            return Response({"error": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "success": True,
            "message": msg,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "name": user.get_full_name() or user.username,
            }
        })


class LoginAPIView(APIView):
    """
    REST API endpoint for authenticating users (Supreme Admin, Tenant Admin, and Faculty).
    Establishes session cookie and returns full serialized user details.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        username = str(request.data.get('username') or '').strip()
        password = str(request.data.get('password') or '')

        if not username or not password:
            return Response(
                {"error": "Both username and password are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=username, password=password)
        if not user:
            return Response(
                {"error": "Invalid credentials. Please verify your username and password."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {"error": "This account is inactive. Please contact your system administrator."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not getattr(user, 'is_approved', True):
            return Response(
                {"error": "Your account is pending institutional administrator approval."},
                status=status.HTTP_403_FORBIDDEN
            )

        if user.tenant and not user.tenant.is_active:
            return Response(
                {"error": "Your institution is inactive or suspended. Access denied."},
                status=status.HTTP_403_FORBIDDEN
            )

        login(request, user)

        serializer = UserMinimalSerializer(user)
        data = serializer.data
        data['phone'] = user.phone
        data['role'] = user.role.name if user.role else ("Superuser" if user.is_superuser else "Faculty")
        data['role_code'] = user.role.code if user.role else ("superuser" if user.is_superuser else "faculty")
        data['is_staff'] = user.is_staff
        data['is_superuser'] = user.is_superuser
        data['scope'] = user.get_scope()
        data['rank'] = user.get_rank()
        data['is_approved'] = user.is_approved
        data['is_department_head'] = user.is_department_head
        data['is_coordinator'] = user.is_coordinator
        perms = {}
        if user.role:
            for p in user.role.permissions.select_related('module'):
                perms[p.module.code] = {
                    'can_view': p.can_view,
                    'can_create': p.can_create,
                    'can_edit': p.can_edit,
                    'can_delete': p.can_delete,
                    'can_approve': p.can_approve,
                    'can_export': p.can_export,
                }
        data['permissions'] = perms
        data['tenant'] = {
            'id': str(user.tenant.id),
            'name': user.tenant.name,
            'code': user.tenant.code,
            'is_active': user.tenant.is_active,
            'subscription_tier': user.tenant.subscription_tier,
        } if user.tenant else None

        return Response({
            "success": True,
            "message": "Authenticated successfully.",
            "user": data,
        })


class LogoutAPIView(APIView):
    """Logs out user and invalidates session."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        logout(request)
        return Response({"success": True, "message": "Logged out successfully."})


class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTenantActive]

    def get(self, request):
        serializer = UserMinimalSerializer(request.user)
        data = serializer.data
        data['phone'] = request.user.phone
        data['role'] = {
            'id': str(request.user.role.id),
            'name': request.user.role.name,
            'code': request.user.role.code,
            'scope': request.user.role.scope,
            'rank': request.user.role.rank,
        } if request.user.role else None
        data['role_name'] = request.user.role.name if request.user.role else ("Superuser" if request.user.is_superuser else "Faculty")
        data['role_code'] = request.user.role.code if request.user.role else ("super_admin" if request.user.is_superuser else "faculty")
        data['is_staff'] = request.user.is_staff
        data['is_superuser'] = request.user.is_superuser
        data['scope'] = request.user.get_scope()
        data['rank'] = request.user.get_rank()
        data['is_approved'] = request.user.is_approved
        data['is_department_head'] = request.user.is_department_head
        data['is_coordinator'] = request.user.is_coordinator
        perms = {}
        if request.user.role:
            for p in request.user.role.permissions.select_related('module'):
                perms[p.module.code] = {
                    'can_view': p.can_view,
                    'can_create': p.can_create,
                    'can_edit': p.can_edit,
                    'can_delete': p.can_delete,
                    'can_approve': p.can_approve,
                    'can_export': p.can_export,
                }
        data['permissions'] = perms
        data['department'] = {
            'id': str(request.user.department.id),
            'name': request.user.department.name,
            'code': request.user.department.code,
        } if request.user.department else None
        data['designation'] = {
            'id': str(request.user.designation.id),
            'name': request.user.designation.name,
        } if request.user.designation else None
        data['tenant'] = {
            'id': str(request.user.tenant.id),
            'name': request.user.tenant.name,
            'code': request.user.tenant.code,
            'is_active': request.user.tenant.is_active,
        } if request.user.tenant else None
        return Response(data)


    def patch(self, request):
        user = request.user
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        phone = request.data.get('phone')
        update_fields = []
        if first_name is not None:
            user.first_name = str(first_name).strip()
            update_fields.append('first_name')
        if last_name is not None:
            user.last_name = str(last_name).strip()
            update_fields.append('last_name')
        if phone is not None:
            user.phone = str(phone).strip()
            update_fields.append('phone')
        if update_fields:
            user.save(update_fields=update_fields)
        return self.get(request)


class ChangePasswordView(APIView):
    """
    API endpoint for authenticated users to update their password.
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantActive]

    def post(self, request):
        user = request.user
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')

        if not current_password or not new_password or not confirm_password:
            return Response(
                {"error": "Fields 'current_password', 'new_password', and 'confirm_password' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not user.check_password(current_password):
            return Response(
                {"error": "The current password you entered is incorrect."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if len(new_password) < 8:
            return Response(
                {"error": "New password must be at least 8 characters long."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if new_password != confirm_password:
            return Response(
                {"error": "New password and confirmation password do not match."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save(update_fields=['password'])
        update_session_auth_hash(request, user)
        return Response({
            "success": True,
            "message": "Password changed successfully."
        })


class UserProfileView(LoginRequiredMixin, View):
    """
    Interactive web profile dashboard for Faculty, Coordinators, and Institutional Administrators.
    Provides personal details, role badges, institutional affiliation, accreditation statistics,
    profile editing, and secure password management.
    """
    login_url = '/admin/login/'

    def get(self, request):
        context = self._get_profile_context(request)
        return render(request, 'accounts/profile.html', context)

    def post(self, request):
        user = request.user
        form_action = request.POST.get('form_action')

        if form_action == 'update_profile':
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            phone = request.POST.get('phone', '').strip()

            user.first_name = first_name
            user.last_name = last_name
            user.phone = phone
            user.save(update_fields=['first_name', 'last_name', 'phone'])
            messages.success(request, "Your profile details have been successfully updated.")
            return redirect('user-profile')

        elif form_action == 'change_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not current_password or not new_password or not confirm_password:
                messages.error(request, "All password fields are required.")
            elif not user.check_password(current_password):
                messages.error(request, "The current password you entered is incorrect.")
            elif len(new_password) < 8:
                messages.error(request, "Your new password must be at least 8 characters long.")
            elif new_password != confirm_password:
                messages.error(request, "New password and confirmation password do not match.")
            else:
                user.set_password(new_password)
                user.save(update_fields=['password'])
                update_session_auth_hash(request, user)
                messages.success(request, "Your password has been changed successfully.")
            return redirect('user-profile')

        messages.error(request, "Unrecognized action.")
        return redirect('user-profile')

    def _get_profile_context(self, request):
        user = request.user
        from apps.activities.models import Activity, ActivityType, ActivityStatus
        from apps.tenants.models import Tenant

        is_super = is_super_admin(request)
        stats = {}
        recent_activities = []

        if is_super:
            stats['total_tenants'] = Tenant.objects.count()
            stats['active_tenants'] = Tenant.objects.filter(is_active=True).count()
            stats['total_users'] = User.objects.count()
            stats['total_activities'] = Activity.objects.count()
            stats['pending_tenants'] = Tenant.objects.filter(is_active=False).count()
            recent_activities = Activity.objects.select_related('academic_session', 'tenant', 'faculty').order_by('-created_at')[:5]
        else:
            # Faculty & Institutional users
            user_activities = Activity.objects.filter(faculty=user)
            stats['total_submissions'] = user_activities.count()
            stats['approved_count'] = user_activities.filter(status=ActivityStatus.APPROVED).count()
            stats['pending_count'] = user_activities.filter(status__in=[ActivityStatus.SUBMITTED, ActivityStatus.UNDER_REVIEW]).count()
            stats['draft_count'] = user_activities.filter(status=ActivityStatus.DRAFT).count()
            stats['rejected_count'] = user_activities.filter(status=ActivityStatus.REJECTED).count()

            # Breakdown by category
            stats['journals_count'] = user_activities.filter(activity_type=ActivityType.JOURNAL_PUBLICATION).count()
            stats['conferences_count'] = user_activities.filter(activity_type=ActivityType.CONFERENCE_PUBLICATION).count()
            stats['patents_count'] = user_activities.filter(activity_type=ActivityType.PATENT).count()
            stats['fdps_count'] = user_activities.filter(activity_type=ActivityType.FACULTY_PARTICIPATION).count()

            recent_activities = user_activities.select_related('academic_session').order_by('-created_at')[:5]

            # If user has tenant and administrative privileges, also compute tenant-level stats
            if user.tenant and (user.is_staff or user.is_superuser or user.is_department_head or user.is_coordinator):
                tenant_acts = Activity.objects.filter(tenant=user.tenant)
                stats['tenant_total_activities'] = tenant_acts.count()
                stats['tenant_approved'] = tenant_acts.filter(status=ActivityStatus.APPROVED).count()
                stats['tenant_pending'] = tenant_acts.filter(status__in=[ActivityStatus.SUBMITTED, ActivityStatus.UNDER_REVIEW]).count()
                stats['tenant_faculty_count'] = User.objects.filter(tenant=user.tenant).count()

        permissions_list = []
        if user.role:
            permissions_list = user.role.permissions.select_related('module').all()

        return {
            'user': user,
            'stats': stats,
            'recent_activities': recent_activities,
            'permissions_list': permissions_list,
            'is_super': is_super,
            'is_supreme': is_super,
        }


