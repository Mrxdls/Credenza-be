from rest_framework import permissions


def is_super_admin(request) -> bool:
    """
    Returns True strictly for Django Superusers (is_superuser=True).
    Platform governance & cross-tenant access is restricted to superusers via Django Admin.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser)


# Backwards compatibility alias
is_supreme_admin = is_super_admin


class IsSupremeAdmin(permissions.BasePermission):
    """DRF permission: allows access exclusively to Django Superusers."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsTenantActive(permissions.BasePermission):
    """
    Ensures that non-supreme-admin users belong to an active, enabled tenant and are approved.
    If the tenant was deactivated or user is pending approval, access is denied (HTTP 403).
    """
    message = "Your institutional account is inactive or suspended, or pending administrator approval."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return True
        if is_supreme_admin(request):
            return True
        if not getattr(user, 'is_approved', True):
            return False
        if user.tenant and not user.tenant.is_active:
            return False
        return True
