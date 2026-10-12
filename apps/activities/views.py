from datetime import datetime
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Count, Q
from rest_framework import viewsets, generics, filters, status, permissions, parsers
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
import django_filters

from .models import AcademicSession, Activity, ActivityAuthor, ActivityStatus, ActivityType
from .serializers import (
    AcademicSessionSerializer,
    ActivitySerializer,
    ActivityAuthorSerializer,
    UserAchievementSummarySerializer,
)
from apps.accounts.models import User
from apps.accounts.permissions import HasModulePermission
from apps.tenants.permissions import IsTenantActive
from apps.core.services.crossref import CrossRefService
from apps.core.services.export_service import AccreditationExportService
from apps.core.services.ingestion_service import BulkIngestionService
from apps.documents.models import DocumentType


class AcademicSessionViewSet(viewsets.ModelViewSet):
    queryset = AcademicSession.objects.all()
    serializer_class = AcademicSessionSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive]
    ordering = ('-start_date', '-id')

    def get_queryset(self):
        user = self.request.user
        qs = AcademicSession.objects.all().select_related('tenant')
        if user.is_superuser:
            return qs
        if getattr(user, 'tenant_id', None):
            return qs.filter(tenant_id=user.tenant_id)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_superuser and 'tenant' in serializer.validated_data:
            serializer.save()
        elif getattr(user, 'tenant_id', None):
            serializer.save(tenant=user.tenant)
        else:
            serializer.save()


class ActivityFilter(django_filters.FilterSet):
    username = django_filters.CharFilter(field_name='faculty__username', lookup_expr='iexact')
    faculty__username = django_filters.CharFilter(field_name='faculty__username', lookup_expr='iexact')
    user = django_filters.CharFilter(field_name='faculty_id')
    user_id = django_filters.CharFilter(field_name='faculty_id')
    faculty = django_filters.CharFilter(field_name='faculty_id')
    department = django_filters.CharFilter(field_name='faculty__department_id')
    department_id = django_filters.CharFilter(field_name='faculty__department_id')
    faculty__department = django_filters.CharFilter(field_name='faculty__department_id')

    class Meta:
        model = Activity
        fields = [
            'status',
            'activity_type',
            'academic_session',
            'faculty',
            'faculty__department',
            'faculty__username',
            'username',
            'user',
            'user_id',
            'department',
            'department_id',
        ]


class ActivityViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Faculty Achievements with department scoping and status state machine.
    """
    serializer_class = ActivitySerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'activities'
    filterset_class = ActivityFilter
    search_fields = ['title', 'faculty__first_name', 'faculty__last_name', 'faculty__employee_id']
    ordering_fields = ['created_at', 'title', 'status']
    ordering = ('-created_at', '-id')

    def get_permissions(self):
        """
        Method-by-method conditional permission check at the view class level.
        """
        if self.action in ('approve_activity', 'reject_activity', 'batch_status_update', 'bulk_verify', 'bulk_import', 'unlock_activity'):
            return [permissions.IsAuthenticated(), IsTenantActive(), HasModulePermission.for_action('activities', 'approve')()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        qs = Activity.objects.all().select_related(
            'faculty', 'faculty__department', 'academic_session', 'tenant'
        ).prefetch_related('documents', 'activity_authors')

        # Tenant boundary isolation: Non-superusers are strictly scoped to their tenant.
        if not user.is_superuser and getattr(user, 'tenant_id', None):
            qs = qs.filter(Q(tenant_id=user.tenant_id) | Q(tenant__isnull=True))
        elif user.is_superuser:
            tenant_filter = self.request.query_params.get('tenant')
            if tenant_filter:
                qs = qs.filter(tenant_id=tenant_filter)

        # Single detail or lifecycle actions
        if getattr(self, 'action', None) in ('retrieve', 'request_access', 'unlock_activity'):
            return qs

        can_approve = user.has_module_perm('activities', 'approve')
        is_inst_admin = (user.get_rank() >= 70 or user.get_scope() == 'organization') or user.is_superuser
        can_view_all_faculty = can_approve and (user.get_scope() == 'organization' or is_inst_admin or user.department_id is None) or user.is_superuser

        # 1. Target user filtering by username (?username=... or ?faculty__username=...)
        target_username = (self.request.query_params.get('username') or self.request.query_params.get('faculty__username') or '').strip()
        if target_username:
            if user.is_superuser or user.username.lower() == target_username.lower() or can_view_all_faculty:
                return qs.filter(faculty__username__iexact=target_username)
            elif can_approve and user.department_id:
                return qs.filter(faculty__username__iexact=target_username, faculty__department_id=user.department_id)
            else:
                # User without permission cannot inspect other users' achievements
                return qs.none()

        # Target user filtering by user/faculty ID (?user=... or ?faculty=... or ?user_id=...)
        target_user_id = self.request.query_params.get('user') or self.request.query_params.get('faculty') or self.request.query_params.get('user_id')
        if target_user_id:
            if user.is_superuser or str(user.id) == str(target_user_id) or can_view_all_faculty:
                return qs.filter(faculty_id=target_user_id)
            elif can_approve and user.department_id:
                return qs.filter(faculty_id=target_user_id, faculty__department_id=user.department_id)
            else:
                return qs.none()

        # 2. Scope-based list filtering
        scope = self.request.query_params.get('scope')
        if scope == 'mine':
            return qs.filter(faculty=user)
        elif (scope == 'all' or self.request.query_params.get('all_faculty') == 'true'):
            if can_view_all_faculty:
                return qs
            if can_approve and user.department_id:
                return qs.filter(faculty__department_id=user.department_id)
            return qs.filter(faculty=user)

        # 3. Default list scoping
        if can_view_all_faculty:
            return qs
        if can_approve and user.department_id:
            return qs.filter(faculty__department_id=user.department_id)

        return qs.filter(faculty=user)


    def perform_create(self, serializer):
        # Default faculty to current user unless user is superuser or has user accounts admin privileges
        if not self.request.user.is_superuser and not self.request.user.has_module_perm('accounts', 'create'):
            serializer.save(faculty=self.request.user)
        else:
            serializer.save()

    def perform_update(self, serializer):
        instance = serializer.instance
        if instance.status == ActivityStatus.APPROVED and not self.request.user.is_superuser:
            raise PermissionDenied("Cannot modify an approved achievement. It is locked for accreditation.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.status == ActivityStatus.APPROVED and not self.request.user.is_superuser:
            raise PermissionDenied("Cannot delete an approved achievement. It is locked for accreditation.")
        instance.delete()

    @action(detail=True, methods=['post'], url_path='request-access')
    def request_access(self, request, pk=None):
        """
        Allows any faculty member or co-author to request editing privileges or submit revision notes.
        """
        activity = self.get_object()
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {"error": "Please provide a reason or note explaining why you need edit access."},
                status=status.HTTP_400_BAD_REQUEST
            )

        coord = None
        if activity.faculty.department:
            coord = User.objects.filter(
                department=activity.faculty.department,
                role__code='coordinator'
            ).first()

        return Response({
            "success": True,
            "message": f"Edit access request submitted for '{activity.title[:50]}'.",
            "faculty_name": activity.faculty.display_name,
            "faculty_email": activity.faculty.email,
            "coordinator_name": coord.display_name if coord else "Department Coordinator",
            "coordinator_email": coord.email if coord else None,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='unlock')
    def unlock_activity(self, request, pk=None):
        """
        Allows department coordinators and administrators to unlock an approved activity for revision.
        """
        activity = self.get_object()
        activity.status = ActivityStatus.SUBMITTED
        activity.save(update_fields=['status', 'updated_at'])
        return Response({"status": "submitted", "message": "Record unlocked for author revisions."})

    @action(detail=True, methods=['post'], url_path='submit')
    def submit_for_review(self, request, pk=None):
        """Transitions activity from draft to submitted."""
        activity = self.get_object()
        if activity.status != ActivityStatus.DRAFT:
            return Response(
                {"error": f"Only draft activities can be submitted. Current status is '{activity.status}'."},
                status=status.HTTP_400_BAD_REQUEST
            )
        activity.status = ActivityStatus.SUBMITTED
        activity.save()
        return Response({"status": "submitted", "message": "Activity submitted for departmental review."})

    @action(detail=True, methods=['post'], url_path='approve')
    def approve_activity(self, request, pk=None):
        """
        Approves an activity. Enforces self-approval block, department scope, and proof attachment requirement.
        """
        activity = self.get_object()

        # Strict Self-Approval Guard: A user cannot approve their own activity
        if activity.faculty_id == request.user.id and not request.user.is_superuser:
            return Response(
                {"error": "Self-approval is prohibited. Achievements must be approved by a department coordinator or head."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Department Scoping Check
        if not request.user.is_superuser and request.user.department_id:
            if activity.faculty.department_id != request.user.department_id:
                return Response(
                    {"error": "You can only approve achievements within your assigned department."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # Invariant check: proof document mandatory
        if not activity.documents.exists():
            return Response(
                {"error": "Cannot approve: Activity must have at least one verified proof attachment linked."},
                status=status.HTTP_400_BAD_REQUEST
            )

        activity.status = ActivityStatus.APPROVED
        activity.verified_by = request.user
        activity.verified_at = timezone.now()
        activity.rejection_reason = ""
        activity.save()

        return Response({"status": "approved", "message": "Activity approved and verified for accreditation."})

    @action(detail=True, methods=['post'], url_path='reject')
    def reject_activity(self, request, pk=None):
        """
        Rejects an activity with a mandatory reason.
        """
        activity = self.get_object()

        # Department Scoping Check
        if not request.user.is_superuser and request.user.department_id:
            if activity.faculty.department_id != request.user.department_id:
                return Response(
                    {"error": "You can only reject achievements within your assigned department."},
                    status=status.HTTP_403_FORBIDDEN
                )

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {"error": "A non-empty 'reason' is required when rejecting an activity."},
                status=status.HTTP_400_BAD_REQUEST
            )

        activity.status = ActivityStatus.REJECTED
        activity.rejection_reason = reason
        activity.verified_by = request.user
        activity.verified_at = timezone.now()
        activity.save()

        return Response({"status": "rejected", "message": "Activity marked as rejected with comments."})

    @action(detail=False, methods=['post'], url_path='batch-status-update')
    def batch_status_update(self, request):
        """
        POST /api/activities/batch-status-update/
        Atomically updates the status of multiple activities.
        Strictly enforces dynamic module permissions, department jurisdiction,
        self-approval block, and proof document requirements.
        """
        activity_ids = request.data.get('activity_ids', [])
        if not activity_ids or not isinstance(activity_ids, list):
            return Response(
                {"error": "Field 'activity_ids' must be a non-empty list of UUIDs."},
                status=status.HTTP_400_BAD_REQUEST
            )

        target_status = request.data.get('status')
        if not target_status or target_status not in ActivityStatus.values:
            return Response(
                {"error": f"Invalid status '{target_status}'. Must be one of: {list(ActivityStatus.values)}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        rejection_reason = request.data.get('rejection_reason', '').strip()
        if target_status == ActivityStatus.REJECTED and not rejection_reason:
            return Response(
                {"error": "A non-empty 'rejection_reason' is required when rejecting activities in batch."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Fetch target activities with strict tenant boundary
        act_qs = Activity.objects.filter(id__in=activity_ids)
        if not request.user.is_superuser and getattr(request.user, 'tenant_id', None):
            act_qs = act_qs.filter(tenant_id=request.user.tenant_id)

        activities = list(
            act_qs.select_related('faculty', 'faculty__department')
            .prefetch_related('documents')
        )

        found_ids = {str(a.id) for a in activities}
        missing_ids = [str(aid) for aid in activity_ids if str(aid) not in found_ids]
        if missing_ids:
            return Response(
                {"error": f"One or more activities could not be found or belong outside your institution: {missing_ids}"},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3. Item-by-item validation
        validation_errors = []
        for act in activities:
            # Department jurisdiction
            if not request.user.is_superuser and request.user.get_scope() == 'department':
                if not act.faculty or act.faculty.department_id != request.user.department_id:
                    validation_errors.append(
                        f"Activity '{act.title[:35]}': Faculty belongs to a different department outside your jurisdiction."
                    )

            # Self-approval guard
            if target_status == ActivityStatus.APPROVED and act.faculty_id == request.user.id and not request.user.is_superuser:
                validation_errors.append(
                    f"Activity '{act.title[:35]}': Self-approval is strictly prohibited."
                )

            # Proof attachment requirement
            if target_status == ActivityStatus.APPROVED and not act.documents.exists():
                validation_errors.append(
                    f"Activity '{act.title[:35]}': Missing mandatory proof document attachment."
                )

        if validation_errors:
            return Response(
                {
                    "error": "Batch status update failed validation. No records were modified.",
                    "details": validation_errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # 4. Atomic update
        now = timezone.now()
        updated_ids = []
        with transaction.atomic():
            for act in activities:
                act.status = target_status
                if target_status == ActivityStatus.APPROVED:
                    act.verified_by = request.user
                    act.verified_at = now
                    act.rejection_reason = ""
                    if request.data.get('verify_documents', True):
                        act.documents.update(is_verified=True, verified_by=request.user)
                elif target_status == ActivityStatus.REJECTED:
                    act.verified_by = request.user
                    act.verified_at = now
                    act.rejection_reason = rejection_reason
                elif target_status in (ActivityStatus.DRAFT, ActivityStatus.SUBMITTED, ActivityStatus.UNDER_REVIEW):
                    act.verified_by = None
                    act.verified_at = None
                    act.rejection_reason = ""
                # Use update_fields to bypass core field lock check during status transition
                act.save(update_fields=['status', 'verified_by', 'verified_at', 'rejection_reason', 'updated_at'])
                updated_ids.append(str(act.id))

        return Response(
            {
                "success": True,
                "updated_count": len(updated_ids),
                "status": target_status,
                "activity_ids": updated_ids,
                "message": f"Successfully updated {len(updated_ids)} activity(ies) to '{target_status}'."
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], url_path='bulk-verify')
    def bulk_verify(self, request):
        """
        POST /api/activities/bulk-verify/
        Mass verify achievements AND all attached proof documents simultaneously.
        """
        request.data['status'] = ActivityStatus.APPROVED
        if 'verify_documents' not in request.data:
            request.data['verify_documents'] = True
        return self.batch_status_update(request)

    @action(detail=False, methods=['post'], url_path='bulk-import', parser_classes=[parsers.MultiPartParser, parsers.FormParser])
    def bulk_import(self, request):
        """
        POST /api/activities/bulk-import/
        Allows coordinators, HODs, and administrators to upload an Excel (.xlsx) workbook or ZIP package.
        """
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({"error": "No file uploaded. Please provide a .xlsx or .zip file under the 'file' parameter."}, status=status.HTTP_400_BAD_REQUEST)

        fname = uploaded_file.name.lower()
        if fname.endswith('.xlsx'):
            result = BulkIngestionService.process_xlsx(uploaded_file, filename=uploaded_file.name)
        elif fname.endswith('.zip'):
            result = BulkIngestionService.process_zip(uploaded_file)
        else:
            return Response({"error": "Unsupported file format. Please upload a .xlsx workbook or a .zip archive."}, status=status.HTTP_400_BAD_REQUEST)

        if not result.get("success"):
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class DepartmentCountsView(APIView):
    """
    GET /api/activities/metrics/department-counts/
    Faculty peer benchmarking endpoint. Open to all authenticated faculty and staff.
    Returns aggregated counts per peer without leaking titles or proof URLs.
    Optimized to execute in a single SQL query using conditional aggregation (0 N+1 overhead).
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantActive]

    def get(self, request):
        user = request.user
        dept_id = request.query_params.get('department_id')
        session_id = request.query_params.get('academic_session_id')

        # Default to current user's department
        target_dept = dept_id or (user.department_id if user.department else None)

        faculty_qs = User.objects.filter(is_active=True)
        if not user.is_superuser and getattr(user, 'tenant_id', None):
            faculty_qs = faculty_qs.filter(tenant_id=user.tenant_id)
        if target_dept:
            faculty_qs = faculty_qs.filter(department_id=target_dept)

        # Build session filter for activities
        session_q = Q(activities__academic_session_id=session_id) if session_id else Q()

        faculty_qs = faculty_qs.select_related('department').annotate(
            journal_count=Count(
                'activities',
                filter=session_q & Q(activities__activity_type=ActivityType.JOURNAL_PUBLICATION),
                distinct=True
            ),
            conference_count=Count(
                'activities',
                filter=session_q & Q(activities__activity_type=ActivityType.CONFERENCE_PUBLICATION),
                distinct=True
            ),
            patent_count=Count(
                'activities',
                filter=session_q & Q(activities__activity_type=ActivityType.PATENT),
                distinct=True
            ),
            participation_count=Count(
                'activities',
                filter=session_q & Q(activities__activity_type=ActivityType.FACULTY_PARTICIPATION),
                distinct=True
            ),
            total_count=Count(
                'activities',
                filter=session_q & Q(activities__id__isnull=False),
                distinct=True
            )
        ).order_by('-total_count', 'first_name', 'last_name')

        results = [
            {
                "faculty_id": str(fac.id),
                "employee_id": fac.employee_id or "",
                "faculty_name": fac.display_name,
                "department_code": fac.department.code if fac.department else "",
                "department_name": fac.department.name if fac.department else "",
                "counts": {
                    "journal_publication": fac.journal_count,
                    "conference_publication": fac.conference_count,
                    "patent": fac.patent_count,
                    "faculty_participation": fac.participation_count,
                },
                "total_activities": fac.total_count,
            }
            for fac in faculty_qs
        ]

        return Response(results)



