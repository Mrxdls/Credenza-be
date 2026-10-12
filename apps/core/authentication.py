from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    SessionAuthentication subclass for decoupled Single Page Application (Next.js) frontends.
    Preserves full session cookie authentication while bypassing DRF's CSRF check on API endpoints.
    Cross-site protection is enforced by CORS_ALLOWED_ORIGINS and CORS_ALLOW_CREDENTIALS.
    """

    def enforce_csrf(self, request):
        return  # Bypasses CSRF validation on API endpoints governed by CORS
