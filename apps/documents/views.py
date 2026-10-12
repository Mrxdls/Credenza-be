import os
import uuid
import logging
import mimetypes
from django.http import HttpResponse, HttpResponseRedirect

logger = logging.getLogger(__name__)
from rest_framework import viewsets, permissions, parsers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import ActivityDocument, DocumentType
from .serializers import ActivityDocumentSerializer, ALLOWED_EXTENSIONS, BLOCKED_EXTENSIONS, MAX_FILE_SIZE
from .r2 import (
    R2StorageService,
    get_r2_presigned_url,
    generate_r2_presigned_upload_url,
    is_r2_configured,
    is_r2_active,
    get_r2_config,
    get_r2_client,
)
from apps.accounts.permissions import HasModulePermission
from apps.tenants.permissions import IsTenantActive
from apps.activities.models import Activity, ActivityStatus


class ActivityDocumentViewSet(viewsets.ModelViewSet):
    """
    CRUD API for activity proof documents.
    Proofs are stored in their native formats (PDF, PNG, JPG) on Cloudflare R2 / local storage.
    Supports direct-to-R2 presigned PUT uploads and zero-egress presigned GET downloads.
    """
    queryset = ActivityDocument.objects.all().select_related('activity', 'activity__faculty')
    serializer_class = ActivityDocumentSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantActive, HasModulePermission]
    module_code = 'documents'
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]
    filterset_fields = ['activity', 'document_type', 'is_verified']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.is_superuser:
            return qs

        if getattr(user, 'tenant_id', None):
            qs = qs.filter(activity__tenant_id=user.tenant_id)

        can_approve = user.has_module_perm('documents', 'approve') or user.has_module_perm('activities', 'approve')
        if can_approve:
            if user.get_scope() == 'organization' or user.get_rank() >= 70 or not user.department_id:
                return qs
            return qs.filter(activity__faculty__department_id=user.department_id)

        from django.db.models import Q
        q_filter = Q(activity__faculty=user) | Q(activity__activity_authors__faculty=user)
        user_name = user.get_full_name().strip()
        if user_name and len(user_name) > 3:
            q_filter |= Q(activity__activity_authors__author_name__icontains=user_name)

        # Allow access to documents of approved activities in tenant
        q_filter |= Q(activity__status=ActivityStatus.APPROVED)

        return qs.filter(q_filter).distinct()

    def perform_destroy(self, instance):
        if instance.activity and instance.activity.status == ActivityStatus.APPROVED and not self.request.user.is_superuser:
            raise PermissionDenied("Cannot delete proof document from an approved achievement. It is locked for accreditation.")
        instance.delete()

    @action(detail=True, methods=['post'], url_path='verify')
    def verify_document(self, request, pk=None):
        """
        POST /api/documents/<id>/verify/
        Allows coordinators or administrators to verify an attached proof document.
        """
        doc = self.get_object()
        if not request.user.is_superuser and not request.user.has_module_perm('documents', 'approve'):
            return Response(
                {"error": "You do not have permission to verify documents."},
                status=status.HTTP_403_FORBIDDEN
            )
        doc.is_verified = True
        doc.verified_by = request.user
        doc.save(update_fields=['is_verified', 'verified_by'])
        serializer = self.get_serializer(doc)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='presigned-upload-url')
    def get_presigned_upload_url(self, request):
        """
        POST /api/documents/presigned-upload-url/
        Generates an authenticated S3/R2 presigned PUT URL allowing clients to upload
        large proof files directly into Cloudflare R2 without routing bytes through Django memory.
        """
        data = request.data
        activity_id = data.get('activity')
        file_name = data.get('file_name', '').strip()
        doc_type = data.get('document_type', DocumentType.PUBLISHED_PAPER)
        title = data.get('title', '').strip()
        file_size = data.get('file_size')
        mime_type = data.get('mime_type', '').strip()

        if not activity_id:
            return Response({"error": "Field 'activity' is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not file_name:
            return Response({"error": "Field 'file_name' is required."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Activity validation and ownership
        try:
            activity = Activity.objects.select_related('faculty').get(id=activity_id)
        except (Activity.DoesNotExist, ValueError):
            return Response({"error": "Specified activity does not exist."}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_superuser:
            is_owner = (activity.faculty_id == request.user.id)
            is_dept_coordinator = (
                request.user.department_id is not None
                and activity.faculty.department_id == request.user.department_id
                and request.user.has_module_perm('documents', 'approve')
            )
            if not is_owner and not is_dept_coordinator:
                return Response(
                    {"error": "You do not have permission to attach proof documents to this activity."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if activity.status == ActivityStatus.APPROVED:
                return Response(
                    {"error": "Cannot attach documents: This achievement has already been verified and locked for accreditation."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # 2. File extension and size validation
        ext = os.path.splitext(file_name)[1].lower()
        if ext in BLOCKED_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
            return Response(
                {"error": f"File type '{ext}' is prohibited. Only certified documents and images (.pdf, .png, .jpg, .jpeg, .webp) are permitted."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if file_size is not None:
            try:
                size_int = int(file_size)
                if size_int > MAX_FILE_SIZE:
                    return Response({"error": "File size exceeds the 15MB limit."}, status=status.HTTP_400_BAD_REQUEST)
                if size_int <= 0:
                    return Response({"error": "File size must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)
            except ValueError:
                return Response({"error": "Invalid file_size provided."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            size_int = 0

        resolved_mime = mime_type or mimetypes.guess_type(file_name)[0] or 'application/octet-stream'

        # 3. Create document record
        clean_name = os.path.basename(file_name)
        storage_key = f"proofs/{activity.id}/{uuid.uuid4().hex[:8]}_{clean_name}"

        doc = ActivityDocument.objects.create(
            activity=activity,
            document_type=doc_type,
            title=title or clean_name,
            file_name=clean_name,
            mime_type=resolved_mime,
            file_size=size_int,
            is_verified=False
        )
        doc.file.name = storage_key
        doc.save(update_fields=['file'])

        # 4. Generate Cloudflare R2 Presigned Upload URL
        if not is_r2_active():
            return Response(
                {"error": "Cloudflare R2 storage is not configured. Please check environment settings."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        try:
            upload_url = generate_r2_presigned_upload_url(
                storage_path=storage_key,
                content_type=resolved_mime,
                expiry=900
            )
        except Exception as e:
            return Response({"error": f"Failed to generate presigned upload URL: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "document_id": str(doc.id),
            "upload_url": upload_url,
            "storage_path": storage_key,
            "method": "PUT",
            "headers": {
                "Content-Type": resolved_mime
            },
            "expires_in": 900
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='confirm-upload')
    def confirm_upload(self, request, pk=None):
        """
        POST /api/documents/<id>/confirm-upload/
        Called by client after completing direct PUT upload to activate document.
        Verifies presence in Cloudflare R2 and updates ContentLength.
        """
        doc = self.get_object()

        if is_r2_active():
            try:
                head = R2StorageService.get_default().head_file(doc.file.name)
                actual_size = head.get('ContentLength')
                if actual_size:
                    doc.file_size = actual_size
                    doc.save(update_fields=['file_size'])
            except Exception as e:
                if not getattr(doc, 'file_size', 0):
                    return Response(
                        {"error": f"Unable to verify uploaded file in Cloudflare R2 storage: {str(e)}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

        serializer = self.get_serializer(doc)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['put'], url_path='upload-direct')
    def upload_direct(self, request, pk=None):
        """
        PUT /api/documents/<id>/upload-direct/
        Direct bytes upload endpoint storing directly into Cloudflare R2 bucket.
        """
        doc = self.get_object()
        raw_bytes = request.body
        if not raw_bytes:
            return Response({"error": "Empty upload payload"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            service = R2StorageService.get_default()
            service.upload_file(raw_bytes, doc.file.name, content_type=doc.mime_type)
            doc.file_size = len(raw_bytes)
            doc.save(update_fields=['file_size'])
            return Response({"status": "uploaded", "document_id": str(doc.id), "file_size": doc.file_size}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Failed to store file in Cloudflare R2: {str(e)}"}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['get'])
    def view_file(self, request, pk=None):
        """
        Serves original native document content (PDF/image) directly from Cloudflare R2.
        - Primary: 302 redirect directly to a time-limited signed Cloudflare R2 GET URL (zero-egress).
        - Direct streaming fallback: Reads bytes directly from Cloudflare R2 if requested or needed.
        Forces X-Content-Type-Options: nosniff and CSP headers.
        """
        doc = self.get_object()
        if not doc.file or not getattr(doc.file, 'name', None):
            return Response({"error": "No file attached to this document"}, status=status.HTTP_404_NOT_FOUND)

        is_download = request.query_params.get('download') == '1'
        want_stream = request.query_params.get('stream') == '1'
        filename = doc.file_name or os.path.basename(doc.file.name)

        # 1. Zero-egress Cloudflare R2 Presigned Redirect (default)
        if not want_stream and is_r2_active():
            try:
                presigned_url = get_r2_presigned_url(
                    storage_path=doc.file.name,
                    expiry=3600,
                    download=is_download,
                    original_filename=filename,
                )
                response = HttpResponseRedirect(presigned_url)
                response['X-Content-Type-Options'] = 'nosniff'
                response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
                return response
            except Exception as e:
                logger.warning(f"Presigned redirect generation failed for doc {doc.id}, falling back to R2 stream: {e}")

        # 2. Cloudflare R2 Direct Stream
        try:
            raw_bytes, clean_name, mime = R2StorageService.get_default().fetch_file(
                doc.file.name,
                original_filename=filename,
            )
            disposition = 'attachment' if is_download else 'inline'
            response = HttpResponse(raw_bytes, content_type=mime or doc.mime_type or 'application/octet-stream')
            response['Content-Disposition'] = f'{disposition}; filename="{clean_name}"'
            response['Content-Length'] = len(raw_bytes)
            response['X-Content-Type-Options'] = 'nosniff'
            response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            return response
        except Exception as e:
            # Fallback for unit tests where files are in test in-memory storage
            try:
                raw_bytes, clean_name, mime = doc.get_file_bytes()
                if raw_bytes:
                    disposition = 'attachment' if is_download else 'inline'
                    response = HttpResponse(raw_bytes, content_type=mime or doc.mime_type or 'application/octet-stream')
                    response['Content-Disposition'] = f'{disposition}; filename="{clean_name}"'
                    response['Content-Length'] = len(raw_bytes)
                    response['X-Content-Type-Options'] = 'nosniff'
                    response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
                    return response
            except Exception:
                pass

            return Response(
                {"error": f"Document file '{filename}' was not found in Cloudflare R2 storage: {str(e)}"},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Forces attachment download of document."""
        request.GET = request.GET.copy()
        request.GET['download'] = '1'
        return self.view_file(request, pk=pk)
