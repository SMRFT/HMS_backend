from rest_framework import serializers
from .models import BreastCancerScreening


class BreastCancerScreeningSerializer(serializers.ModelSerializer):
    _id = serializers.CharField(read_only=True)
    id = serializers.CharField(source='_id', read_only=True)
    bill_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = BreastCancerScreening
        fields = '__all__'
