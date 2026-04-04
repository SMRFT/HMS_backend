from rest_framework import serializers
from djongo.models.fields import ObjectIdField
from .models import StoresAssetsManagement ,StoresAssetsMaintainance ,recycle_asset

class StoresAssetsManagementSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = StoresAssetsManagement
        fields = '__all__'

class StoresAssetsMaintainanceSerializer(serializers.ModelSerializer):
    maintainance_details = serializers.ListField(
        child=serializers.DictField(),
        required=False
    )

    class Meta:
        model = StoresAssetsMaintainance
        fields = '__all__'

    def validate_maintainance_details(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("maintainance_details must be array of objects")

        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Each item must be object")

        return value

    def to_representation(self, instance):
        if isinstance(getattr(instance, 'maintainance_details', None), str):
            import json
            try:
                instance.maintainance_details = json.loads(instance.maintainance_details)
            except Exception:
                instance.maintainance_details = []

        representation = super().to_representation(instance)

        if not representation.get("maintainance_details"):
            representation["maintainance_details"] = []

        return representation

class recycle_assetSerializer(serializers.ModelSerializer):
    class Meta:
        model = recycle_asset
        fields = '__all__'

    def validate_items(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("items must be array of objects")

        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Each item must be object")

        return value

    def to_representation(self, instance):
        if isinstance(getattr(instance, 'items', None), str):
            import json
            try:
                instance.items = json.loads(instance.items)
            except Exception:
                instance.items = []

        representation = super().to_representation(instance)

        if not representation.get("items"):
            representation["items"] = []

        return representation
        