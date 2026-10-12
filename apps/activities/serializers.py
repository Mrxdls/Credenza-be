from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from apps.core.mixins import FieldMixin
from .models import AcademicSession, Activity, ActivityAuthor, ActivityStatus, ActivityType
from apps.documents.serializers import ActivityDocumentSerializer


class AcademicSessionSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = AcademicSession
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.tenant:
            data['tenant_name'] = instance.tenant.name
            data['tenant_code'] = instance.tenant.code
        return data


class ActivityAuthorSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = ActivityAuthor
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.faculty:
            data['faculty_employee_id'] = instance.faculty.employee_id
            data['faculty_name'] = instance.faculty.display_name
        return data


class ActivitySerializer(FieldMixin, serializers.ModelSerializer):
    documents = ActivityDocumentSerializer(many=True, read_only=True)
    activity_authors = ActivityAuthorSerializer(many=True, read_only=True)

    class Meta:
        model = Activity
        fields = '__all__'
        read_only_fields = ['id', 'verified_by', 'verified_at', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)

        faculty = instance.faculty
        if faculty:
            data['faculty_name'] = faculty.display_name
            data['faculty_email'] = faculty.email
            data['faculty_employee_id'] = faculty.employee_id or ''
            data['faculty_designation'] = faculty.designation.name if faculty.designation else ''
            dept = faculty.department
            if dept:
                data['department_name'] = dept.name
                data['department_code'] = dept.code
                data['faculty_department_name'] = dept.name
            else:
                data['department_name'] = None
                data['department_code'] = None
                data['faculty_department_name'] = None

        session = instance.academic_session
        if session:
            data['session_name'] = session.name
            data['academic_session_name'] = session.name

        tenant = instance.tenant
        if tenant:
            data['tenant_name'] = tenant.name
            data['tenant_code'] = tenant.code

        verifier = instance.verified_by
        data['verified_by_name'] = verifier.display_name if verifier else ''

        if isinstance(instance.metadata, dict):
            data['description'] = instance.metadata.get('description', '')
        else:
            data['description'] = ''

        return data

    def validate(self, attrs):
        request = self.context.get('request')

        # 1. Enforce immutability on approved achievements for non-superusers
        if self.instance and self.instance.status == ActivityStatus.APPROVED:
            if request and not request.user.is_superuser:
                raise PermissionDenied(
                    "Cannot modify an approved achievement. It is locked for accreditation."
                )

        # 2. Prevent non-approvers from transitioning status directly to approved/under_review/rejected
        if self.instance and 'status' in attrs:
            new_status = attrs['status']
            if new_status != self.instance.status:
                if request and not request.user.is_superuser:
                    if new_status in (ActivityStatus.APPROVED, ActivityStatus.UNDER_REVIEW, ActivityStatus.REJECTED):
                        if not request.user.has_module_perm('activities', 'approve'):
                            raise serializers.ValidationError(
                                {"status": f"You do not have permission to transition status to '{new_status}'."}
                            )

        # Sync description into metadata if provided
        initial_description = self.initial_data.get('description')
        if initial_description is not None:
            if 'metadata' not in attrs:
                attrs['metadata'] = dict(self.instance.metadata) if self.instance and self.instance.metadata else {}
            attrs['metadata']['description'] = str(initial_description).strip()

        # Metadata validation based on activity_type
        activity_type = attrs.get('activity_type') or (self.instance.activity_type if self.instance else None)
        metadata = attrs.get('metadata', self.instance.metadata if self.instance else {})

        # If partial update without touching metadata or activity_type, and title/session already valid, skip deep metadata checks
        if self.partial and 'metadata' not in attrs and 'activity_type' not in attrs:
            return attrs

        title = attrs.get('title') or (self.instance.title if self.instance else '')

        if activity_type == ActivityType.JOURNAL_PUBLICATION:
            has_journal = (
                metadata.get('journal_name')
                or metadata.get('name_of_journal')
                or metadata.get('journal')
                or bool(title)
            )
            if not has_journal:
                raise serializers.ValidationError({"metadata": "Missing required journal name."})

        elif activity_type == ActivityType.CONFERENCE_PUBLICATION:
            has_conf = (
                metadata.get('conference_name')
                or metadata.get('name_of_conference')
                or metadata.get('conference')
                or bool(title)
            )
            if not has_conf:
                raise serializers.ValidationError({"metadata": "Missing required conference name."})

        elif activity_type == ActivityType.PATENT:
            has_patent = (
                metadata.get('patent_or_application_number')
                or metadata.get('application_number')
                or metadata.get('patent_number')
                or bool(title)
            )
            if not has_patent:
                raise serializers.ValidationError({"metadata": "Missing required patent / application number."})

        elif activity_type == ActivityType.FACULTY_PARTICIPATION:
            has_prog = (
                metadata.get('program_title')
                or metadata.get('title_of_the_program')
                or metadata.get('program_name')
                or bool(title)
            )
            if not has_prog:
                raise serializers.ValidationError({"metadata": "Missing required program title."})

        return attrs

    def update(self, instance, validated_data):
        request = self.context.get('request')
        if request and request.user.is_superuser:
            instance._skip_lock_check = True
        return super().update(instance, validated_data)


class DepartmentSummarySerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        from apps.accounts.models import Department
        model = Department
        fields = '__all__'


class UserAchievementSummarySerializer(FieldMixin, serializers.ModelSerializer):
    department = DepartmentSummarySerializer(read_only=True)

    class Meta:
        from apps.accounts.models import User
        model = User
        exclude = ['password', 'user_permissions', 'groups', 'password_setup_token', 'password_setup_expires_at']

    def to_representation(self, instance):
        can_view = self.get_can_view_details(instance)
        data = super().to_representation(instance)
        data['designation'] = instance.designation.name if instance.designation else ''
        data['role'] = instance.role.name if instance.role else 'Faculty'
        data['achievements_count'] = getattr(instance, 'total_achievements', 0)
        data['approved_count'] = getattr(instance, 'approved_achievements', 0)
        data['can_view_details'] = can_view

        if not can_view:
            # Strip private personal data when viewer lacks detail clearance
            safe_data = {
                'id': str(instance.id),
                'username': instance.username,
                'first_name': instance.first_name,
                'last_name': instance.last_name,
                'display_name': instance.display_name,
                'department': data.get('department'),
                'designation': data['designation'],
                'role': data['role'],
                'achievements_count': data['achievements_count'],
                'approved_count': data['approved_count'],
                'can_view_details': False,
            }
            return safe_data

        return data

    def get_can_view_details(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        user = request.user
        if user.is_superuser or str(obj.id) == str(user.id):
            return True
        scope = user.get_scope()
        can_approve = user.has_module_perm('activities', 'approve')
        if can_approve and (scope == 'organization' or user.get_rank() >= 70 or not user.department_id):
            return True
        if can_approve and user.department_id and getattr(obj, 'department_id', None) == user.department_id:
            return True
        return False
