from rest_framework import serializers
from djongo.models.fields import ObjectIdField
from .models import StoresAssetsManagement ,StoresAssetsmaintenance ,recycle_asset, AssetMaintenanceRequest

class StoresAssetsManagementSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = StoresAssetsManagement
        fields = '__all__'

class StoresAssetsmaintenanceSerializer(serializers.ModelSerializer):
    maintenance_details = serializers.ListField(
        child=serializers.DictField(),
        required=False
    )

    class Meta:
        model = StoresAssetsmaintenance
        fields = '__all__'

    def validate_maintenance_details(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("maintenance_details must be array of objects")

        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Each item must be object")

        return value

    def to_representation(self, instance):
        if isinstance(getattr(instance, 'maintenance_details', None), str):
            import json
            try:
                instance.maintenance_details = json.loads(instance.maintenance_details)
            except Exception:
                instance.maintenance_details = []

        representation = super().to_representation(instance)

        if not representation.get("maintenance_details"):
            representation["maintenance_details"] = []

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

class AssetMaintenanceRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetMaintenanceRequest
        fields = '__all__'

    def to_representation(self, instance):
        if hasattr(instance, 'service_cost') and instance.service_cost is not None:
            try:
                instance.service_cost = float(str(instance.service_cost))
            except Exception:
                instance.service_cost = 0.0
        return super().to_representation(instance)

    def update(self, instance, validated_data):
        if hasattr(instance, 'service_cost') and instance.service_cost is not None:
            try:
                instance.service_cost = float(str(instance.service_cost))
            except Exception:
                instance.service_cost = 0.0
        return super().update(instance, validated_data)


        