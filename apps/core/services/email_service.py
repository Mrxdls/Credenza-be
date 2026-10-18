"""
Professional Email Dispatch Service for Credenza Platform.
Uses structured HTML & plain-text templates with standard Django EmailMultiAlternatives.
Sender and administrative alerts use official domain aliases:
- System Sender: no-reply@oryvo.co.in
- Platform Admin / Alerts: info@oryvo.co.in
"""

import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


class EmailService:
    """Centralized email notification dispatcher with responsive HTML template support."""

    DEFAULT_FROM = "no-reply@oryvo.co.in"
    DEFAULT_ADMIN_RECIPIENT = "info@oryvo.co.in"

    @classmethod
    def _get_from_email(cls) -> str:
        return getattr(settings, 'DEFAULT_FROM_EMAIL', cls.DEFAULT_FROM) or cls.DEFAULT_FROM

    @classmethod
    def _get_admin_email(cls) -> str:
        return getattr(settings, 'NOTIFY_ADMIN_EMAIL', cls.DEFAULT_ADMIN_RECIPIENT) or cls.DEFAULT_ADMIN_RECIPIENT

    @classmethod
    def _send_template_email(
        cls,
        subject: str,
        template_name: str,
        context: dict,
        to_email: str,
    ) -> bool:
        """
        Renders both HTML and plain-text templates and delivers via Django email backend.
        """
        try:
            from_email = cls._get_from_email()

            # Render HTML body
            html_template = f"emails/{template_name}.html"
            html_content = render_to_string(html_template, context)

            # Render plain text body or fallback to strip_tags
            txt_template = f"emails/{template_name}.txt"
            try:
                plain_content = render_to_string(txt_template, context)
            except Exception:
                plain_content = strip_tags(html_content)

            msg = EmailMultiAlternatives(
                subject=subject,
                body=plain_content,
                from_email=from_email,
                to=[to_email],
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            logger.info("Successfully dispatched email '%s' to %s", subject, to_email)
            return True

        except Exception as exc:
            logger.error("Failed to dispatch email '%s' to %s: %s", subject, to_email, exc, exc_info=True)
            return False

    @classmethod
    def send_registration_received_email(cls, tenant, user) -> bool:
        """
        Sends registration receipt confirmation to the applying institution administrator.
        """
        subject = f"Registration Received — {tenant.name} | Credenza Portal"
        context = {
            "tenant": tenant,
            "user": user,
        }
        return cls._send_template_email(
            subject=subject,
            template_name="registration_received",
            context=context,
            to_email=user.email,
        )

    @classmethod
    def send_admin_new_registration_alert(cls, tenant, user) -> bool:
        """
        Sends an alert email to the platform administrator (info@oryvo.co.in)
        notifying them of a new institution awaiting verification and approval.
        """
        admin_email = cls._get_admin_email()
        if not admin_email or admin_email == user.email:
            return False

        subject = f"Action Required: New Institution Registration — {tenant.name} ({tenant.code})"
        admin_url = f"https://credenza-be.vercel.app/admin/tenants/tenant/{tenant.id}/change/"
        context = {
            "tenant": tenant,
            "user": user,
            "admin_url": admin_url,
        }
        return cls._send_template_email(
            subject=subject,
            template_name="admin_registration_alert",
            context=context,
            to_email=admin_email,
        )

    @classmethod
    def send_tenant_activated_email(cls, tenant, user) -> bool:
        """
        Sends an activation confirmation email to the institution administrator
        when their tenant is approved by the platform superadmin.
        """
        subject = f"Institution Approved — {tenant.name} is Live! | Credenza"
        login_url = "https://credenza-be-rvs8.vercel.app/login"
        context = {
            "tenant": tenant,
            "user": user,
            "login_url": login_url,
        }
        return cls._send_template_email(
            subject=subject,
            template_name="tenant_activated",
            context=context,
            to_email=user.email,
        )

    @classmethod
    def send_user_invitation_email(cls, user, setup_url: str, tenant=None) -> bool:
        """
        Sends a one-time activation and password setup link to an onboarded faculty user.
        """
        tenant_name = tenant.name if tenant else "Credenza Portal"
        subject = f"Welcome to {tenant_name} — Set Your Password"
        context = {
            "user": user,
            "tenant": tenant,
            "setup_url": setup_url,
        }
        return cls._send_template_email(
            subject=subject,
            template_name="user_invitation",
            context=context,
            to_email=user.email,
        )
