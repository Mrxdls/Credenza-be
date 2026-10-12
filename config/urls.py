"""
URL configuration for Poornima Faculty Achievements Portal.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

from apps.tenants.views import OrganizationRegistrationView
from apps.accounts.views import UserProfileView

urlpatterns = [
    # Root redirects directly to the interactive Unfold Admin
    path('', RedirectView.as_view(url='/admin/', permanent=False)),

    # Dedicated User Profile Pages
    path('profile/', UserProfileView.as_view(), name='user-profile'),
    path('accounts/profile/', UserProfileView.as_view(), name='accounts-profile'),

    # Public Organization / Institution Self-Registration
    path('register-organization/', OrganizationRegistrationView.as_view(), name='register-organization'),
    path('register/', OrganizationRegistrationView.as_view(), name='register-alias'),

    # Django Admin Portal (Full access for Super Admin & Tenant Staff)

    # Tenant Admin Portal (Institutional Admins & Staff)
    path('admin/', admin.site.urls),

    # REST Framework APIs
    path('api/accounts/', include('apps.accounts.urls')),
    path('api/', include('apps.activities.urls')),
    path('api/', include('apps.documents.urls')),
    path('api/', include('apps.tenants.urls')),
]

# Serve uploaded media files locally in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
