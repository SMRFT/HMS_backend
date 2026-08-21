from rest_framework import serializers
from .models import MasterHealthcheckup


class MasterHealthcheckupSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True, required=False)

    class Meta:
        model = MasterHealthcheckup
        fields = '__all__'
