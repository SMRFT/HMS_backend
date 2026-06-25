from rest_framework import serializers
from .models import Complaint

class ComplaintSerializer(serializers.ModelSerializer):
    issue_id = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Complaint
        fields = '__all__'

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        import json
        import ast
        from collections import OrderedDict

        for field in ['labels_tags', 'attachments']:
            val = getattr(instance, field, None)
            
            # If val is already a list, ensure its contents are clean dicts/values
            if isinstance(val, list):
                clean_list = []
                for item in val:
                    if isinstance(item, (dict, OrderedDict)):
                        clean_list.append(dict(item))
                    else:
                        clean_list.append(item)
                representation[field] = clean_list
            elif isinstance(val, str):
                try:
                    representation[field] = json.loads(val)
                except:
                    try:
                        representation[field] = ast.literal_eval(val)
                    except:
                        representation[field] = []
            elif val is None:
                representation[field] = []
            else:
                try:
                    representation[field] = list(val)
                except:
                    representation[field] = []
                    
        return representation

    def to_internal_value(self, data):
        import json
        internal_data = data.copy()

        for field in ['labels_tags', 'attachments']:
            if field in internal_data and isinstance(internal_data[field], str):
                try:
                    internal_data[field] = json.loads(internal_data[field])
                except json.JSONDecodeError:
                    pass

        return super().to_internal_value(internal_data)
