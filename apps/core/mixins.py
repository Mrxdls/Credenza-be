class FieldMixin(object):
    """
    Mixin for DRF ModelSerializer to dynamically include or exclude fields.
    Inspired by production DRF patterns (like vmco-backend):
      1. context={'fields': ['id', 'name', ...]}
      2. context={'exclude_fields': ['created_at', ...]}
      3. Query parameter: ?fields=id,name
    """
    def get_field_names(self, *args, **kwargs):
        field_names = self.context.get('fields', None)
        exclude_fields = self.context.get('exclude_fields', None)

        request = self.context.get('request', None)
        if request and hasattr(request, 'query_params') and not field_names:
            query_fields = request.query_params.get('fields', None)
            if query_fields:
                field_names = [f.strip() for f in query_fields.split(',') if f.strip()]

        if field_names:
            return field_names

        field_names = super(FieldMixin, self).get_field_names(*args, **kwargs)

        if exclude_fields:
            return [field for field in field_names if field not in exclude_fields]

        return field_names

