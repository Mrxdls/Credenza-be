from typing import Optional
from rest_framework import permissions


class HasModulePermission(permissions.BasePermission):
    """
    Dynamic DRF Permission based on RolePermission records.
    
    Can be used as a view class attribute:
        permission_classes = [HasModulePermission]
        module_code = 'activities'
        
    Or instantiated with explicit module and action:
        permission_classes = [HasModulePermission.for_action('activities', 'approve')]
    """
    ACTION_MAP = {
        'GET': 'view',
        'POST': 'create',
        'PUT': 'edit',
        'PATCH': 'edit',
        'DELETE': 'delete',
    }

    def __init__(self, module_code: Optional[str] = None, required_action: Optional[str] = None):
        self.module_code = module_code
        self.required_action = required_action

    @classmethod
    def for_action(cls, module_code: str, action: str):
        """Factory creating a permission class bound to a specific module and action."""
        class BoundModulePermission(cls):
            def __init__(self):
                super().__init__(module_code=module_code, required_action=action)
        return BoundModulePermission

    def has_permission(self, request, view):
        # Allow preflight CORS OPTIONS requests
        if request.method == 'OPTIONS':
            return True

        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        if getattr(request.user, 'tenant_id', None) and request.user.tenant:
            if not request.user.tenant.is_active:
                self.message = "Your institutional tenant account is inactive or suspended. Please contact the platform administrator."
                return False

        module = self.module_code or getattr(view, 'module_code', None)
        if not module:
            # Fall back to matching view's basename or app_label
            module = getattr(view, 'basename', None) or view.__class__.__module__.split('.')[1]

        action = self.required_action
        if not action:
            view_action = getattr(view, 'action', None)
            if view_action in ('list', 'retrieve', 'view_file', 'download'):
                action = 'view'
            elif view_action in ('create', 'get_presigned_upload_url', 'confirm_upload'):
                action = 'create'
            elif view_action in ('update', 'partial_update'):
                action = 'edit'
            elif view_action in ('destroy',):
                action = 'delete'
            elif view_action in ('approve_activity', 'approve', 'batch_status_update', 'bulk_import', 'unlock_activity'):
                action = 'approve'
            elif view_action in ('export', 'naac_export'):
                action = 'view'  # Rule: who has permission to view can also export
            elif view_action in ('request_access',):
                action = 'view'
            else:
                action = self.ACTION_MAP.get(request.method, 'view')

        # Check explicit module permission
        if request.user.has_module_perm(module, action):
            return True

        # Allow faculty/authors to initiate delete/edit on activities & documents:
        # has_object_permission and perform_destroy strictly enforce ownership,
        # tenancy, and immutability of approved accreditation records.
        if module in ('activities', 'documents') and action in ('delete', 'edit', 'create'):
            if (request.user.has_module_perm(module, 'create') or 
                request.user.has_module_perm(module, 'edit') or 
                request.user.has_module_perm(module, 'view')):
                return True

        # Scoped read-only access for 'accounts' module:
        # Instead of 403 on listing or retrieving accounts (departments, designations, users),
        # allow authenticated tenant users to read their own scoped records.
        # get_queryset and has_object_permission enforce the exact scoping:
        # - DepartmentViewSet: returns user's own department
        # - UserViewSet: returns user's own profile (self) or department faculty (dept)
        # - DesignationViewSet: returns tenant designations
        if module == 'accounts' and action == 'view':
            return True

        return False

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        from apps.accounts.models import User, Department
        if isinstance(obj, User):
            if request.method in permissions.SAFE_METHODS:
                if request.user.get_scope() == 'organization' or request.user.get_rank() >= 100 or request.user.has_module_perm('accounts', 'view'):
                    return obj.tenant_id == request.user.tenant_id
                if request.user.get_scope() == 'department':
                    return obj.tenant_id == request.user.tenant_id and obj.department_id == request.user.department_id
                return obj.id == request.user.id
            return request.user.can_manage_user(obj)

        if isinstance(obj, Department):
            if request.method in permissions.SAFE_METHODS:
                if request.user.get_scope() == 'organization' or request.user.get_rank() >= 70 or request.user.has_module_perm('accounts', 'view'):
                    return obj.tenant_id == request.user.tenant_id
                # Department or self scope: can only view their own assigned department
                return obj.tenant_id == request.user.tenant_id and obj.id == request.user.department_id
            return request.user.get_rank() >= 100 and obj.tenant_id == request.user.tenant_id

        # Extract faculty owner
        faculty = getattr(obj, 'faculty', None)
        if faculty is None and hasattr(obj, 'activity'):
            faculty = getattr(obj.activity, 'faculty', None)

        view_action = getattr(view, 'action', None)

        # Self-approval guard: a faculty member cannot approve their own activity
        if view_action in ('approve_activity', 'approve') and faculty == request.user:
            return False

        # Activity status resolution
        act_status = getattr(obj, 'status', None)
        if act_status is None and hasattr(obj, 'activity'):
            act_status = getattr(obj.activity, 'status', None)

        is_author = (faculty == request.user)
        if not is_author and hasattr(obj, 'activity_authors'):
            is_author = obj.activity_authors.filter(faculty=request.user).exists()
        elif not is_author and hasattr(obj, 'activity') and hasattr(obj.activity, 'activity_authors'):
            is_author = obj.activity.activity_authors.filter(faculty=request.user).exists()

        is_org_admin = (request.user.get_rank() >= 100 or (request.user.role and request.user.role.code in ('admin', 'super_admin')))

        # Mutation lock for approved records:
        # Neither authors nor department coordinators can modify or delete approved records.
        # Approved records are immutable for accreditation unless unlocked by a coordinator/admin.
        if act_status == 'approved' and not request.user.is_superuser:
            if view_action in ('destroy', 'update', 'partial_update') or request.method in ('DELETE', 'PUT', 'PATCH'):
                return False

        # Read-only actions (retrieve, view_file, download, SAFE_METHODS)
        if view_action in ('retrieve', 'view_file', 'download', 'request_access') or request.method in permissions.SAFE_METHODS:
            tenant_id = getattr(obj, 'tenant_id', None)
            if tenant_id is None and hasattr(obj, 'activity'):
                tenant_id = getattr(obj.activity, 'tenant_id', None)
            if getattr(request.user, 'tenant_id', None) and tenant_id:
                if request.user.tenant_id != tenant_id:
                    return False

            # Authors and Organization Admins can always view
            if is_author or is_org_admin:
                return True

            # If activity is fully APPROVED, it is part of the institution's verified repository
            if act_status == 'approved':
                return True

            # DRAFTS can strictly ONLY be viewed by the author/co-authors
            if act_status == 'draft':
                return False

            # For submitted / under_review / rejected: only authorized reviewers can view
            module = self.module_code or getattr(view, 'module_code', 'activities')
            if request.user.has_module_perm(module, 'approve'):
                scope = request.user.get_scope()
                if scope == 'organization' or request.user.get_rank() >= 70 or not request.user.department_id:
                    return True
                if scope == 'department' and request.user.department_id and faculty:
                    return faculty.department_id == request.user.department_id

            return False

        if faculty is not None:
            module = self.module_code or getattr(view, 'module_code', 'activities')
            if request.user.has_module_perm(module, 'approve'):
                scope = request.user.get_scope()
                if scope == 'organization' or request.user.get_rank() >= 70:
                    return True
                if scope == 'department' and request.user.department_id:
                    return faculty.department_id == request.user.department_id
                return True

            # Standard faculty can only delete if primary faculty owner, and only modify/submit if author/co-author
            if view_action == 'destroy' or request.method == 'DELETE':
                return faculty == request.user

            return is_author

        return True
