from rest_framework import serializers
from .models import (
    ItemMaster, Department, Group, Category, GroupType, Rack, Shelf, storesGRN, storesIntent, 
    GeneralStoreVendor, VendingMachineSale, StoresPurchaseOrder, StoresPurchaseReturn, StoresIndentReturn,
    Stores_LabApprovedItem, Stores_LabUsedQtyDetail, ItemOpeningStockLog
)

_PROFILE_CACHE = {}
_PROFILE_CACHE_EXPIRY = 0

def get_employee_display_name(emp_id):
    """
    Resolves employee display name using created_by id matched into
    DB: Global, col: backend_diagnostics_profile (employeeId / userId / _id) -> employeeName
    """
    if not emp_id:
        return ""
    emp_str = str(emp_id).strip()
    if not emp_str:
        return ""

    import time
    global _PROFILE_CACHE, _PROFILE_CACHE_EXPIRY
    now = time.time()
    if now > _PROFILE_CACHE_EXPIRY:
        _PROFILE_CACHE.clear()
        _PROFILE_CACHE_EXPIRY = now + 300  # 5-minute cache

    if emp_str in _PROFILE_CACHE:
        return _PROFILE_CACHE[emp_str]

    try:
        from ..dbcollection import profile_collection
        from bson import ObjectId
        query = {"$or": [{"employeeId": emp_str}, {"userId": emp_str}]}
        if ObjectId.is_valid(emp_str):
            query["$or"].append({"_id": ObjectId(emp_str)})
        
        doc = profile_collection.find_one(
            query,
            {"employeeName": 1, "name": 1, "employeeId": 1, "_id": 0}
        )
        if doc:
            name = doc.get("employeeName") or doc.get("name") or emp_str
            _PROFILE_CACHE[emp_str] = name
            return name
    except Exception:
        pass

    _PROFILE_CACHE[emp_str] = emp_str
    return emp_str


def get_employee_map_for_grns(queryset):
    """
    Bulk pre-fetches display names for all distinct created_by IDs in queryset
    from Global.backend_diagnostics_profile.
    """
    employee_ids = set()
    for grn in queryset:
        cb = getattr(grn, 'created_by', None)
        if cb:
            employee_ids.add(str(cb).strip())

    employee_map = {}
    if not employee_ids:
        return employee_map

    # Check cache first
    missing_ids = set()
    for eid in employee_ids:
        if eid in _PROFILE_CACHE:
            employee_map[eid] = _PROFILE_CACHE[eid]
        else:
            missing_ids.add(eid)

    if missing_ids:
        try:
            from ..dbcollection import profile_collection
            from bson import ObjectId
            or_queries = [
                {"employeeId": {"$in": list(missing_ids)}},
                {"userId": {"$in": list(missing_ids)}}
            ]
            valid_object_ids = [ObjectId(eid) for eid in missing_ids if ObjectId.is_valid(eid)]
            if valid_object_ids:
                or_queries.append({"_id": {"$in": valid_object_ids}})

            profiles = list(profile_collection.find(
                {"$or": or_queries},
                {"employeeId": 1, "userId": 1, "employeeName": 1, "name": 1, "_id": 1}
            ))
            for p in profiles:
                emp_name = p.get("employeeName") or p.get("name") or ""
                if not emp_name:
                    continue
                if p.get("employeeId"):
                    k = str(p["employeeId"]).strip()
                    employee_map[k] = emp_name
                    _PROFILE_CACHE[k] = emp_name
                if p.get("userId"):
                    k = str(p["userId"]).strip()
                    employee_map[k] = emp_name
                    _PROFILE_CACHE[k] = emp_name
                if p.get("_id"):
                    k = str(p["_id"]).strip()
                    employee_map[k] = emp_name
                    _PROFILE_CACHE[k] = emp_name
        except Exception:
            pass

    # For any still missing, map to original ID
    for eid in missing_ids:
        if eid not in employee_map:
            employee_map[eid] = eid
            _PROFILE_CACHE[eid] = eid

    return employee_map