class DOIEnrichmentView(APIView):
    """
    POST /api/activities/auto-enrich-doi/
    On-demand asynchronous CrossRef lookup for DOI auto-fill.
    Payload: {"doi": "10.1109/..."}
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantActive]

    def post(self, request):
        raw_doi = request.data.get('doi', '').strip()
        if not raw_doi:
            return Response({"error": "DOI is required in request body."}, status=status.HTTP_400_BAD_REQUEST)

        result = CrossRefService.fetch_doi(raw_doi)
        if not result.get("success"):
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class NAACExportView(APIView):
    """
    GET /api/activities/export/
    1-Click NAAC AQAR Criteria 3 (3.4.3–3.4.6) multi-tab Excel export.
    Filters: ?academic_session_id=...&department_id=...
    Permission: Requires view permission on 'activities' or 'reports'.
    Scope:
      - Faculty: exports their own verified activities only.
      - Coordinator / HOD: exports their department's verified activities.
      - Dean / Superadmin: institution-wide export.
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'activities'

    def get(self, request):
        user = request.user
        session_id = request.query_params.get('academic_session_id') or request.query_params.get('session') or request.query_params.get('academic_session')
        dept_id = request.query_params.get('department_id') or request.query_params.get('department') or request.query_params.get('dept')
        status_param = request.query_params.get('status')
        verified_param = request.query_params.get('verified') or request.query_params.get('is_verified')
        has_proof_param = request.query_params.get('has_proof') or request.query_params.get('with_proof') or request.query_params.get('proof')
        type_param = request.query_params.get('activity_type') or request.query_params.get('type') or request.query_params.get('activity_types')
        date_from = request.query_params.get('date_from') or request.query_params.get('start_date')
        date_to = request.query_params.get('date_to') or request.query_params.get('end_date')
        search = request.query_params.get('search') or request.query_params.get('q')
        ids_param = request.query_params.get('ids') or request.query_params.get('activity_ids')
        faculty_id = request.query_params.get('faculty_id') or request.query_params.get('faculty')

        if not user.is_superuser:
            can_approve = user.has_module_perm('activities', 'approve')
            if can_approve and not user.department_id:
                pass  # Institution-wide export
            elif can_approve and user.department_id:
                dept_id = str(user.department_id)
            else:
                faculty_id = user.id
                dept_id = None

        statuses = None
        if status_param:
            if status_param.lower() in ('all', '*'):
                statuses = 'all'
            else:
                statuses = [s.strip().lower() for s in status_param.split(',') if s.strip()]

        tenant_id = None
        if not user.is_superuser and getattr(user, 'tenant_id', None):
            tenant_id = user.tenant_id

        workbook_buffer = AccreditationExportService.generate_naac_criteria_3_workbook(
            academic_session_id=session_id,
            department_id=dept_id,
            faculty_id=faculty_id,
            statuses=statuses,
            verified=verified_param,
            has_proof=has_proof_param,
            activity_types=type_param,
            date_from=date_from,
            date_to=date_to,
            search=search,
            activity_ids=ids_param,
            tenant_id=tenant_id,
        )

        date_str = datetime.now().strftime('%Y%m%d_%H%M')
        filename = f"NAAC_Criteria_3_Accreditation_Report_{date_str}.xlsx"

        response = HttpResponse(
            workbook_buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class BulkImportAPIView(APIView):
    """
    REST API endpoint for bulk ingesting faculty achievements via Excel (.xlsx) or ZIP archive.
    POST /api/activities/bulk-import/
    Multipart body: file=<xlsx or zip>
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'activities'
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        if not request.user.is_superuser and not request.user.has_module_perm('activities', 'approve'):
            raise PermissionDenied("You do not have permission to bulk-import activities.")

        upload_file = request.FILES.get('file') or request.FILES.get('import_file')
        if not upload_file:
            return Response(
                {"error": "Please provide an Excel (.xlsx) or ZIP archive (.zip) under key 'file'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        fname = upload_file.name.lower()
        if fname.endswith('.xlsx'):
            res = BulkIngestionService.process_xlsx(upload_file, filename=upload_file.name)
        elif fname.endswith('.zip'):
            res = BulkIngestionService.process_zip(upload_file)
        else:
            return Response(
                {"error": "Unsupported file format. Please upload a .xlsx Excel workbook or .zip archive."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if res.get('success'):
            return Response(res, status=status.HTTP_200_OK)
        else:
            return Response(res, status=status.HTTP_400_BAD_REQUEST)


class ActivityMetadataView(APIView):
    """
    Returns schema definitions, allowed choices, and recommended key-value templates
    for frontend dynamic forms and filtering.
    GET /api/activities/meta/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        data = {
            "activity_types": [
                {"code": code, "label": str(label)} for code, label in ActivityType.choices
            ],
            "activity_statuses": [
                {"code": code, "label": str(label)} for code, label in ActivityStatus.choices
            ],
            "document_types": [
                {"code": code, "label": str(label)} for code, label in DocumentType.choices
            ],
            "metadata_templates": {
                ActivityType.JOURNAL_PUBLICATION: [
                    {"key": "name_of_journal", "label": "Journal Name", "required": True},
                    {"key": "isbn_issn_(if_applicable)", "label": "ISSN / ISBN", "required": False},
                    {"key": "volume_no", "label": "Volume No", "required": False},
                    {"key": "issue_no", "label": "Issue No", "required": False},
                    {"key": "page_no", "label": "Page No", "required": False},
                    {"key": "doi", "label": "DOI / Paper URL", "required": False},
                    {"key": "indexing(if_any)_eg_scopus,_sci,_ugc_car", "label": "Indexing", "required": False},
                    {"key": "type_of_journal_(national_international)", "label": "Journal Type", "required": False},
                    {"key": "date_of_publication", "label": "Publication Date", "required": False},
                    {"key": "name_of_the_publisher", "label": "Publisher", "required": False},
                ],
                ActivityType.CONFERENCE_PUBLICATION: [
                    {"key": "conference_name", "label": "Conference Name", "required": True},
                    {"key": "types_of_conference_(national_conference", "label": "Conference Type", "required": False},
                    {"key": "organized_by", "label": "Organized By", "required": False},
                    {"key": "conference_location_(if_applicable)", "label": "Location", "required": False},
                    {"key": "date_of_conference", "label": "Conference Date", "required": False},
                    {"key": "isbn_issn_(if_applicable)", "label": "ISBN", "required": False},
                    {"key": "publication_through_conference_(yes_no)", "label": "Published in Proceedings?", "required": False},
                ],
                ActivityType.PATENT: [
                    {"key": "application_number", "label": "Patent / Application No", "required": True},
                    {"key": "patent_status", "label": "Status (Filed/Published/Granted)", "required": True},
                    {"key": "patent_office", "label": "Patent Office", "required": False},
                    {"key": "filing_date", "label": "Filing Date", "required": False},
                    {"key": "date_of_publication", "label": "Publication Date", "required": False},
                ],
                ActivityType.FACULTY_PARTICIPATION: [
                    {"key": "type_of_program_(fdp__workshop_conferenc", "label": "Program Type", "required": True},
                    {"key": "title_of_the_program", "label": "Program Title", "required": True},
                    {"key": "organized_by", "label": "Organized By", "required": False},
                    {"key": "sponsored_by", "label": "Sponsored By", "required": False},
                    {"key": "venue_of_the_program", "label": "Venue", "required": False},
                    {"key": "start_date", "label": "Start Date", "required": False},
                    {"key": "end_date", "label": "End Date", "required": False},
                    {"key": "duration_of_the_program", "label": "Duration", "required": False},
                    {"key": "select_semester(odd_even)", "label": "Semester (Odd/Even)", "required": False},
                ],
            }
        }
        return Response(data)


class UserAchievementSummaryView(generics.ListAPIView):
    """
    GET /api/activities/user-summary/
    Returns directory of users along with number of achievements uploaded by each.
    If the requesting user has permission to view a user's achievements,
    `can_view_details` is True (allowing click-through to GET /api/activities/?username=<username>).
    Otherwise, `can_view_details` is False, displaying only the aggregate numbers.
    """
    serializer_class = UserAchievementSummarySerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'activities'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'first_name', 'last_name', 'employee_id']
    ordering_fields = ['total_achievements', 'first_name', 'last_name']
    ordering = ('-total_achievements', 'first_name', 'last_name')
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        qs = User.objects.filter(is_active=True).select_related('department', 'designation', 'role')

        if not user.is_superuser and getattr(user, 'tenant_id', None):
            qs = qs.filter(tenant_id=user.tenant_id)

        dept_id = self.request.query_params.get('department_id') or self.request.query_params.get('department')
        if dept_id:
            qs = qs.filter(Q(department_id=dept_id) | Q(department__code__iexact=dept_id))

        return qs.annotate(
            total_achievements=Count('activities', distinct=True),
            approved_achievements=Count('activities', filter=Q(activities__status=ActivityStatus.APPROVED), distinct=True),
        )


