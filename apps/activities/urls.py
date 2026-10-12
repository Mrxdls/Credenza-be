from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AcademicSessionViewSet,
    ActivityViewSet,
    DepartmentCountsView,
    UserAchievementSummaryView,
    DOIEnrichmentView,
    NAACExportView,
    BulkImportAPIView,
    ActivityMetadataView,
)

router = DefaultRouter()
router.register(r'sessions', AcademicSessionViewSet, basename='session')
router.register(r'activities', ActivityViewSet, basename='activity')

urlpatterns = [
    path('activities/metrics/department-counts/', DepartmentCountsView.as_view(), name='department-peer-counts'),
    path('activities/user-summary/', UserAchievementSummaryView.as_view(), name='activities-user-summary'),
    path('activities/metrics/user-summary/', UserAchievementSummaryView.as_view(), name='activities-user-summary-metrics'),
    path('activities/auto-enrich-doi/', DOIEnrichmentView.as_view(), name='auto-enrich-doi'),
    path('activities/export/', NAACExportView.as_view(), name='naac-criteria-export'),
    path('activities/bulk-import/', BulkImportAPIView.as_view(), name='activities-bulk-import-api'),
    path('activities/meta/', ActivityMetadataView.as_view(), name='activities-metadata'),
    path('', include(router.urls)),
]
