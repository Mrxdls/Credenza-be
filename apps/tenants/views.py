import logging
from django.shortcuts import render
from django.utils.text import slugify
from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User, Role
from .models import Tenant
from .serializers import TenantSerializer
from .permissions import IsSupremeAdmin

logger = logging.getLogger(__name__)


class TenantViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Multi-Tenant Provisioning & Management.
    Accessible strictly by Platform Supreme Admins.
    """
    queryset = Tenant.objects.all().order_by('name')
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated, IsSupremeAdmin]
    ordering = ('name', 'id')

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        tenant = self.get_object()
        tenant.is_active = True
        tenant.save(update_fields=['is_active', 'updated_at'])
        # Also approve and activate institutional staff administrators
        admin_users = list(User.objects.filter(tenant=tenant, is_staff=True))
        User.objects.filter(tenant=tenant, is_staff=True).update(is_approved=True, is_active=True)

        from django.core.mail import send_mail
        from django.conf import settings
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@oryvo.co.in')
        for admin_user in admin_users:
            try:
                send_mail(
                    subject=f"Institution Activated — {tenant.name} is now Live!",
                    message=(
                        f"Dear {admin_user.get_full_name() or admin_user.username},\n\n"
                        f"Great news! Your institution '{tenant.name}' has been verified and activated on Credenza.\n\n"
                        f"You can now log in to the portal with your credentials:\n"
                        f"https://credenza-be-rvs8.vercel.app/login\n\n"
                        f"Best regards,\n"
                        f"Credenza Support Team"
                    ),
                    from_email=from_email,
                    recipient_list=[admin_user.email],
                    fail_silently=True
                )
            except Exception as err:
                logger.warning(f"Failed to dispatch activation email to {admin_user.email}: {err}")

        return Response({"status": "active", "message": f"Tenant '{tenant.name}' has been activated and administrators approved."})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        tenant = self.get_object()
        tenant.is_active = False
        tenant.save(update_fields=['is_active', 'updated_at'])
        return Response({"status": "inactive", "message": f"Tenant '{tenant.name}' has been deactivated. Tenant users are now locked out."})


def send_registration_notifications(tenant, user):
    """
    Dispatches:
    1. Confirmation email to the registering administrator.
    2. Notification email to the platform superadmin.
    """
    from django.core.mail import send_mail
    from django.conf import settings

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@oryvo.co.in')
    notify_admin = getattr(settings, 'NOTIFY_ADMIN_EMAIL', 'mridul.s@oryvo.co.in')

    # 1. Confirmation email to registering institution applicant
    user_subject = f"Registration Received — {tenant.name} | Credenza Portal"
    user_message = (
        f"Dear {user.get_full_name() or user.username},\n\n"
        f"Thank you for registering {tenant.name} on the Credenza Institutional Achievements Portal.\n\n"
        f"Registration Summary:\n"
        f"  • Institution Name: {tenant.name}\n"
        f"  • Short Code: {tenant.code}\n"
        f"  • Administrator Email: {user.email}\n"
        f"  • Subscription Tier: {tenant.subscription_tier.title()}\n\n"
        f"Status: Under Review\n"
        f"Your organization account is currently pending verification and activation by the platform administrator. "
        f"You will receive an email confirmation as soon as your account is activated.\n\n"
        f"Best regards,\n"
        f"Credenza Support Team"
    )
    try:
        send_mail(user_subject, user_message, from_email, [user.email], fail_silently=False)
        logger.info(f"Dispatched registration confirmation to applicant {user.email}")
    except Exception as err:
        logger.error(f"Failed to dispatch applicant registration email to {user.email}: {err}")

    # 2. Alert email to platform administrator (mridul.s@oryvo.co.in)
    if notify_admin and notify_admin != user.email:
        admin_subject = f"New Institution Registration: {tenant.name} ({tenant.code})"
        admin_message = (
            f"Hello Administrator,\n\n"
            f"A new institution has registered on Credenza:\n\n"
            f"  • Institution: {tenant.name}\n"
            f"  • Short Code: {tenant.code}\n"
            f"  • Domain: {tenant.domain or 'None'}\n"
            f"  • Tier: {tenant.subscription_tier.title()}\n"
            f"  • Contact Person: {tenant.contact_name} ({user.email})\n"
            f"  • Phone: {tenant.contact_phone or 'N/A'}\n"
            f"  • Address: {tenant.address or 'N/A'}\n\n"
            f"To review and approve this institution, please log in to the admin console:\n"
            f"https://credenza-be.vercel.app/admin/tenants/tenant/{tenant.id}/change/\n\n"
            f"— Credenza Notification System"
        )
        try:
            send_mail(admin_subject, admin_message, from_email, [notify_admin], fail_silently=False)
            logger.info(f"Dispatched admin registration alert to {notify_admin}")
        except Exception as err:
            logger.error(f"Failed to dispatch admin registration notification to {notify_admin}: {err}")


class OrganizationRegistrationView(APIView):
    """
    Public registration portal and endpoint for new institutions/organizations.
    Creates an inactive organization and unapproved admin account pending Supreme Admin review.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return render(request, 'tenants/register_organization.html', {
            'success': False,
            'form_data': {},
            'error_message': None,
        })

    def post(self, request):
        is_json = request.content_type == 'application/json' or 'application/json' in request.META.get('HTTP_ACCEPT', '')
        data = request.data if hasattr(request, 'data') and request.data else request.POST

        name = str(data.get('name') or '').strip()
        code = str(data.get('code') or '').strip().upper()
        domain = str(data.get('domain') or '').strip().lower() or None
        subscription_tier = str(data.get('subscription_tier') or 'trial').strip().lower()
        address = str(data.get('address') or '').strip()

        admin_first_name = str(data.get('admin_first_name') or '').strip()
        admin_last_name = str(data.get('admin_last_name') or '').strip()
        admin_email = str(data.get('admin_email') or '').strip().lower()
        admin_phone = str(data.get('admin_phone') or '').strip()
        admin_password = str(data.get('admin_password') or '')
        confirm_password = str(data.get('confirm_password') or '')

        errors = []
        if not name:
            errors.append("Institution Name is required.")
        if not code:
            errors.append("Institution Short Code is required.")
        if not admin_email or '@' not in admin_email:
            errors.append("A valid administrative email address is required.")
        if not admin_password:
            errors.append("Admin password is required.")
        elif len(admin_password) < 8:
            errors.append("Admin password must be at least 8 characters long.")
        if confirm_password and admin_password != confirm_password:
            errors.append("Passwords do not match.")

        if Tenant.objects.filter(Q(code__iexact=code) | Q(name__iexact=name)).exists():
            errors.append(f"An institution with name '{name}' or code '{code}' already exists.")

        if domain and Tenant.objects.filter(domain__iexact=domain).exists():
            errors.append(f"Domain '{domain}' is already registered to another institution.")

        if User.objects.filter(email__iexact=admin_email).exists():
            errors.append(f"A user with email '{admin_email}' already exists.")

        if errors:
            err_msg = " ".join(errors)
            if is_json and not request.POST:
                return Response({"success": False, "error": err_msg, "details": errors}, status=status.HTTP_400_BAD_REQUEST)
            return render(request, 'tenants/register_organization.html', {
                'success': False,
                'form_data': data,
                'error_message': err_msg,
            })

        # Derived slugs and usernames
        slug_base = slugify(code).lower() or slugify(name).lower()[:50]
        slug = slug_base
        c = 1
        while Tenant.objects.filter(slug=slug).exists():
            slug = f"{slug_base}-{c}"
            c += 1

        username_base = admin_email.split('@')[0]
        username = username_base
        u_c = 1
        while User.objects.filter(username__iexact=username).exists():
            username = f"{username_base}{u_c}"
            u_c += 1

        try:
            with transaction.atomic():
                tenant = Tenant.objects.create(
                    name=name,
                    code=code,
                    slug=slug,
                    domain=domain,
                    subscription_tier=subscription_tier,
                    address=address,
                    contact_name=f"{admin_first_name} {admin_last_name}".strip(),
                    contact_email=admin_email,
                    contact_phone=admin_phone,
                    is_active=False,  # Inactive pending Supreme Admin approval
                )

                admin_role, _ = Role.objects.get_or_create(
                    tenant=tenant,
                    code='super_admin',
                    defaults={
                        'name': f"{tenant.code} Super Admin",
                        'description': f"Institutional Tenant Administrator for {tenant.name}"
                    }
                )

                user = User(
                    tenant=tenant,
                    email=admin_email,
                    username=username,
                    first_name=admin_first_name,
                    last_name=admin_last_name,
                    phone=admin_phone,
                    role=admin_role,
                    is_staff=True,
                    is_active=False,      # Inactive pending platform superuser approval
                    is_approved=False,    # Unapproved until platform superuser activates
                )
                user.set_password(admin_password)
                user.save()

            # Dispatch confirmation email to applicant and alert email to platform admin
            send_registration_notifications(tenant, user)

            if is_json and not request.POST:
                return Response({
                    "success": True,
                    "message": f"Institution '{tenant.name}' registered successfully. Awaiting platform administrator approval.",
                    "tenant": {
                        "id": str(tenant.id),
                        "name": tenant.name,
                        "code": tenant.code,
                        "is_active": tenant.is_active,
                    },
                    "admin": {
                        "id": str(user.id),
                        "email": user.email,
                        "username": user.username,
                        "is_approved": user.is_approved,
                    }
                }, status=status.HTTP_201_CREATED)

            return render(request, 'tenants/register_organization.html', {
                'success': True,
                'tenant_name': tenant.name,
                'tenant_code': tenant.code,
                'admin_email': user.email,
            })

        except Exception as e:
            logger.error(f"Error registering institution: {e}", exc_info=True)
            err_msg = f"An unexpected error occurred while processing registration: {str(e)}"
            if is_json and not request.POST:
                return Response({"success": False, "error": err_msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return render(request, 'tenants/register_organization.html', {
                'success': False,
                'form_data': data,
                'error_message': err_msg,
            })

