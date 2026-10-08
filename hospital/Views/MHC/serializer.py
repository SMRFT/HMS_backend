import re
from rest_framework import serializers
from .models import MasterHealthcheckup


class FlexibleIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if data in [None, '', 'null', 'None', 'undefined']:
            return None
        if isinstance(data, str):
            clean = data.strip()
            if not clean:
                return None
            digits = re.findall(r'\d+', clean)
            if digits:
                return int(digits[0])
            return None
        try:
            return int(float(data))
        except (ValueError, TypeError):
            return None


class MasterHealthcheckupSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True, required=False)
    age = FlexibleIntegerField(required=False, allow_null=True)

    class Meta:
        model = MasterHealthcheckup
        fields = '__all__'

