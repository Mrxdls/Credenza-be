from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DepartmentViewSet,
    DesignationViewSet,
    ModuleViewSet,
    RoleViewSet,
    RolePermissionViewSet,
    UserViewSet,
    CurrentUserView,
    ChangePasswordView,
    SetupPasswordView,
    LoginAPIView,
    LogoutAPIView,
)

router = DefaultRouter()
router.register(r'departments', DepartmentViewSet, basename='department')
router.register(r'designations', DesignationViewSet, basename='designation')
router.register(r'modules', ModuleViewSet, basename='module')
router.register(r'roles', RoleViewSet, basename='role')
router.register(r'permissions', RolePermissionViewSet, basename='permission')
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('login/', LoginAPIView.as_view(), name='api-login'),
    path('logout/', LogoutAPIView.as_view(), name='api-logout'),
    path('me/', CurrentUserView.as_view(), name='current-user'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('setup-password/', SetupPasswordView.as_view(), name='setup-password'),
    path('', include(router.urls)),
]

