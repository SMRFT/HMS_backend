from rest_framework import serializers
from .models import InPatientFeedback, OutPatientFeedback

class InPatientFeedbackSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True, required=False)

    class Meta:
        model = InPatientFeedback
        fields = '__all__'


class OutPatientFeedbackSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True, required=False)

    class Meta:
        model = OutPatientFeedback
        fields = '__all__'

