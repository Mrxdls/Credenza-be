from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ActivityDocumentViewSet

router = DefaultRouter()
router.register(r'documents', ActivityDocumentViewSet, basename='document')

urlpatterns = [
    path('', include(router.urls)),
]
