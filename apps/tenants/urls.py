from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TenantViewSet, OrganizationRegistrationView

router = DefaultRouter()
router.register(r'tenants', TenantViewSet, basename='tenant')

urlpatterns = [
    path('tenants/register/', OrganizationRegistrationView.as_view(), name='tenant-register-api'),
    path('register/', OrganizationRegistrationView.as_view(), name='tenant-register-alias'),
    path('', include(router.urls)),
]

