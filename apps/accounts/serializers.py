from rest_framework import serializers
from apps.core.mixins import FieldMixin
from .models import Department, Designation, User, Role, RolePermission, Module


class DepartmentSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = '__all__'


class DesignationSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Designation
        fields = '__all__'


class ModuleSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = '__all__'


class RolePermissionSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = RolePermission
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.module:
            data['module_name'] = instance.module.name
            data['module_code'] = instance.module.code
        return data


class RoleSerializer(FieldMixin, serializers.ModelSerializer):
    permissions = RolePermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = '__all__'


class UserMinimalSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ['password', 'user_permissions', 'groups', 'password_setup_token', 'password_setup_expires_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['display_name'] = instance.display_name
        if instance.department:
            data['department_name'] = instance.department.name
            data['department_code'] = instance.department.code
            data['department_details'] = {'id': str(instance.department.id), 'name': instance.department.name, 'code': instance.department.code}
        else:
            data['department_name'] = None
            data['department_code'] = None
            data['department_details'] = None

        if instance.designation:
            data['designation_name'] = instance.designation.name
            data['designation_details'] = {'id': str(instance.designation.id), 'name': instance.designation.name}
        else:
            data['designation_name'] = None
            data['designation_details'] = None

        if instance.role:
            data['role_name'] = instance.role.name
            data['role_code'] = instance.role.code
            data['role_details'] = {
                'id': str(instance.role.id),
                'name': instance.role.name,
                'code': instance.role.code,
                'scope': instance.role.scope,
                'rank': instance.role.rank,
            }
        else:
            data['role_name'] = None
            data['role_code'] = None
            data['role_details'] = None

        if instance.tenant:
            data['tenant_name'] = instance.tenant.name
            data['tenant_code'] = instance.tenant.code
        else:
            data['tenant_name'] = None
            data['tenant_code'] = None

        data['scope'] = instance.get_scope()
        data['rank'] = instance.get_rank()
        return data


class UserSerializer(FieldMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ['password', 'user_permissions', 'groups', 'password_setup_token', 'password_setup_expires_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['display_name'] = instance.display_name
        if instance.department:
            data['department_name'] = instance.department.name
            data['department_code'] = instance.department.code
            data['department_details'] = {'id': str(instance.department.id), 'name': instance.department.name, 'code': instance.department.code}
        else:
            data['department_name'] = None
            data['department_code'] = None
            data['department_details'] = None

        if instance.designation:
            data['designation_name'] = instance.designation.name
            data['designation_details'] = {'id': str(instance.designation.id), 'name': instance.designation.name}
        else:
            data['designation_name'] = None
            data['designation_details'] = None

        if instance.role:
            data['role_name'] = instance.role.name
            data['role_code'] = instance.role.code
            data['role_details'] = {
                'id': str(instance.role.id),
                'name': instance.role.name,
                'code': instance.role.code,
                'scope': instance.role.scope,
                'rank': instance.role.rank,
            }
        else:
            data['role_name'] = None
            data['role_code'] = None
            data['role_details'] = None

        if instance.tenant:
            data['tenant_name'] = instance.tenant.name
            data['tenant_code'] = instance.tenant.code
        else:
            data['tenant_name'] = None
            data['tenant_code'] = None

        data['scope'] = instance.get_scope()
        data['rank'] = instance.get_rank()
        return data
