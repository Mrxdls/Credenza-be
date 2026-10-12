from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import display
from simple_history.admin import SimpleHistoryAdmin

from .models import ActivityDocument


@admin.register(ActivityDocument)
class ActivityDocumentAdmin(ModelAdmin, SimpleHistoryAdmin):
    list_display = ('title_or_name', 'document_type', 'activity_header', 'file_size_display', 'is_verified', 'preview_action', 'uploaded_at')
    list_filter = ('document_type', 'is_verified', 'uploaded_at')
    search_fields = ('file_name', 'title', 'activity__title', 'activity__faculty__first_name', 'activity__faculty__last_name')
    readonly_fields = ('file_size', 'uploaded_at')

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('activity', 'activity__faculty', 'activity__faculty__department')
        if request.user.is_superuser:
            return qs

        if request.user.has_module_perm('documents', 'approve'):
            if not request.user.department_id:
                return qs
            return qs.filter(activity__faculty__department=request.user.department)

        return qs.filter(activity__faculty=request.user)

    @display(description="File / Document")
    def title_or_name(self, obj):
        return obj.title or obj.file_name or str(obj.id)

    @display(description="Associated Activity", header=True)
    def activity_header(self, obj):
        return [
            obj.activity.title[:60],
            obj.activity.faculty.display_name,
        ]

    @display(description="File Size")
    def file_size_display(self, obj):
        return obj.formatted_size

    @display(description="Action")
    def preview_action(self, obj):
        if not obj.file:
            return "—"
        return format_html(
            '<a href="/api/documents/{}/view_file/" target="_blank" class="text-primary-600 font-medium hover:underline text-xs">View Document ↗</a>',
            obj.id
        )
