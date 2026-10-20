from rest_framework import serializers
from .models import BreastCancerScreening, StudentSurveyorRegistration


class BreastCancerScreeningSerializer(serializers.ModelSerializer):
    _id = serializers.CharField(read_only=True)
    id = serializers.CharField(source='_id', read_only=True)
    bill_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = BreastCancerScreening
        fields = '__all__'


class StudentSurveyorRegistrationSerializer(serializers.ModelSerializer):
    _id = serializers.CharField(read_only=True)
    id = serializers.CharField(source='_id', read_only=True)

    class Meta:
        model = StudentSurveyorRegistration
        fields = '__all__'

