import os
from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display, action
from simple_history.admin import SimpleHistoryAdmin

from .models import AcademicSession, Activity, ActivityAuthor, ActivityStatus, ActivityType
from .forms import ActivityAdminForm
from apps.documents.models import ActivityDocument, DocumentType


class ActivityAuthorInline(TabularInline):
    model = ActivityAuthor
    extra = 1
    fields = ('author_order', 'author_name', 'faculty', 'is_corresponding', 'affiliation')
    autocomplete_fields = ('faculty',)


class ActivityDocumentInline(TabularInline):
    model = ActivityDocument
    extra = 1
    fields = ('document_type', 'title', 'file', 'file_size_display', 'preview_document', 'is_verified')
    readonly_fields = ('file_size_display', 'preview_document')

    @display(description="Size")
    def file_size_display(self, obj):
        if not obj or not obj.file:
            return "—"
        return obj.formatted_size

    @display(description="Action")
    def preview_document(self, obj):
        if not obj or not obj.file:
            return "—"
        return format_html(
            '<a href="{}" target="_blank" class="text-primary-600 font-medium hover:underline text-xs">View Document ↗</a>',
            obj.direct_url
        )


@admin.register(AcademicSession)
class AcademicSessionAdmin(ModelAdmin):
    list_display = ('name', 'tenant', 'start_date', 'end_date', 'is_current_badge', 'activity_count')
    list_filter = ('tenant', 'is_current')
    search_fields = ('name', 'tenant__name', 'tenant__code')
    actions = ['mark_session_as_current']

    @display(
        description="Status",
        label={
            True: "success",
            False: "info",
        }
    )
    def is_current_badge(self, obj):
        return "Current Active" if obj.is_current else "Inactive"

    @display(description="Activities")
    def activity_count(self, obj):
        return obj.activities.count()

    @action(description="Mark selected session as Current (atomically deactivates others for tenant)")
    def mark_session_as_current(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Please select exactly one session to set as current.", level=messages.ERROR)
            return
        sess = queryset.first()
        sess.is_current = True
        sess.save()
        tenant_str = f" for '{sess.tenant.name}'" if sess.tenant else ""
        self.message_user(
            request,
            f"Academic Session '{sess.name}' is now the active current session{tenant_str}. Other sessions were deactivated.",
            level=messages.SUCCESS
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('tenant')
        if request.user.is_superuser:
            return qs
        if getattr(request.user, 'tenant_id', None):
            return qs.filter(tenant_id=request.user.tenant_id)
        return qs

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not obj.tenant and getattr(request.user, 'tenant_id', None):
            obj.tenant = request.user.tenant
        super().save_model(request, obj, form, change)


@admin.register(Activity)
class ActivityAdmin(ModelAdmin, SimpleHistoryAdmin):
    list_display = (
        'title_display',
        'faculty_info',
        'activity_type_badge',
        'status_badge',
        'proof_status_display',
        'academic_session',
        'created_at'
    )
    list_filter = (
        'tenant',
        'status',
        'activity_type',
        'academic_session',
        'faculty__department',
        'created_at',
    )
    search_fields = (
        'title',
        'faculty__first_name',
        'faculty__last_name',
        'faculty__employee_id',
        'faculty__email',
    )
    autocomplete_fields = ('faculty', 'academic_session')
    inlines = [ActivityAuthorInline, ActivityDocumentInline]
    actions = [
        'approve_selected_activities',
        'reject_selected_activities',
        'mark_under_review',
        'mark_draft',
        'export_selected_activities_action',
    ]
    actions_list = ['export_excel_action', 'bulk_import_action']

    form = ActivityAdminForm

    fieldsets = (
        ("Core Activity Information", {
            'fields': (
                'title',
                ('activity_type', 'academic_session'),
                ('faculty', 'status'),
                'rejection_reason',
                'metadata',
            )
        }),
        ("Polymorphic Metadata & Custom Attributes", {
            'description': "Each row represents an attribute (Key) and its data (Value). You can edit existing attributes, click '+ Load Template Keys' for recommended fields, or click '+ Add Field' to add any custom attribute on the fly.",
            'fields': ('metadata_kv_editor',),
        }),
        ("Proof Documents", {
            'description': "Batch upload proof files (PDF, PNG, JPG, WEBP) to attach directly to this achievement, or manage individual documents in the Proof Documents inline below.",
            'fields': ('upload_multiple_proofs',),
        }),
        ("Audit & Verification Metadata", {
            'fields': ('verified_by', 'verified_at'),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('verified_by', 'verified_at')

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj and obj.status == ActivityStatus.APPROVED and not request.user.is_superuser:
            core_fields = [f.name for f in self.model._meta.fields]
            return list(set(ro + core_fields + ['metadata_kv_editor', 'upload_multiple_proofs']))

        if not request.user.is_superuser:
            if not request.user.has_module_perm('activities', 'approve'):
                ro.extend(['faculty', 'verified_by', 'verified_at', 'rejection_reason'])
        return ro

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status == ActivityStatus.APPROVED and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj=obj)

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "status":
            if not request.user.is_superuser:
                if not request.user.has_module_perm('activities', 'approve'):
                    kwargs['choices'] = [
                        (ActivityStatus.DRAFT, 'Draft'),
                        (ActivityStatus.SUBMITTED, 'Submitted for Review'),
                    ]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not obj.tenant and getattr(request.user, 'tenant_id', None):
            obj.tenant = request.user.tenant
        elif not obj.tenant and obj.faculty and getattr(obj.faculty, 'tenant_id', None):
            obj.tenant = obj.faculty.tenant

        if not request.user.is_superuser:
            if not request.user.has_module_perm('activities', 'approve'):
                obj.faculty = request.user
                if not change and not obj.status:
                    obj.status = ActivityStatus.SUBMITTED
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        uploaded_files = request.FILES.getlist('upload_multiple_proofs')
        if uploaded_files:
            created_count = 0
            for f in uploaded_files:
                doc_type = DocumentType.PUBLISHED_PAPER
                lower = f.name.lower()
                if 'acceptance' in lower:
                    doc_type = DocumentType.ACCEPTANCE_LETTER
                elif 'index' in lower or 'scopus' in lower or 'wos' in lower:
                    doc_type = DocumentType.INDEXING_PROOF
                elif 'patent' in lower:
                    doc_type = DocumentType.PATENT_GRANT_CERTIFICATE
                elif 'certificate' in lower or 'fdp' in lower or 'workshop' in lower:
                    doc_type = DocumentType.FDP_ATTENDANCE_CERTIFICATE

                ActivityDocument.objects.create(
                    activity=form.instance,
                    file=f,
                    title=f.name,
                    document_type=doc_type,
                )
                created_count += 1

            if created_count > 0:
                self.message_user(
                    request,
                    f"Successfully uploaded and attached {created_count} proof document(s) directly to Cloudflare R2.",
                    level=messages.SUCCESS
                )

    def get_queryset(self, request):
        """Department and tenant scoping: users only see their tenant's activities."""
        qs = super().get_queryset(request).select_related('faculty', 'faculty__department', 'academic_session', 'tenant').prefetch_related('documents')
        if request.user.is_superuser:
            return qs

        if getattr(request.user, 'tenant_id', None):
            qs = qs.filter(tenant_id=request.user.tenant_id)

        if request.user.is_superuser:
            return qs

        if request.user.has_module_perm('activities', 'approve'):
            if not request.user.department_id:
                return qs
            return qs.filter(faculty__department=request.user.department)

        return qs.filter(faculty=request.user)

    @display(description="Title", header=True)
    def title_display(self, obj):
        return [
            obj.title[:90] + ("..." if len(obj.title) > 90 else ""),
            f"ID: {str(obj.id)[:8]}",
        ]

    @display(description="Faculty / Dept", header=True)
    def faculty_info(self, obj):
        dept_code = obj.faculty.department.code if obj.faculty.department else "N/A"
        emp_id = obj.faculty.employee_id or "—"
        initials = "".join([part[0] for part in obj.faculty.display_name.split()[:2]]).upper()
        return [
            obj.faculty.display_name,
            f"Emp: {emp_id} • Dept: {dept_code}",
            initials,
        ]

    @display(
        description="Type",
        label={
            ActivityType.JOURNAL_PUBLICATION: "info",
            ActivityType.CONFERENCE_PUBLICATION: "primary",
            ActivityType.PATENT: "warning",
            ActivityType.FACULTY_PARTICIPATION: "success",
        }
    )
    def activity_type_badge(self, obj):
        return obj.activity_type, obj.get_activity_type_display()

    @display(
        description="Status",
        label={
            ActivityStatus.DRAFT: "default",
            ActivityStatus.SUBMITTED: "warning",
            ActivityStatus.UNDER_REVIEW: "info",
            ActivityStatus.APPROVED: "success",
            ActivityStatus.REJECTED: "danger",
        }
    )
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @display(
        description="Proof Documents",
        label={
            True: "success",
            False: "danger",
        }
    )
    def proof_status_display(self, obj):
        count = obj.documents.count()
        if count > 0:
            return True, f"{count} Proof(s)"
        return False, "No Proof"

    @action(description="✓ Approve selected activities (Verifies proof documents)")
    def approve_selected_activities(self, request, queryset):
        """Batch approval action strictly enforcing dynamic module permissions, proof requirements, and self-approval block."""
        if not request.user.is_superuser and not request.user.has_module_perm('activities', 'approve'):
            self.message_user(request, "Permission Denied: You do not have permission to approve activities.", level=messages.ERROR)
            return

        approved_count = 0
        blocked_count = 0
        now = timezone.now()

        for activity in queryset:
            # Self-approval guard
            if activity.faculty_id == request.user.id and not request.user.is_superuser:
                blocked_count += 1
                self.message_user(
                    request,
                    f"BLOCKED: Self-approval is prohibited for '{activity.title[:45]}'.",
                    level=messages.ERROR
                )
                continue

            # Department jurisdiction
            if not request.user.is_superuser and request.user.department_id:
                if activity.faculty.department_id != request.user.department_id:
                    blocked_count += 1
                    self.message_user(
                        request,
                        f"BLOCKED: Activity '{activity.title[:45]}' belongs to a different department outside your jurisdiction.",
                        level=messages.ERROR
                    )
                    continue

            # Proof attachment requirement
            if not activity.documents.exists():
                blocked_count += 1
                self.message_user(
                    request,
                    f"BLOCKED: Activity '{activity.title[:45]}' has NO uploaded proof documents and cannot be approved.",
                    level=messages.ERROR
                )
                continue

            activity.status = ActivityStatus.APPROVED
            activity.verified_by = request.user
            activity.verified_at = now
            activity.rejection_reason = ""
            activity.save(update_fields=['status', 'verified_by', 'verified_at', 'rejection_reason', 'updated_at'])

            # Simultaneously verify all attached proof documents
            activity.documents.update(is_verified=True, verified_by=request.user)
            approved_count += 1

        if approved_count > 0:
            self.message_user(
                request,
                f"Successfully approved {approved_count} faculty activity(ies).",
                level=messages.SUCCESS
            )
        if blocked_count > 0:
            self.message_user(
                request,
                f"Warning: {blocked_count} activity(ies) were BLOCKED during batch approval.",
                level=messages.WARNING
            )

    @action(description="✗ Reject selected activities")
    def reject_selected_activities(self, request, queryset):
        """Batch rejection action with dynamic RBAC and department jurisdiction checks."""
        if not request.user.is_superuser and not request.user.has_module_perm('activities', 'approve'):
            self.message_user(request, "Permission Denied: You do not have permission to reject activities.", level=messages.ERROR)
            return

        rejected_count = 0
        blocked_count = 0
        now = timezone.now()

        for activity in queryset:
            if not request.user.is_superuser and request.user.department_id:
                if activity.faculty.department_id != request.user.department_id:
                    blocked_count += 1
                    self.message_user(
                        request,
                        f"BLOCKED: Activity '{activity.title[:45]}' is outside your department jurisdiction.",
                        level=messages.ERROR
                    )
                    continue

            activity.status = ActivityStatus.REJECTED
            activity.verified_by = request.user
            activity.verified_at = now
            activity.rejection_reason = "Rejected in administrative review."
            activity.save(update_fields=['status', 'verified_by', 'verified_at', 'rejection_reason', 'updated_at'])
            rejected_count += 1

        if rejected_count > 0:
            self.message_user(request, f"Successfully marked {rejected_count} activity(ies) as Rejected.", level=messages.SUCCESS)
        if blocked_count > 0:
            self.message_user(request, f"Warning: {blocked_count} activity(ies) were skipped due to jurisdiction limits.", level=messages.WARNING)

    @action(description="Move selected activities to 'Under Review'")
    def mark_under_review(self, request, queryset):
        if not request.user.is_superuser and not request.user.has_module_perm('activities', 'approve'):
            self.message_user(request, "Permission Denied: You do not have permission to update activity statuses.", level=messages.ERROR)
            return

        updated = 0
        for act in queryset:
            if not request.user.is_superuser and request.user.department_id:
                if act.faculty.department_id != request.user.department_id:
                    continue
            act.status = ActivityStatus.UNDER_REVIEW
            act.save(update_fields=['status', 'updated_at'])
            updated += 1

        self.message_user(request, f"Updated {updated} activity(ies) to Under Review.", level=messages.INFO)

    @action(description="Reset selected activities to 'Draft' (Send back to faculty)")
    def mark_draft(self, request, queryset):
        if not request.user.is_superuser and not request.user.has_module_perm('activities', 'approve'):
            self.message_user(request, "Permission Denied: You do not have permission to update activity statuses.", level=messages.ERROR)
            return

        updated = 0
        for act in queryset:
            if not request.user.is_superuser and request.user.department_id:
                if act.faculty.department_id != request.user.department_id:
                    continue
            act.status = ActivityStatus.DRAFT
            act.verified_by = None
            act.verified_at = None
            act.save(update_fields=['status', 'verified_by', 'verified_at', 'updated_at'])
            updated += 1

        self.message_user(request, f"Reset {updated} activity(ies) to Draft status.", level=messages.INFO)

    @action(description="Export NAAC Excel", url_path="export-excel-link")
    def export_excel_action(self, request):
        return redirect("admin:activities_activity_export")

    @action(description="📥 Export selected activities to Excel (NAAC Criteria 3)")
    def export_selected_activities_action(self, request, queryset):
        selected_ids = [str(x) for x in queryset.values_list('id', flat=True)]
        if not selected_ids:
            self.message_user(request, "No activities selected for export.", level=messages.WARNING)
            return

        from apps.core.services.export_service import AccreditationExportService
        tenant_id = request.user.tenant_id if not request.user.is_superuser and getattr(request.user, 'tenant_id', None) else None
        wb_buf = AccreditationExportService.generate_naac_criteria_3_workbook(
            activity_ids=selected_ids,
            statuses='all',
            tenant_id=tenant_id
        )
        date_str = timezone.now().strftime('%Y%m%d_%H%M')
        filename = f"NAAC_Criteria_3_Selected_{date_str}.xlsx"
        response = HttpResponse(
            wb_buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(description="Bulk Import (Excel / ZIP)", url_path="bulk-import-link")
    def bulk_import_action(self, request):
        return redirect("admin:activities_activity_bulk_import")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('export/', self.admin_site.admin_view(self.export_view), name='activities_activity_export'),
            path('bulk-import/', self.admin_site.admin_view(self.bulk_import_view), name='activities_activity_bulk_import'),
        ]
        return custom_urls + urls

    def export_view(self, request):
        from apps.core.services.export_service import AccreditationExportService
        from apps.accounts.models import Department

        user = request.user
        has_perm = (
            user.is_superuser
            or user.has_module_perm('activities', 'export')
            or user.has_module_perm('reports', 'export')
            or user.has_module_perm('activities', 'view')
            or user.has_module_perm('reports', 'view')
        )
        if not has_perm:
            messages.error(request, "Permission Denied: You do not have permission to view or export reports.")
            return redirect("admin:activities_activity_changelist")

        is_download = request.method == "POST" or request.GET.get("download") == "1"

        if is_download:
            params = request.POST if request.method == "POST" else request.GET
            session_id = params.get('academic_session')
            dept_id = params.get('department')
            status_list = params.getlist('status')
            verified = params.get('verified')
            has_proof = params.get('has_proof')
            activity_types = params.getlist('activity_type')
            date_from = params.get('date_from')
            date_to = params.get('date_to')
            search = params.get('search')

            # Scoping check for coordinators/HODs
            if not user.is_superuser:
                role_code = getattr(user.role, 'code', '').lower() if hasattr(user, 'role') and user.role else ''
                if role_code not in ('super_admin', 'dean') and user.department:
                    dept_id = str(user.department.id)

            # If 'all' in status_list or empty, export all statuses
            if not status_list or 'all' in status_list:
                statuses = 'all'
            else:
                statuses = status_list

            if not activity_types or 'all' in activity_types:
                types_filter = None
            else:
                types_filter = activity_types

            tenant_id = user.tenant_id if not user.is_superuser and getattr(user, 'tenant_id', None) else None
            wb_buf = AccreditationExportService.generate_naac_criteria_3_workbook(
                academic_session_id=session_id if session_id and session_id != 'all' else None,
                department_id=dept_id if dept_id and dept_id != 'all' else None,
                statuses=statuses,
                verified=verified if verified and verified != 'all' else None,
                has_proof=has_proof if has_proof and has_proof != 'all' else None,
                activity_types=types_filter,
                date_from=date_from or None,
                date_to=date_to or None,
                search=search or None,
                tenant_id=tenant_id,
            )

            date_str = timezone.now().strftime('%Y%m%d_%H%M')
            filename = f"NAAC_Criteria_3_Export_{date_str}.xlsx"
            response = HttpResponse(
                wb_buf.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        # GET request: render export console form
        sessions = AcademicSession.objects.all().order_by('-start_date')
        if not user.is_superuser and getattr(user, 'tenant_id', None):
            sessions = sessions.filter(tenant_id=user.tenant_id)
        is_dept_locked = False
        if not user.is_superuser:
            if user.has_module_perm('activities', 'approve'):
                if user.department:
                    departments = Department.objects.filter(id=user.department.id)
                    is_dept_locked = True
                else:
                    departments = Department.objects.all().order_by('name')
                    if getattr(user, 'tenant_id', None):
                        departments = departments.filter(tenant_id=user.tenant_id)
            else:
                departments = Department.objects.none()
        else:
            departments = Department.objects.all().order_by('name')

        context = {
            **self.admin_site.each_context(request),
            "title": "NAAC Criteria 3 Excel Export Console",
            "opts": self.model._meta,
            "sessions": sessions,
            "departments": departments,
            "user_dept": getattr(user, 'department', None),
            "is_dept_locked": is_dept_locked,
            "activity_types": ActivityType.choices,
            "status_choices": ActivityStatus.choices,
            "initial_status": request.GET.getlist('status') or ['approved'],
            "initial_session": request.GET.get('academic_session', 'all'),
            "initial_department": request.GET.get('department', 'all'),
            "initial_verified": request.GET.get('verified', 'all'),
            "initial_proof": request.GET.get('has_proof', 'all'),
        }
        return render(request, "admin/activities/export.html", context)

    def bulk_import_view(self, request):
        from apps.core.services.ingestion_service import BulkIngestionService
        if request.method == "POST":
            uploaded_file = request.FILES.get("import_file")
            if not uploaded_file:
                messages.error(request, "Please select an Excel (.xlsx) file or ZIP archive (.zip).")
            else:
                fname = uploaded_file.name.lower()
                if fname.endswith('.xlsx'):
                    res = BulkIngestionService.process_xlsx(uploaded_file, filename=uploaded_file.name)
                elif fname.endswith('.zip'):
                    res = BulkIngestionService.process_zip(uploaded_file)
                else:
                    messages.error(request, "Unsupported format. Please upload .xlsx or .zip.")
                    res = None

                if res:
                    if res.get("success"):
                        created = res.get("created") or res.get("activities_created", 0)
                        updated = res.get("updated", 0)
                        docs = res.get("documents_linked", 0)
                        messages.success(
                            request,
                            f"Bulk import succeeded! {created} activities created, {updated} updated, {docs} proof documents linked."
                        )
                        return redirect("admin:activities_activity_changelist")
                    else:
                        messages.error(request, f"Import failed: {res.get('error')}")

        context = {
            **self.admin_site.each_context(request),
            "title": "Bulk Ingest Faculty Achievements (Excel / ZIP)",
            "opts": self.model._meta,
        }
        return render(request, "admin/activities/bulk_import.html", context)