_DEPT_CACHE = {}
_DEPT_CACHE_EXPIRY = 0

def get_department_display_name(dept_code):
    """
    Resolves department code -> department name using:
    1. Global['backend_diagnostics_Departments'] (department_code / department_id / _id)
    2. Department model (hospital_department)
    """
    if not dept_code:
        return ""
    code_str = str(dept_code).strip()
    if not code_str:
        return ""

    import time
    global _DEPT_CACHE, _DEPT_CACHE_EXPIRY
    now = time.time()
    if now > _DEPT_CACHE_EXPIRY or not _DEPT_CACHE:
        try:
            from ..dbcollection import department_collection
            new_map = {}
            for doc in department_collection.find():
                if doc.get('is_active', True) is False:
                    continue
                c = doc.get('department_code') or doc.get('department_id') or str(doc.get('_id'))
                n = doc.get('department_name')
                if c and n:
                    c_clean = str(c).strip()
                    n_clean = str(n).strip()
                    new_map[c_clean] = n_clean
                    new_map[c_clean.lower()] = n_clean
                    new_map[n_clean] = n_clean
                    new_map[n_clean.lower()] = n_clean
            for d in Department.objects.filter(is_active__in=[True]):
                if d.department_id and d.department_name:
                    d_id = str(d.department_id).strip()
                    d_name = str(d.department_name).strip()
                    new_map[d_id] = d_name
                    new_map[d_id.lower()] = d_name
                    new_map[d_name] = d_name
                    new_map[d_name.lower()] = d_name
            _DEPT_CACHE = new_map
            _DEPT_CACHE_EXPIRY = now + 300  # 5-minute cache
        except Exception:
            pass

    resolved = _DEPT_CACHE.get(code_str) or _DEPT_CACHE.get(code_str.lower())
    return resolved or code_str


def get_department_map_for_grns(queryset=None):
    """
    Pre-populates and returns department code -> name mapping from Global.backend_diagnostics_Departments.
    """
    import time
    global _DEPT_CACHE, _DEPT_CACHE_EXPIRY
    now = time.time()
    if now > _DEPT_CACHE_EXPIRY or not _DEPT_CACHE:
        try:
            from ..dbcollection import department_collection
            new_map = {}
            for doc in department_collection.find():
                if doc.get('is_active', True) is False:
                    continue
                c = doc.get('department_code') or doc.get('department_id') or str(doc.get('_id'))
                n = doc.get('department_name')
                if c and n:
                    c_clean = str(c).strip()
                    n_clean = str(n).strip()
                    new_map[c_clean] = n_clean
                    new_map[c_clean.lower()] = n_clean
                    new_map[n_clean] = n_clean
                    new_map[n_clean.lower()] = n_clean
            for d in Department.objects.filter(is_active__in=[True]):
                if d.department_id and d.department_name:
                    d_id = str(d.department_id).strip()
                    d_name = str(d.department_name).strip()
                    new_map[d_id] = d_name
                    new_map[d_id.lower()] = d_name
                    new_map[d_name] = d_name
                    new_map[d_name.lower()] = d_name
            _DEPT_CACHE = new_map
            _DEPT_CACHE_EXPIRY = now + 300
        except Exception:
            pass

    return _DEPT_CACHE


