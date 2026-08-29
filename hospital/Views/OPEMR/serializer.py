from rest_framework import serializers
from .models import VitalEntry, DoctorConsultation


class VitalEntrySerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = VitalEntry
        fields = '__all__'


class DoctorConsultationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = DoctorConsultation
        fields = '__all__'
