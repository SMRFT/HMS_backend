from rest_framework import serializers
from djongo.models.fields import ObjectIdField
from .models import ItemMaster, Department, Group, Category, GroupType

class ItemMasterSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = ItemMaster
        fields = '__all__'

class DepartmentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Department
        fields = '__all__'

class GroupSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Group
        fields = '__all__'

class CategorySerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Category
        fields = '__all__'

class GroupTypeSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = GroupType
        fields = '__all__'