def get_department_candidates(dept_val):
    """
    Returns all possible department code and name variations matching dept_val
    by comparing with backend_diagnostics_Departments and Department model.
    """
    if not dept_val:
        return set()
    dept_map = get_department_map_for_grns()
    v = str(dept_val).strip().lower()
    cands = {str(dept_val).strip()}
    for k, name in dept_map.items():
        if k.lower() == v or name.lower() == v:
            cands.add(k)
            cands.add(name)
    return cands


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

        # Resolve employee display name for created_by from Global.backend_diagnostics_profile
        created_by_id = representation.get('created_by') or getattr(instance, 'created_by', None)
        emp_name = None
        if created_by_id:
            emp_key = str(created_by_id).strip()
            context_map = self.context.get('employee_map') if isinstance(getattr(self, 'context', None), dict) else None
            if context_map and emp_key in context_map:
                emp_name = context_map[emp_key]
            else:
                emp_name = get_employee_display_name(emp_key)

        display_name = emp_name or (str(created_by_id).strip() if created_by_id else '')
        representation['entered_by'] = display_name
        representation['created_by_name'] = display_name

        # Resolve department name comparing department code with backend_diagnostics_Departments
        dept_val = representation.get('department') or getattr(instance, 'department', None)
        if not dept_val:
            # Fallback if GRN top-level department is blank, check items
            try:
                items_val = representation.get('items') or getattr(instance, 'items', None)
                if isinstance(items_val, list) and len(items_val) > 0 and isinstance(items_val[0], dict):
                    dept_val = items_val[0].get('department')
            except Exception:
                pass

        if dept_val:
            dept_key = str(dept_val).strip()
            context_map = self.context.get('department_map') if isinstance(getattr(self, 'context', None), dict) else None
            resolved_dept_name = None
            if context_map and dept_key in context_map:
                resolved_dept_name = context_map[dept_key]
            elif context_map and dept_key.lower() in context_map:
                resolved_dept_name = context_map[dept_key.lower()]
            else:
                resolved_dept_name = get_department_display_name(dept_key)

            representation['department_code'] = dept_key
            representation['department_name'] = resolved_dept_name or dept_key
        else:
            representation['department_code'] = ''
            representation['department_name'] = ''
                    
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
_GROUP_TYPE_MAP = {}
_VENDOR_MAP = {}

GROUP_CODE_TO_DEPT_CODE = {
    'GRP00028': 'DEPT036',  # STATIONERY -> General Store
    'GRP00029': 'DEPT036',  # GENERAL ITEMS -> General Store
    'GRP00030': 'DEPT036',  # PRINTING -> General Store
    'GRP00031': 'DEPT010',  # ELECTRICAL GOODS -> Electrician
    'GRP00032': 'DEPT013',  # HOUSE KEEPING -> House Keeping
    'GRP00037': 'DEPT048',  # MAMMOGRAPHY -> Radiology
    'GRP00049': 'DEPT053',  # PLUMING WORK -> Maintenance
    'GRP00052': 'DEPT036',  # TABL -> General Store
    'GRP00004': 'DPT00004',  # Vending Machine
    'GRP00001': 'DPT00001',
    'GRP00002': 'DPT00002',
    'GRP00003': 'DPT00002',
}

def get_lookup_maps():
    import time
    global _CACHE_EXPIRY, _CAT_MAP, _DEPT_MAP, _GROUP_MAP, _GROUP_TYPE_MAP, _VENDOR_MAP
    now_ts = time.time()
    if now_ts > _CACHE_EXPIRY:
        try:
            from ..dbcollection import hms_db
            _CAT_MAP = {}
            for doc in hms_db['hospital_category'].find({'is_active': True}):
                cid = doc.get('category_id')
                cname = doc.get('category_name') or doc.get('categoryName') or doc.get('name')
                if cid and cname:
                    _CAT_MAP[cid] = cname
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
                    _DEPT_MAP[str(name)] = name
            for d in Department.objects.filter(is_active__in=[True]):
                if d.department_id and d.department_name:
                    _DEPT_MAP[str(d.department_id)] = d.department_name
                    _DEPT_MAP[str(d.department_name)] = d.department_name
        except Exception:
            _DEPT_MAP = {}

        try:
            from ..dbcollection import hms_db
            _GROUP_MAP = {}
            for doc in hms_db['hospital_group'].find({'is_active': True}):
                gid = doc.get('group_id')
                gname = doc.get('group_name') or doc.get('groupName') or doc.get('name')
                if gid and gname:
                    _GROUP_MAP[gid] = gname
        except Exception:
            _GROUP_MAP = {}

        try:
            _GROUP_TYPE_MAP = {gt.group_type_id: gt.group_type_name for gt in GroupType.objects.filter(is_active__in=[True]) if gt.group_type_id and gt.group_type_name}
        except Exception:
            _GROUP_TYPE_MAP = {}

        try:
            _VENDOR_MAP = {str(v.vendor_id): v.name for v in GeneralStoreVendor.objects.filter(is_active__in=[True]) if v.vendor_id and v.name}
        except Exception:
            _VENDOR_MAP = {}

        _CACHE_EXPIRY = now_ts + 30

    return _CAT_MAP, _DEPT_MAP, _GROUP_MAP, _GROUP_TYPE_MAP, _VENDOR_MAP

class ItemMasterSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    unit_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, allow_null=True, default=0.00)
    ved_category = serializers.CharField(required=False, allow_null=True, default='D')
    abc_category = serializers.CharField(required=False, allow_null=True, default='C')
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
        if data.get('abc_category') is None or data.get('abc_category') == '':
            data['abc_category'] = 'C'
        if data.get('opening_stock') is None or data.get('opening_stock') == '':
            data['opening_stock'] = 0.00
        else:
            try:
                data['opening_stock'] = float(data.get('opening_stock', 0))
            except (ValueError, TypeError):
                data['opening_stock'] = 0.00
        if data.get('total_quantity') in (None, ''):
            data['total_quantity'] = 0
        if data.get('approved_quantity') in (None, ''):
            data['approved_quantity'] = 0

        cat_map, dept_map, group_map, _, _ = get_lookup_maps()
        rev_group_map = {v.lower().strip(): k for k, v in group_map.items() if v}
        rev_cat_map = {v.lower().strip(): k for k, v in cat_map.items() if v}

        # Resolve group to group_id code
        grp_code = data.get('group_code')
        if grp_code and grp_code in group_map:
            data['group'] = grp_code
        elif data.get('group'):
            g_val = str(data['group']).strip()
            if g_val in group_map:
                data['group'] = g_val
            elif g_val.lower() in rev_group_map:
                data['group'] = rev_group_map[g_val.lower()]

        # Resolve category to category_id code
        cat_code = data.get('category_code')
        if cat_code and cat_code in cat_map:
            data['category'] = cat_code
        elif data.get('category'):
            c_val = str(data['category']).strip()
            if c_val in cat_map:
                data['category'] = c_val
            elif c_val.lower() in rev_cat_map:
                data['category'] = rev_cat_map[c_val.lower()]

        # If category is provided but group is missing, auto-populate group from Category Master
        if data.get('category') and (not data.get('group') or str(data.get('group')).strip() in ('', '-', 'None', 'null')):
            from ..dbcollection import hms_db
            cat_doc = hms_db['hospital_category'].find_one({'category_id': data['category']})
            if cat_doc and cat_doc.get('group'):
                data['group'] = cat_doc['group']

        # Ensure department code mapping
        dept_val = data.get('department')
        if not dept_val or str(dept_val).strip() in ('', '-', 'None', 'null'):
            grp_val = data.get('group')
            if grp_val and grp_val in GROUP_CODE_TO_DEPT_CODE:
                data['department'] = GROUP_CODE_TO_DEPT_CODE[grp_val]
        return super().to_internal_value(data)

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        cat_map, dept_map, group_map, group_type_map, vendor_map = get_lookup_maps()
        
        # Category Code -> Name mapping
        cat_code = getattr(instance, 'category', None)
        if cat_code:
            cat_name = cat_map.get(cat_code) or cat_code
            rep['category_name'] = cat_name
            rep['category_code'] = cat_code
            rep['category'] = cat_name
        else:
            rep['category_name'] = '-'
            rep['category_code'] = ''

        # Department Code -> Name mapping
        dept_code = getattr(instance, 'department', None)
        if not dept_code or str(dept_code).strip() in ('', '-', 'None', 'null'):
            group_code = getattr(instance, 'group', None)
            dept_code = GROUP_CODE_TO_DEPT_CODE.get(group_code)

        if dept_code:
            dept_name = dept_map.get(str(dept_code)) or dept_code
            rep['department_name'] = dept_name
            rep['department_code'] = dept_code
            rep['department'] = dept_name
        else:
            rep['department_name'] = '-'
            rep['department_code'] = ''

        # Group Code -> Name mapping
        group_code = getattr(instance, 'group', None)
        if group_code:
            group_name = group_map.get(group_code) or group_code
            rep['group_name'] = group_name
            rep['group_code'] = group_code
            rep['group'] = group_name
        else:
            rep['group_name'] = '-'

        # Group Type Code -> Name mapping
        group_type_code = getattr(instance, 'group_type', None)
        if group_type_code:
            group_type_name = group_type_map.get(group_type_code) or group_type_code
            rep['group_type_name'] = group_type_name
            rep['group_type_code'] = group_type_code
            rep['group_type'] = group_type_name
        else:
            rep['group_type_name'] = '-'

        # Supplier Code -> Name mapping
        supp_code = getattr(instance, 'supplier', None)
        if supp_code:
            supp_name = vendor_map.get(str(supp_code)) or supp_code
            rep['supplier_name'] = supp_name
            rep['supplier_code'] = supp_code
            rep['supplier'] = supp_name
        else:
            rep['supplier_name'] = '-'

        # Manufacturer Code -> Name mapping
        manuf_code = getattr(instance, 'manufacturer', None)
        if manuf_code:
            manuf_name = vendor_map.get(str(manuf_code)) or manuf_code
            rep['manufacturer_name'] = manuf_name
            rep['manufacturer_code'] = manuf_code
            rep['manufacturer'] = manuf_name
        else:
            rep['manufacturer_name'] = '-'

        return rep


class DepartmentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Department
        fields = '__all__'

class GroupSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    group_name = serializers.CharField(required=False, allow_null=True)
    groupName = serializers.CharField(required=False, allow_null=True)
    class Meta:
        model = Group
        fields = '__all__'

    def to_internal_value(self, data):
        ret = super().to_internal_value(data)
        name = ret.get('group_name') or data.get('groupName') or data.get('group_name')
        if name:
            ret['group_name'] = name
        return ret

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        name = getattr(instance, 'group_name', None) or getattr(instance, 'groupName', None)
        if not rep.get('group_name') and name:
            rep['group_name'] = name
        rep['groupName'] = rep.get('group_name') or name
        return rep

    def create(self, validated_data):
        name = validated_data.get('group_name')
        instance = super().create(validated_data)
        if name:
            try:
                from ..dbcollection import hms_db
                hms_db['hospital_group'].update_one({'_id': instance.pk}, {'$set': {'groupName': name, 'group_name': name}})
            except Exception:
                pass
        return instance

    def update(self, instance, validated_data):
        name = validated_data.get('group_name') or instance.group_name
        instance = super().update(instance, validated_data)
        if name:
            try:
                from ..dbcollection import hms_db
                hms_db['hospital_group'].update_one({'_id': instance.pk}, {'$set': {'groupName': name, 'group_name': name}})
            except Exception:
                pass
        return instance

class CategorySerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    category_name = serializers.CharField(required=False, allow_null=True)
    categoryName = serializers.CharField(required=False, allow_null=True)
    group = serializers.CharField(required=False, allow_null=True)
    group_name = serializers.CharField(required=False, allow_null=True)
    group_type = serializers.CharField(required=False, allow_null=True)

    class Meta:
        model = Category
        fields = '__all__'

    def to_internal_value(self, data):
        ret = super().to_internal_value(data)
        name = ret.get('category_name') or data.get('categoryName') or data.get('category_name')
        if name:
            ret['category_name'] = name
        if data.get('group'):
            ret['group'] = data['group']
        if data.get('group_type'):
            ret['group_type'] = data['group_type']
        return ret

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        name = getattr(instance, 'category_name', None) or getattr(instance, 'categoryName', None)
        if not rep.get('category_name') and name:
            rep['category_name'] = name
        rep['categoryName'] = rep.get('category_name') or name
        grp = getattr(instance, 'group', None)
        if grp and not rep.get('group'):
            rep['group'] = grp
        if grp:
            _, _, group_map, _, _ = get_lookup_maps()
            rep['group_name'] = group_map.get(grp) or grp
        else:
            rep['group_name'] = '-'
        return rep

    def create(self, validated_data):
        name = validated_data.get('category_name')
        instance = super().create(validated_data)
        if name:
            try:
                from ..dbcollection import hms_db
                hms_db['hospital_category'].update_one({'_id': instance.pk}, {'$set': {'categoryName': name, 'category_name': name}})
            except Exception:
                pass
        return instance

    def update(self, instance, validated_data):
        name = validated_data.get('category_name') or instance.category_name
        instance = super().update(instance, validated_data)
        if name:
            try:
                from ..dbcollection import hms_db
                hms_db['hospital_category'].update_one({'_id': instance.pk}, {'$set': {'categoryName': name, 'category_name': name}})
            except Exception:
                pass
        return instance

class GroupTypeSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = GroupType
        fields = '__all__'

class RackSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Rack
        fields = '__all__'

class ShelfSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Shelf
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


class StoresPurchaseOrderSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = StoresPurchaseOrder
        fields = '__all__'

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        import json
        import ast
        from collections import OrderedDict

        val = getattr(instance, 'items', None)
        if isinstance(val, list):
            clean_list = []
            for item in val:
                if isinstance(item, (dict, OrderedDict)):
                    clean_list.append(dict(item))
                else:
                    clean_list.append(item)
            representation['items'] = clean_list
        elif isinstance(val, str):
            try:
                representation['items'] = json.loads(val)
            except Exception:
                try:
                    representation['items'] = ast.literal_eval(val)
                except Exception:
                    representation['items'] = []
        elif val is None:
            representation['items'] = []
        return representation


class StoresPurchaseReturnSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = StoresPurchaseReturn
        fields = '__all__'

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        import json
        import ast
        from collections import OrderedDict

        val = getattr(instance, 'items', None)
        if isinstance(val, list):
            clean_list = []
            for item in val:
                if isinstance(item, (dict, OrderedDict)):
                    clean_list.append(dict(item))
                else:
                    clean_list.append(item)
            representation['items'] = clean_list
        elif isinstance(val, str):
            try:
                representation['items'] = json.loads(val)
            except Exception:
                try:
                    representation['items'] = ast.literal_eval(val)
                except Exception:
                    representation['items'] = []
        elif val is None:
            representation['items'] = []
        return representation


class StoresIndentReturnSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = StoresIndentReturn
        fields = '__all__'

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        import json
        import ast
        from collections import OrderedDict

        val = getattr(instance, 'items', None)
        if isinstance(val, list):
            clean_list = []
            for item in val:
                if isinstance(item, (dict, OrderedDict)):
                    clean_list.append(dict(item))
                else:
                    clean_list.append(item)
            representation['items'] = clean_list
        elif isinstance(val, str):
            try:
                representation['items'] = json.loads(val)
            except Exception:
                try:
                    representation['items'] = ast.literal_eval(val)
                except Exception:
                    representation['items'] = []
        elif val is None:
            representation['items'] = []
        return representation


class ItemOpeningStockLogSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ItemOpeningStockLog
        fields = '__all__'

    def get_created_by_name(self, obj):
        return get_employee_display_name(getattr(obj, 'created_by', None))

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        cat_map, dept_map, group_map, _, _ = get_lookup_maps()
        
        dept_val = getattr(instance, 'department', None)
        if dept_val:
            rep['department_name'] = dept_map.get(str(dept_val), str(dept_val))
        
        grp_val = getattr(instance, 'group', None)
        if grp_val:
            rep['group_name'] = group_map.get(str(grp_val), str(grp_val))

        cat_val = getattr(instance, 'category', None)
        if cat_val:
            rep['category_name'] = cat_map.get(str(cat_val), str(cat_val))

        rep['created_by_name'] = self.get_created_by_name(instance)
        return rep




