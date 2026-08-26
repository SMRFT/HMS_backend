from rest_framework import serializers
from .models import VitalEntry


class VitalEntrySerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = VitalEntry
        fields = '__all__'
