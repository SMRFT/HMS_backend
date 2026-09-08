import ast
import json
from collections import OrderedDict
from rest_framework import serializers
from .models import IPDoctorNotes, IPNursingNotes


def to_plain_json(val, default_type=dict):
    if val is None or val == "":
        return default_type()
    if isinstance(val, (dict, OrderedDict)):
        return {k: to_plain_json(v, dict) if isinstance(v, (dict, list, tuple, OrderedDict)) else v for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [to_plain_json(x, dict) if isinstance(x, (dict, list, tuple, OrderedDict)) else x for x in val]
    if isinstance(val, str):
        s = val.strip()
        # Handle OrderedDict and Python string repr
        if "OrderedDict" in s or (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
            try:
                evaluated = eval(s, {"OrderedDict": dict})
                return to_plain_json(evaluated, default_type)
            except Exception:
                pass
            try:
                parsed = json.loads(s)
                return to_plain_json(parsed, default_type)
            except Exception:
                pass
            try:
                parsed = ast.literal_eval(s)
                return to_plain_json(parsed, default_type)
            except Exception:
                pass
    return val


class IPDoctorNotesSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()

    class Meta:
        model = IPDoctorNotes
        fields = '__all__'

    def get_id(self, obj):
        val = getattr(obj, '_id', None) or getattr(obj, 'id', None)
        return str(val) if val is not None else ""

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Clean JSON dict fields
        json_dict_fields = ['allergies', 'past_history', 'social_history', 'menstrual_history',
                            'vaccination_history', 'obstetrics_history', 'investigations_done',
                            'physical_examination', 'provisional_diagnosis', 'plan_of_care']
        for f in json_dict_fields:
            if f in ret:
                ret[f] = to_plain_json(ret[f], dict)

        # Clean JSON list fields
        json_list_fields = ['chief_complaints', 'present_medications']
        for f in json_list_fields:
            if f in ret:
                ret[f] = to_plain_json(ret[f], list)
        return ret


class IPNursingNotesSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()

    class Meta:
        model = IPNursingNotes
        fields = '__all__'

    def get_id(self, obj):
        val = getattr(obj, '_id', None) or getattr(obj, 'id', None)
        return str(val) if val is not None else ""

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        json_fields = ['vitals', 'intake_output', 'nursing_assessment', 'nursing_interventions']
        for f in json_fields:
            if f in ret:
                ret[f] = to_plain_json(ret[f], dict)
        return ret
