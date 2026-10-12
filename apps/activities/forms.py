"""
Dynamic Key-Value Form for Polymorphic Metadata & Custom Attributes.

Presents all metadata attributes as raw, editable Key-Value field pairs in the Django Admin.
First field represents the Key, second field represents the Value.
Users can edit any attribute, add new custom fields with 1 click, or load standard template fields.
Zero requirement to write raw JSON, completely UX-friendly and natively reliable.
"""
import json
from django import forms
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from .models import Activity


class KeyValueMetadataWidget(forms.Widget):
    """
    Renders all metadata as an interactive list of Key - Value input rows
    using standard Django widget templating.
    """
    template_name = "admin/activities/widgets/key_value_metadata.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except Exception:
                data = {}
        elif isinstance(value, dict):
            data = value
        else:
            data = {}

        context["widget"]["items"] = list(data.items())
        context["widget"]["num_items"] = len(data)
        return context

    def render(self, name, value, attrs=None, renderer=None):
        context = self.get_context(name, value, attrs)
        return mark_safe(render_to_string(self.template_name, context))


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


class ActivityAdminForm(forms.ModelForm):
    """
    ModelForm that presents polymorphic metadata and custom attributes as an editable
    Key-Value form. First field is Key, second field is Value.
    Saves cleanly and directly into Activity.metadata JSONField without user needing to format JSON.
    """
    metadata_kv_editor = forms.CharField(
        required=False,
        label="",
        widget=KeyValueMetadataWidget()
    )
    upload_multiple_proofs = MultipleFileField(
        required=False,
        label="Batch Upload Proof Documents",
        help_text="Select one or multiple proof files (PDF, PNG, JPG, WEBP) to attach simultaneously to this achievement."
    )

    class Meta:
        model = Activity
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Hide the raw JSON metadata field so users only interact with the Key-Value editor
        if 'metadata' in self.fields:
            self.fields['metadata'].widget = forms.HiddenInput()
            self.fields['metadata'].required = False

        instance = kwargs.get('instance')
        if instance and instance.metadata:
            self.initial['metadata_kv_editor'] = instance.metadata

    def clean(self):
        cleaned_data = super().clean()

        # Extract Key-Value pairs directly from standard HTTP POST parameters
        keys = self.data.getlist('meta_keys')
        values = self.data.getlist('meta_values')

        compiled_meta = {}
        for k, v in zip(keys, values):
            clean_k = str(k).strip()
            if clean_k:  # ignore empty keys
                compiled_meta[clean_k] = str(v).strip()

        # If form was submitted programmatically with dict in cleaned_data['metadata'] and no POST lists
        if not keys and not values and 'metadata' in cleaned_data and isinstance(cleaned_data['metadata'], dict) and cleaned_data['metadata']:
            compiled_meta = cleaned_data['metadata']

        cleaned_data['metadata'] = compiled_meta
        self.instance.metadata = compiled_meta
        return cleaned_data
