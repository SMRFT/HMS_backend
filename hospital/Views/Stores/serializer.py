from rest_framework import serializers
from djongo.models.fields import ObjectIdField
from .models import ItemMaster, Department, Group, Category, GroupType, storesGRN ,storesIntent 

class StoresGRNSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = storesGRN
        fields = '__all__'

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        import json
        import ast
        from collections import OrderedDict

        for field in ['items', 'payment_status']:
            val = getattr(instance, field, None)
            
            # If val is already a list, ensure its contents are simple dicts
            if isinstance(val, list):
                clean_list = []
                for item in val:
                    if isinstance(item, (dict, OrderedDict)):
                        clean_list.append(dict(item))
                    else:
                        clean_list.append(item)
                representation[field] = clean_list
            elif isinstance(val, str):
                try:
                    representation[field] = json.loads(val)
                except:
                    try:
                        representation[field] = ast.literal_eval(val)
                    except:
                        representation[field] = []
            elif val is None:
                representation[field] = []
            else:
                # Fallback for other types
                try:
                    representation[field] = list(val)
                except:
                    representation[field] = []
                    
        return representation

    def to_internal_value(self, data):
        import json
        internal_data = data.copy()

        # Check and parse items
        if 'items' in internal_data and isinstance(internal_data['items'], str):
            try:
                internal_data['items'] = json.loads(internal_data['items'])
            except json.JSONDecodeError:
                pass

        # Check and parse payment_status
        if 'payment_status' in internal_data and isinstance(internal_data['payment_status'], str):
            try:
                internal_data['payment_status'] = json.loads(internal_data['payment_status'])
            except json.JSONDecodeError:
                pass

        return super().to_internal_value(internal_data)

    def update(self, instance, validated_data):
        from bson.decimal128 import Decimal128
        from decimal import Decimal
        # Djongo bug: existing Decimal128 field values on the model instance 
        # fail validation when Django re-saves the instance on PATCH. 
        # We manually cast them to python Decimals to fix this.
        for field in instance._meta.fields:
            val = getattr(instance, field.attname, None)
            if isinstance(val, Decimal128):
                setattr(instance, field.attname, Decimal(str(val)))

        return super().update(instance, validated_data)

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

class StoresIntentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = storesIntent
        fields = '__all__'

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        import json
        import ast
        from collections import OrderedDict

        for field in ['items']:
            val = getattr(instance, field, None)
            
            # If val is already a list, ensure its contents are simple dicts
            if isinstance(val, list):
                clean_list = []
                for item in val:
                    if isinstance(item, (dict, OrderedDict)):
                        clean_list.append(dict(item))
                    else:
                        clean_list.append(item)
                representation[field] = clean_list
            elif isinstance(val, str):
                try:
                    representation[field] = json.loads(val)
                except:
                    try:
                        representation[field] = ast.literal_eval(val)
                    except:
                        representation[field] = []
            elif val is None:
                representation[field] = []
            else:
                # Fallback for other types
                try:
                    representation[field] = list(val)
                except:
                    representation[field] = []
                    
        return representation



from rest_framework import serializers
from .models import Stores_LabApprovedItem, Stores_LabUsedQtyDetail

class Stores_LabApprovedItemSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Stores_LabApprovedItem
        fields = '__all__'



class Stores_LabUsedQtyDetailSerializer(serializers.ModelSerializer):
    items = serializers.JSONField(required=False, default=list)

    class Meta:
        model = Stores_LabUsedQtyDetail
        fields = '__all__'

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        import json
        import ast
        from collections import OrderedDict

        val = getattr(instance, 'items', None)
        if val is None:
            val = representation.get('items')

        if isinstance(val, list):
            clean_list = []
            for item in val:
                if isinstance(item, (dict, OrderedDict)):
                    clean_list.append(dict(item))
                elif isinstance(item, str):
                    try:
                        clean_list.append(json.loads(item))
                    except Exception:
                        clean_list.append(item)
                else:
                    clean_list.append(item)
            representation['items'] = clean_list
        elif isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    representation['items'] = parsed
                else:
                    representation['items'] = [parsed]
            except Exception:
                try:
                    parsed = ast.literal_eval(val)
                    representation['items'] = parsed if isinstance(parsed, list) else []
                except Exception:
                    representation['items'] = []
        elif not representation.get('items'):
            representation['items'] = []

        return representation