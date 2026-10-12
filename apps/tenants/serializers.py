from rest_framework import serializers
from apps.core.mixins import FieldMixin
from .models import Tenant


class TenantSerializer(FieldMixin, serializers.ModelSerializer):
    users_count = serializers.IntegerField(read_only=True, required=False)
    activities_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Tenant
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.current_session:
            data['current_session_name'] = instance.current_session.name
        else:
            data['current_session_name'] = None
        return data
