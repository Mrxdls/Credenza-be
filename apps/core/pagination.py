"""
Global Cursor Pagination for High-Performance Deterministic API Streaming.
"""
from rest_framework.pagination import CursorPagination


class StandardCursorPagination(CursorPagination):
    """
    Standard cursor-based pagination for high performance and deterministic streaming.
    Eliminates offset-based query degradation on large datasets.
    """
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = ('-created_at', '-id')
    cursor_query_param = 'cursor'

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        model = getattr(queryset, 'model', None)
        if model:
            model_fields = {f.name for f in model._meta.get_fields()}
            valid_ordering = []
            for field in ordering:
                clean_name = field.lstrip('-+')
                if clean_name in model_fields or clean_name == 'pk':
                    valid_ordering.append(field)
            if valid_ordering:
                # Ensure unique tie-breaker
                if not any(f.lstrip('-+') in ('id', 'pk') for f in valid_ordering):
                    valid_ordering.append('id' if 'id' in model_fields else 'pk')
                return tuple(valid_ordering)
            else:
                # Fallback for reference tables without created_at
                if 'priority' in model_fields:
                    return ('-priority', 'id' if 'id' in model_fields else 'pk')
                elif 'name' in model_fields:
                    return ('name', 'id' if 'id' in model_fields else 'pk')
                return ('id' if 'id' in model_fields else 'pk',)
        return ordering
