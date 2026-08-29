from rest_framework import serializers
from .models import ItemMaster, Department, Group, Category, GroupType, storesGRN, storesIntent, GeneralStoreVendor, VendingMachineSale

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

_CACHE_EXPIRY = 0
_CAT_MAP = {}
_DEPT_MAP = {}
_GROUP_MAP = {}

def get_lookup_maps():
    import time
    global _CACHE_EXPIRY, _CAT_MAP, _DEPT_MAP, _GROUP_MAP
    now_ts = time.time()
    if now_ts > _CACHE_EXPIRY:
        try:
            _CAT_MAP = {c.category_id: c.category_name for c in Category.objects.filter(is_active__in=[True]) if c.category_id and c.category_name}
        except Exception:
            _CAT_MAP = {}
            
        try:
            from ..dbcollection import department_collection
            _DEPT_MAP = {}
            for doc in department_collection.find({'is_active': True}):
                code = doc.get('department_code') or doc.get('department_id') or str(doc.get('_id'))
                name = doc.get('department_name')
                if code and name:
                    _DEPT_MAP[str(code)] = name
            for d in Department.objects.filter(is_active__in=[True]):
                if d.department_id and d.department_name and str(d.department_id) not in _DEPT_MAP:
                    _DEPT_MAP[str(d.department_id)] = d.department_name
        except Exception:
            _DEPT_MAP = {}

        try:
            _GROUP_MAP = {g.group_id: g.group_name for g in Group.objects.filter(is_active__in=[True]) if g.group_id and g.group_name}
        except Exception:
            _GROUP_MAP = {}

        _CACHE_EXPIRY = now_ts + 30

    return _CAT_MAP, _DEPT_MAP, _GROUP_MAP

class ItemMasterSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    unit_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, allow_null=True, default=0.00)
    ved_category = serializers.CharField(required=False, allow_null=True, default='D')
    is_VM = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = ItemMaster
        fields = '__all__'

    def to_internal_value(self, data):
        data = data.copy()
        if data.get('unit_price') is None or data.get('unit_price') == '':
            data['unit_price'] = 0.00
        if data.get('ved_category') is None or data.get('ved_category') == '':
            data['ved_category'] = 'D'
        return super().to_internal_value(data)

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        cat_map, dept_map, group_map = get_lookup_maps()
        
        # Category Code -> Name mapping
        cat_code = getattr(instance, 'category', None)
        if cat_code:
            cat_name = cat_map.get(cat_code) or cat_code
            rep['category_name'] = cat_name
            rep['category_code'] = cat_code
            rep['category'] = cat_name
        else:
            rep['category_name'] = '-'

        # Department Code -> Name mapping
        dept_code = getattr(instance, 'department', None)
        if dept_code:
            dept_name = dept_map.get(dept_code) or dept_code
            rep['department_name'] = dept_name
            rep['department_code'] = dept_code
            rep['department'] = dept_name
        else:
            rep['department_name'] = '-'

        # Group Code -> Name mapping
        group_code = getattr(instance, 'group', None)
        if group_code:
            group_name = group_map.get(group_code) or group_code
            rep['group_name'] = group_name
            rep['group_code'] = group_code
            rep['group'] = group_name
        else:
            rep['group_name'] = '-'

        return rep


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
        return representation


class GeneralStoreVendorSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = GeneralStoreVendor
        fields = '__all__'

class VendingMachineSaleSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = VendingMachineSale
        fields = '__all__'
