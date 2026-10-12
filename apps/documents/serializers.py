import os
from rest_framework import serializers
from apps.core.mixins import FieldMixin
from .models import ActivityDocument
from apps.activities.models import ActivityStatus

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}
BLOCKED_EXTENSIONS = {
    '.html', '.htm', '.svg', '.js', '.exe', '.sh', '.php', '.bat',
    '.py', '.pl', '.jsp', '.asp', '.vbs', '.cgi', '.jar', '.cmd'
}
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB


class ActivityDocumentSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = ActivityDocument
        fields = '__all__'
        read_only_fields = [
            'id', 'file_name', 'mime_type', 'file_size',
            'is_verified', 'uploaded_at'
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['url'] = instance.direct_url
        data['is_pdf'] = instance.is_pdf
        data['is_image'] = instance.is_image
        data['formatted_size'] = instance.formatted_size
        return data

    def validate_file(self, value):
        if not value:
            return value

        # 1. Extension Whitelist & Blacklist Enforcement
        fname = getattr(value, 'name', '')
        ext = os.path.splitext(fname)[1].lower()
        if ext in BLOCKED_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(
                f"File type '{ext}' is prohibited. Only certified documents and images "
                f"(.pdf, .png, .jpg, .jpeg, .webp) are permitted as proof attachments."
            )

        # 2. File Size Limit (15MB)
        if hasattr(value, 'size') and value.size > MAX_FILE_SIZE:
            raise serializers.ValidationError("File size exceeds the 15MB limit.")

        # 3. Header & Magic Bytes Inspection (Anti-XSS / Anti-Scripting)
        initial_bytes = value.read(64)
        value.seek(0)
        lower_bytes = initial_bytes.lower()
        if any(marker in lower_bytes for marker in (b'<html', b'<svg', b'<?xml', b'<script', b'<!doctype html')):
            raise serializers.ValidationError(
                "Malicious or executable content detected in file header. Upload rejected."
            )

        return value

    def validate(self, attrs):
        request = self.context.get('request')
        activity = attrs.get('activity')

        if not activity and self.instance:
            activity = self.instance.activity

        if request and request.user and not request.user.is_superuser:
            if activity:
                # 1. Ownership & Coordinator Authorization (IDOR Prevention)
                is_owner = (activity.faculty_id == request.user.id)
                is_dept_coordinator = (
                    request.user.department_id is not None
                    and activity.faculty.department_id == request.user.department_id
                    and request.user.has_module_perm('documents', 'approve')
                )
                if not is_owner and not is_dept_coordinator:
                    raise serializers.ValidationError({
                        "activity": "You do not have permission to attach proof documents to another faculty member's activity."
                    })

                # 2. Immutability Guard: Cannot attach documents to approved records
                if activity.status == ActivityStatus.APPROVED:
                    raise serializers.ValidationError({
                        "activity": "Cannot attach documents: This achievement has already been verified and locked for accreditation."
                    })

        return attrs
