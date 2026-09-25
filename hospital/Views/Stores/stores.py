import json
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import (
    ItemMaster, Department, Group, Category, GroupType, Rack, Shelf, storesGRN, storesIntent, 
    Stores_LabApprovedItem, Stores_LabUsedQtyDetail, GeneralStoreVendor, VendingMachineSale,
    StoresPurchaseOrder, StoresPurchaseReturn, StoresIndentReturn
)
from .serializer import (
    ItemMasterSerializer, DepartmentSerializer, 
    GroupSerializer, CategorySerializer, GroupTypeSerializer, RackSerializer, ShelfSerializer,
    StoresGRNSerializer, StoresIntentSerializer,
    Stores_LabApprovedItemSerializer, Stores_LabUsedQtyDetailSerializer, GeneralStoreVendorSerializer,
    VendingMachineSaleSerializer, StoresPurchaseOrderSerializer, StoresPurchaseReturnSerializer,
    StoresIndentReturnSerializer
)
from django.shortcuts import get_object_or_404
from datetime import datetime, timedelta, date
from pyauth.auth import HasRoleAndDataPermission
from ..dbcollection import department_collection
from django.utils import timezone

def get_financial_year_string():
    now = datetime.now()
    if now.month <= 3:
        return f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"
    else:
        return f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"

def generate_custom_id(model_class, id_field_name, prefix, sequence_length):
    fy_str = get_financial_year_string()
    base_prefix = f"{prefix}{fy_str}"
    
    last_record = model_class.objects.filter(**{f"{id_field_name}__startswith": base_prefix}).order_by('-created_date').first()
    
    if last_record:
        last_id = getattr(last_record, id_field_name)
        try:
            last_sequence = int(last_id.replace(base_prefix, ''))
            new_sequence = last_sequence + 1
        except ValueError:
            new_sequence = 1
    else:
        new_sequence = 1
        
    return f"{base_prefix}{new_sequence:0{sequence_length}d}"

def generate_custom_id_without_fy(model_class, id_field_name, prefix, sequence_length):
    base_prefix = f"{prefix}"
    print("base_prefix", base_prefix)
    last_record = model_class.objects.filter(**{f"{id_field_name}__startswith": base_prefix}).order_by('-created_date').first()
    print("last_record", last_record)
    if last_record:
        last_id = getattr(last_record, id_field_name)
        try:
            last_sequence = int(last_id.replace(base_prefix, ''))
            print("last_sequence", last_sequence)
            new_sequence = last_sequence + 1
            print("new_sequence", new_sequence)
        except ValueError:
            new_sequence = 1
    else:
        new_sequence = 1
        
    return f"{base_prefix}{new_sequence:0{sequence_length}d}"

# --- Item Master Views ---


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def item_master_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        items = ItemMaster.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = ItemMasterSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('item_id'):
            data['item_id'] = generate_custom_id(ItemMaster, 'item_id', 'ITM', 7)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = ItemMasterSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def item_master_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        item = ItemMaster.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Item not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = ItemMasterSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        if data.get('unit_price') is None or data.get('unit_price') == '':
            data['unit_price'] = 0.00
        if data.get('ved_category') is None or data.get('ved_category') == '':
            data['ved_category'] = 'D'
        if data.get('abc_category') is None or data.get('abc_category') == '':
            data['abc_category'] = 'C'
        if 'is_VM' in data:
            data['is_VM'] = bool(data.get('is_VM'))
        
        serializer = ItemMasterSerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "Item soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def item_price_history(request, item_id):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    try:
        import json
        from_date_str = request.query_params.get('from_date') or request.GET.get('from_date')
        to_date_str = request.query_params.get('to_date') or request.GET.get('to_date')

        history = []
        grns = storesGRN.objects.filter(is_active__in=[True]).order_by('-date')

        if from_date_str:
            try:
                from_d = datetime.strptime(from_date_str, "%Y-%m-%d").date()
                grns = [g for g in grns if g.date and g.date >= from_d]
            except Exception:
                pass
        if to_date_str:
            try:
                to_d = datetime.strptime(to_date_str, "%Y-%m-%d").date()
                grns = [g for g in grns if g.date and g.date <= to_d]
            except Exception:
                pass

        for grn in grns:
            items = grn.items
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []
            if not isinstance(items, list):
                items = []
                
            for item in items:
                i_id = item.get('item_id') or item.get('id') or item.get('itemId')
                if str(i_id) == str(item_id):
                    # Find price rate
                    rate_val = item.get('rate') or item.get('purchase_price') or item.get('unit_price') or item.get('price') or item.get('net_amount') or item.get('unitPrice')
                    if rate_val is not None:
                        try:
                            rate = float(rate_val)
                            history.append({
                                "grn_number": grn.grn_number,
                                "date": grn.date.strftime("%Y-%m-%d") if grn.date else None,
                                "vendor_id": grn.vendor_id,
                                "rate": rate,
                                "quantity": item.get('quantity')
                            })
                        except (ValueError, TypeError):
                            pass

        if not history:
            return Response({"history": [], "lowest": 0, "highest": 0, "average": 0})

        rates = [h['rate'] for h in history]
        return Response({
            "history": history,
            "lowest": round(min(rates), 2),
            "highest": round(max(rates), 2),
            "average": round(sum(rates) / len(rates), 2),
        })

    except Exception as e:
        print("Error in item_price_history:", str(e))
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

# --- Department Views ---
def serialize_doc(doc):
    """Convert MongoDB document to JSON serializable"""
    doc['_id'] = str(doc['_id'])
    return doc


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def department_list_create(request):

    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    # ✅ GET → Fetch only active departments
    if request.method == 'GET':
        departments = list(
            department_collection.find(
                {"is_active": True}
            ).sort("created_date", -1)
        )

        data = [serialize_doc(doc) for doc in departments]
        return Response(data)

    # ✅ POST → Insert new department
    elif request.method == 'POST':
        data = request.data.copy()

        # Generate department_code if not provided
        if not data.get('department_code'):
            last = department_collection.find_one(
                {},
                sort=[("department_code", -1)]
            )

            if last and last.get('department_code'):
                last_num = int(last['department_code'].replace('DEPT', ''))
                new_code = f"DEPT{str(last_num + 1).zfill(3)}"
            else:
                new_code = "DEPT001"

            data['department_code'] = new_code

        # Add audit fields
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        data['hospital_code'] = hospital_code
        data['created_date'] = timezone.now().isoformat()
        data['is_active'] = True

        # Insert into MongoDB
        result = department_collection.insert_one(dict(data))

        # Return inserted document
        inserted_doc = department_collection.find_one({"_id": result.inserted_id})
        return Response(serialize_doc(inserted_doc), status=status.HTTP_201_CREATED)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def department_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        item = Department.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Department not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = DepartmentSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = DepartmentSerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.lastmodified_by = employee_id
        item.save()
        return Response({"message": "Department soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

# --- Group Views ---
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def group_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        items = Group.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = GroupSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('group_id'):
            data['group_id'] = generate_custom_id_without_fy(Group, 'group_id', 'GRP', 5)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = GroupSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def group_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        item = Group.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Group not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = GroupSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()

        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = GroupSerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "Group soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

# --- Category Views ---
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def category_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        items = Category.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = CategorySerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('category_id'):
            data['category_id'] = generate_custom_id_without_fy(Category, 'category_id', 'CAT', 5)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
    
        serializer = CategorySerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def category_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        item = Category.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Category not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = CategorySerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()

        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = CategorySerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "Category soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

# --- Group Type Views ---
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def group_type_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        items = GroupType.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = GroupTypeSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('group_type_id'):
            data['group_type_id'] = generate_custom_id_without_fy(GroupType, 'group_type_id', 'GRPT', 5)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = GroupTypeSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def group_type_detail(request, pk):
    print("auth-user-id", request.data.get('auth-user-id'))
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        item = GroupType.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "GroupType not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = GroupTypeSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()

        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = GroupTypeSerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.lastmodified_by = employee_id
        item.save()
        return Response({"message": "GroupType soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)


# --- Rack Views ---
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def rack_master_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        items = Rack.objects.filter(is_active__in=[True]).order_by('rack_name')
        serializer = RackSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('rack_id'):
            data['rack_id'] = generate_custom_id_without_fy(Rack, 'rack_id', 'RCK', 4)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = RackSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def rack_master_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        item = Rack.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Rack not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = RackSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = RackSerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.lastmodified_by = employee_id
        item.save()
        return Response({"message": "Rack soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)


# --- Shelf Views ---
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def shelf_master_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        rack_id = request.query_params.get('rack_id')
        queryset = Shelf.objects.filter(is_active__in=[True])
        if rack_id:
            queryset = queryset.filter(rack_id=rack_id)
        items = queryset.order_by('shelf_name')
        serializer = ShelfSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('shelf_id'):
            data['shelf_id'] = generate_custom_id_without_fy(Shelf, 'shelf_id', 'SHF', 4)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = ShelfSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def shelf_master_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        item = Shelf.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Shelf not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = ShelfSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = ShelfSerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.lastmodified_by = employee_id
        item.save()
        return Response({"message": "Shelf soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)


# --- Stores GRN Views ---
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_grn_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        from_date = request.query_params.get('from_date')
        to_date = request.query_params.get('to_date')

        queryset = storesGRN.objects.filter(is_active__in=[True]).order_by('-created_date')
        
        if from_date and to_date:
            queryset = queryset.filter(date__range=[from_date, to_date])
            
        serializer = StoresGRNSerializer(queryset, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        
        # Check if this is a filter request (search by date range)
        from_date = data.get('from_date')
        to_date = data.get('to_date')
        
        if from_date or to_date:
            queryset = storesGRN.objects.filter(is_active__in=[True]).order_by('-created_date')
            if from_date and to_date:
                queryset = queryset.filter(date__range=[from_date, to_date])
            elif from_date:
                queryset = queryset.filter(date__gte=from_date)
            elif to_date:
                queryset = queryset.filter(date__lte=to_date)
            
            serializer = StoresGRNSerializer(queryset, many=True)
            return Response(serializer.data)

        # Auto-generate GRN number
        if not data.get('grn_number'):
            # SGRN252600001
            fy_str = get_financial_year_string()
            prefix = f"SGRN{fy_str}"
            
            # Simple sequence generator
            last_record = storesGRN.objects.filter(grn_number__startswith=prefix).order_by('-created_date').first()
            if last_record and last_record.grn_number:
                try:
                    last_sequence = int(last_record.grn_number.replace(prefix, ''))
                    new_sequence = last_sequence + 1
                except ValueError:
                    new_sequence = 1
            else:
                new_sequence = 1
            
            data['grn_number'] = f"{prefix}{new_sequence:05d}"
            
        # Initial Payment Status
        if 'payment_status' not in data or not data['payment_status']:
            data['payment_status'] = [{
                "status": "Not Paid",
                "amount_paid": 0,
                "pending_amount": data.get('net_invoice_amount', 0),
                "payment_method": None,
                "payment_details": None,
                "paid_by": None
            }]
        elif isinstance(data.get('payment_status'), str):
            import json
            try:
                data['payment_status'] = json.loads(data['payment_status'])
            except:
                pass
            
        data['total_amount_paid'] = 0
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        
        # Parse items if strictly stringified
        if isinstance(data.get('items'), str):
            import json
            try:
                data['items'] = json.loads(data['items'])
            except:
                pass
            
        serializer = StoresGRNSerializer(data=data)
        if serializer.is_valid():
            grn_instance = serializer.save()
            
            # Update Item quantities & track pre/post approval stock
            # IMPORTANT: Stock is ONLY added to ItemMaster.total_quantity if the GRN is approved
            items = grn_instance.items
            if isinstance(items, list):
                items_updated = False
                for item_data in items:
                    if isinstance(item_data, dict):
                        item_id = item_data.get('item_id') or item_data.get('id') or item_data.get('itemId')
                        quantity = item_data.get('quantity', 0)
                        free = item_data.get('free', 0)
                        
                        try:
                            quantity = int(quantity)
                        except (ValueError, TypeError):
                            quantity = 0
                            
                        try:
                            free = int(free)
                        except (ValueError, TypeError):
                            free = 0
                            
                        total_addition = quantity + free
                        
                        if item_id:
                            try:
                                item_obj = ItemMaster.objects.get(item_id=str(item_id))
                                stock_before = item_obj.total_quantity or 0
                                if grn_instance.is_approved:
                                    stock_after = stock_before + total_addition
                                    item_obj.total_quantity = stock_after
                                    item_obj.save()
                                else:
                                    stock_after = stock_before
                                
                                item_data['quantity_before_approval'] = stock_before
                                item_data['added_quantity'] = total_addition
                                item_data['quantity_after_approval'] = stock_after
                                items_updated = True
                            except ItemMaster.DoesNotExist:
                                item_data['quantity_before_approval'] = 0
                                item_data['added_quantity'] = total_addition
                                item_data['quantity_after_approval'] = total_addition if grn_instance.is_approved else 0
                                items_updated = True

                if items_updated:
                    grn_instance.items = items
                    grn_instance.save()
                            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def stores_grn_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    try:
        grn = storesGRN.objects.filter(grn_number=pk, is_active__in=[True]).first()
        if not grn:
            from bson import ObjectId
            grn = storesGRN.objects.filter(_id=ObjectId(pk), is_active__in=[True]).first()
    except Exception:
        pass
        
    if not grn:
        return Response({"error": "GRN not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = StoresGRNSerializer(grn)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        import json
        data = request.data.copy()

        # --- Payment-safe merge logic ---
        # The frontend sends the full payment_status array. We trust the frontend to have
        # built the correct full array (existing + new entries). We only need to ensure that
        # if the incoming array is SHORTER than the stored array (i.e. frontend accidentally
        # lost entries), we use the longer stored array and only append truly new entries.
        incoming_payments = data.get('payment_status', None)
        if incoming_payments is not None:
            if isinstance(incoming_payments, str):
                try:
                    incoming_payments = json.loads(incoming_payments)
                except Exception:
                    incoming_payments = []

            # Get the existing stored payments
            existing_payments = grn.payment_status
            if isinstance(existing_payments, str):
                try:
                    existing_payments = json.loads(existing_payments)
                except Exception:
                    existing_payments = []
            if not isinstance(existing_payments, list):
                existing_payments = []

            # Collect timestamps of already stored payments
            existing_timestamps = {p.get('timestamp') for p in existing_payments if p.get('timestamp')}

            # Append any new payments from the incoming data that are not yet stored
            merged = list(existing_payments)
            for p in incoming_payments:
                if p.get('timestamp') not in existing_timestamps:
                    merged.append(p)

            # If merged list is shorter or equal (i.e. incoming was missing history), use merged
            # which guarantees we never shrink the array
            data['payment_status'] = merged

        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = StoresGRNSerializer(grn, data=data, partial=True)
        if serializer.is_valid():
            # ── Stock update on approval ─────────────────────────────────────
            approving_now = (
                data.get('is_approved') is True
                and not grn.is_approved           # only if not already approved
            )
            if approving_now:
                items = grn.items
                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except Exception:
                        items = []
                if not isinstance(items, list):
                    items = []

                for item in items:
                    if isinstance(item, dict):
                        item_id = item.get('item_id') or item.get('id') or item.get('itemId')
                        qty = int(item.get('quantity') or 0)
                        free = int(item.get('free') or 0)
                        total_addition = qty + free
                        
                        if item_id:
                            try:
                                master = ItemMaster.objects.get(item_id=str(item_id))
                                stock_before = master.total_quantity or 0
                                stock_after = stock_before + total_addition
                                master.total_quantity = stock_after
                                master.save()

                                item['quantity_before_approval'] = stock_before
                                item['added_quantity'] = total_addition
                                item['quantity_after_approval'] = stock_after
                            except ItemMaster.DoesNotExist:
                                item['quantity_before_approval'] = 0
                                item['added_quantity'] = total_addition
                                item['quantity_after_approval'] = total_addition

                grn.items = items
                grn.is_approved = True
                grn.save()
            # ────────────────────────────────────────────────────────────────
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        storesGRN.objects.filter(grn_number=grn.grn_number).update(is_active=False)
        return Response({"message": "GRN soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db import connection
from datetime import datetime

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def get_stores_intents(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    from_date = request.data.get('from_date')
    to_date = request.data.get('to_date')
    department_filter = request.data.get('department')

    query = {
        "is_active": True
    }

    if department_filter:
        query["department"] = department_filter

    # Date filter
    if from_date or to_date:
        query["date"] = {}

        if from_date:
            query["date"]["$gte"] = datetime.strptime(from_date, "%Y-%m-%d")

        if to_date:
            query["date"]["$lte"] = datetime.strptime(to_date, "%Y-%m-%d")

    db = connection.cursor().db_conn

    intent_collection = db["hospital_storesintent"]
    dept_collection = db["hospital_department"]
    item_collection = db["hospital_itemmaster"]

    # ✅ Department mapping (from Global.backend_diagnostics_Departments and Department model)
    dept_map = {}
    for doc in department_collection.find({'is_active': True}):
        code = doc.get('department_code') or doc.get('department_id') or str(doc.get('_id'))
        name = doc.get('department_name')
        if code and name:
            dept_map[str(code)] = name
    for d in Department.objects.filter(is_active__in=[True]):
        if d.department_id and d.department_name and str(d.department_id) not in dept_map:
            dept_map[str(d.department_id)] = d.department_name

    # ✅ Item stock mapping
    item_map = {
        i["item_id"]: {
            "total_quantity": i.get("total_quantity", 0),
            "approved_quantity": i.get("approved_quantity", 0)
        }
        for i in item_collection.find({"is_active": True})
    }

    data = list(intent_collection.find(query).sort("created_date", -1))

    for d in data:
        d["_id"] = str(d["_id"])

        # ✅ Department name
        dept_code = d.get("department")
        d["department_name"] = dept_map.get(dept_code) or dept_code or "General"

        # ✅ Add stock inside items
        for item in d.get("items", []):
            item_id = item.get("item_id")

            stock_data = item_map.get(item_id, {})

            total_qty = stock_data.get("total_quantity", 0)
            approved_qty = stock_data.get("approved_quantity", 0)

            # ✅ Calculate available stock
            item["available_stock"] = total_qty - approved_qty
            item["total_stock"] = total_qty

    return Response(data)

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_stores_intent(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    data = request.data.copy()

    data['intent_id'] = generate_custom_id(
        storesIntent,
        'intent_id',
        'SINT',
        5
    )

    data['created_by'] = employee_id
    data['branch_code'] = branch_code
    data['outlet_code'] = outlet_code

    serializer = StoresIntentSerializer(data=data)

    if serializer.is_valid():
        serializer.save()
        return Response(
            {
                "message": "Created successfully",
                "data": serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_stores_intent(request, pk):
    employee_id  = request.data.get('auth-user-id')
    branch_code = request.data.get('auth-branch-code')
    hospital_code = request.data.get('auth-hospital-code')

    obj = get_object_or_404(storesIntent, intent_id=pk)
    if not obj.is_active:
        return Response({"error": "Intent not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)

    # Store old items to compare quantities if needed
    old_items = {it.get('item_id'): it.get('approved_quantity', 0) for it in (obj.items or []) if it.get('item_id')}

    data = request.data.copy()
    data['lastmodified_by'] = employee_id
    data['branch_code'] = branch_code
    data['hospital_code'] = hospital_code

    serializer = StoresIntentSerializer(obj, data=data, partial=True)

    if serializer.is_valid():
        instance = serializer.save()
        items = instance.items or []

        for item in items:
            item_id = item.get("item_id")
            new_qty = int(item.get("approved_quantity", 0))
            is_approved = item.get("approval", {}).get("approved", False)

            if is_approved and item_id:
                try:
                    item_obj = ItemMaster.objects.get(item_id=item_id)

                    # Logic: Only update ItemMaster if the quantity has actually changed
                    old_qty = int(old_items.get(item_id, 0))
                    diff = new_qty - old_qty

                    if diff != 0:
                        item_obj.approved_quantity += diff
                        item_obj.save()

                except ItemMaster.DoesNotExist:
                    continue

        # --- DEPT002: Save/accumulate approved items in Stores_LabApprovedItem ---
        dept_code = instance.department
        if dept_code == 'DEPT002':
            for item in items:
                item_id = item.get("item_id")
                is_approved = item.get("approval", {}).get("approved", False)
                new_qty = int(item.get("approved_quantity", 0))
                old_qty = int(old_items.get(item_id, 0)) if item_id else 0
                diff = new_qty - old_qty  # Only the newly approved quantity in this call

                if is_approved and item_id and diff > 0:
                    lab_item = Stores_LabApprovedItem.objects.filter(
                        item_id=item_id,
                        branch_code=branch_code,
                        hospital_code=hospital_code,
                    ).first()
                    if lab_item:
                        # Same item approved again (same branch/hospital) -> accumulate, don't duplicate
                        lab_item.quantity = (lab_item.quantity or 0) + diff
                        lab_item.lastmodified_by = employee_id
                        lab_item.save()
                    else:
                        Stores_LabApprovedItem.objects.create(
                            item_id=item_id,
                            name=item.get("name", ""),
                            hsn=item.get("hsn", None),
                            quantity=diff,
                            created_by=employee_id,
                            branch_code=branch_code,
                            hospital_code=hospital_code,
                        )
        # ---------------------------------------------------------------

        return Response({"message": "Updated successfully", "data": serializer.data})
    return Response(serializer.errors, status=400)





@api_view(['DELETE'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_intent(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    obj = get_object_or_404(storesIntent, intent_id=pk)
    if not obj.is_active:
        return Response({"error": "Intent not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)

    # Revert approved quantities in ItemMaster before soft deleting
    items = obj.items or []
    for item in items:
        item_id = item.get("item_id")
        approved_qty = int(item.get("approved_quantity", 0))
        is_item_approved = item.get("approval", {}).get("approved", False)

        if is_item_approved and item_id and approved_qty > 0:
            try:
                item_obj = ItemMaster.objects.get(item_id=item_id)
                item_obj.approved_quantity = max(0, item_obj.approved_quantity - approved_qty)
                item_obj.lastmodified_by = employee_id
                item_obj.branch_code = branch_code
                item_obj.outlet_code = outlet_code
                
                item_obj.save()
            except ItemMaster.DoesNotExist:
                continue

    storesIntent.objects.filter(intent_id=obj.intent_id).update(is_active=False, lastmodified_by=employee_id)

    return Response({"message": "Soft deleted successfully"})


# --- Lab Approved Items Views ---

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_stores_lab_approved_items(request):
    """Return all Stores_LabApprovedItem records with remaining balance calculated."""
    employee_id  = request.data.get('auth-user-id')
    branch_code = request.data.get('auth-branch-code')
    hospital_code = request.data.get('auth-hospital-code')

    items_qs = Stores_LabApprovedItem.objects.all().order_by('-date')
    serializer = Stores_LabApprovedItemSerializer(items_qs, many=True)

    result = []
    for item_obj, item_data in zip(items_qs, serializer.data):
        qty = item_data.get('quantity') or 0
        used = item_data.get('used_qty') or 0
        remaining = qty - used
        result.append({
            **dict(item_data),
            'id': str(item_obj.pk),   # always inject the real PK as a string
            'remaining_qty': remaining
        })

    return Response(result)



@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_daily_usage_items(request):
    employee_id  = request.data.get('auth-user-id')
    branch_code = request.data.get('auth-branch-code')
    hospital_code = request.data.get('auth-hospital-code')
    used_date = request.data.get('used_date') or datetime.now().strftime('%Y-%m-%d')

    items_to_process = []
    
    # Check if request has bulk items
    bulk_items = request.data.get('items')
    if bulk_items and isinstance(bulk_items, list):
        items_to_process = bulk_items
    else:
        # Single item request
        item_id = request.data.get('item_id') or request.data.get('lab_approved_item_id')
        new_used_qty = request.data.get('used_qty')
        if not item_id or str(item_id).strip().lower() in ('none', 'null', 'undefined'):
            return Response({'error': 'item_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        if new_used_qty is None:
            return Response({'error': 'used_qty is required'}, status=status.HTTP_400_BAD_REQUEST)
        items_to_process = [{'item_id': item_id, 'used_qty': new_used_qty}]

    # Validate all items first
    validated_items = []
    for it in items_to_process:
        it_id = it.get('item_id')
        it_qty = it.get('used_qty')
        if not it_id:
            return Response({'error': 'item_id is required for all items'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            it_qty = int(it_qty)
        except (ValueError, TypeError):
            return Response({'error': f'used_qty must be an integer for item {it_id}'}, status=status.HTTP_400_BAD_REQUEST)
        if it_qty <= 0:
            return Response({'error': f'used_qty must be greater than 0 for item {it_id}'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            approved_item = Stores_LabApprovedItem.objects.get(item_id=it_id)
        except Stores_LabApprovedItem.DoesNotExist:
            return Response({'error': f'Lab approved item not found: {it_id}'}, status=status.HTTP_404_NOT_FOUND)

        current_used = approved_item.used_qty or 0
        total_after = current_used + it_qty
        if total_after > approved_item.quantity:
            remaining = approved_item.quantity - current_used
            return Response({
                'error': f'Cannot exceed approved quantity for item "{approved_item.name}". Remaining balance: {remaining}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        validated_items.append((approved_item, it_qty))

    # Get or create the usage detail for the date
    usage_detail, created = Stores_LabUsedQtyDetail.objects.get_or_create(
        date=used_date,
        defaults={
            'items': [],
            'created_by': employee_id,
            'branch_code': branch_code,
            'hospital_code': hospital_code,
        }
    )
    import json
    existing_items = usage_detail.items
    if isinstance(existing_items, str):
        try:
            existing_items = json.loads(existing_items)
        except Exception:
            existing_items = []
    if not isinstance(existing_items, list):
        existing_items = []

    formatted_date = str(used_date)[:10]

    for approved_item, it_qty in validated_items:
        # 1) Update cumulative used_qty on Stores_LabApprovedItem
        approved_item.used_qty = (approved_item.used_qty or 0) + it_qty
        approved_item.lastmodified_by = employee_id
        approved_item.save()

        # 2) Always store each usage entry separately into usage_detail items list with date
        existing_items.append({
            'date': formatted_date,
            'item_id': approved_item.item_id,
            'name': approved_item.name,
            'hsn': approved_item.hsn,
            'used_qty': it_qty,
            'created_by': employee_id,
            'lastmodified_by': employee_id,
        })

    usage_detail.items = existing_items
    usage_detail.lastmodified_by = employee_id
    usage_detail.save()

    # Direct PyMongo update to ensure native BSON Array of Objects in MongoDB, bypassing Djongo JSONField stringification
    try:
        from ..dbcollection import hms_db
        hms_db["hospital_stores_labusedqtydetail"].update_one(
            {"$or": [{"date": usage_detail.date}, {"date": used_date}]},
            {"$set": {"items": existing_items}}
        )
    except Exception:
        pass

    return Response({
        'message': 'Usage recorded successfully',
        'processed_count': len(validated_items)
    })


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_lab_used_qty_report(request):
    """
    Fetch date-wise lab daily usage records within a date range (from_date to to_date).
    Matches created_by / lastmodified_by against backend_diagnostics_profile collection 
    (from dbcollection.py) on employeeId to return employeeName.
    """
    try:
        from_date = request.query_params.get('from_date') or request.query_params.get('startDate')
        to_date = request.query_params.get('to_date') or request.query_params.get('endDate')
        single_date = request.query_params.get('date')

        if single_date and not from_date and not to_date:
            from_date = single_date
            to_date = single_date

        from ..dbcollection import hms_db, profile_collection
        col = hms_db["hospital_stores_labusedqtydetail"]
        raw_docs = list(col.find({}))

        # Collect all employee IDs to resolve names in bulk
        employee_ids = set()
        for doc in raw_docs:
            if doc.get('created_by'):
                employee_ids.add(str(doc.get('created_by')).strip())
            if doc.get('lastmodified_by'):
                employee_ids.add(str(doc.get('lastmodified_by')).strip())
            items = doc.get('items') or []
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        if it.get('created_by'):
                            employee_ids.add(str(it.get('created_by')).strip())
                        if it.get('lastmodified_by'):
                            employee_ids.add(str(it.get('lastmodified_by')).strip())

        # Map employeeId -> employeeName from backend_diagnostics_profile collection
        employee_map = {}
        if employee_ids:
            profiles = list(profile_collection.find(
                {"employeeId": {"$in": list(employee_ids)}},
                {"employeeId": 1, "employeeName": 1, "name": 1, "_id": 0}
            ))
            for p in profiles:
                emp_id = str(p.get("employeeId") or "").strip()
                emp_name = p.get("employeeName") or p.get("name") or ""
                if emp_id and emp_name:
                    employee_map[emp_id] = emp_name

        reports = []
        flattened_items = []

        for doc in raw_docs:
            doc_date_raw = doc.get('date')
            doc_date_str = ""
            if isinstance(doc_date_raw, datetime):
                doc_date_str = doc_date_raw.strftime('%Y-%m-%d')
            elif isinstance(doc_date_raw, dict) and '$date' in doc_date_raw:
                doc_date_str = str(doc_date_raw['$date'])[:10]
            elif doc_date_raw:
                doc_date_str = str(doc_date_raw)[:10]

            c_by = str(doc.get('created_by') or '').strip()
            m_by = str(doc.get('lastmodified_by') or '').strip()
            c_by_name = employee_map.get(c_by, c_by)
            m_by_name = employee_map.get(m_by, m_by)

            items_raw = doc.get('items') or []
            if isinstance(items_raw, str):
                try:
                    items_raw = json.loads(items_raw)
                except Exception:
                    items_raw = []
            if not isinstance(items_raw, list):
                items_raw = []

            doc_branch = doc.get('branch_code') or doc.get('branch') or doc.get('auth-branch-code') or request.query_params.get('auth-branch-code') or request.query_params.get('branch_code') or 'SHB001'
            doc_hospital = doc.get('hospital_code') or doc.get('hospital') or doc.get('auth-hospital-code') or request.query_params.get('auth-hospital-code') or request.query_params.get('hospital_code') or 'SH001'

            processed_items = []
            for it in items_raw:
                if not isinstance(it, dict):
                    continue
                it_date = str(it.get('date') or doc_date_str)[:10]

                # Filter by date range if provided
                if from_date and it_date < from_date:
                    continue
                if to_date and it_date > to_date:
                    continue

                it_c_by = str(it.get('created_by') or c_by).strip()
                it_m_by = str(it.get('lastmodified_by') or m_by).strip()

                item_obj = {
                    'date': it_date,
                    'item_id': it.get('item_id', ''),
                    'name': it.get('name', ''),
                    'hsn': it.get('hsn', ''),
                    'used_qty': it.get('used_qty', 0),
                    'created_by': it_c_by,
                    'created_by_name': employee_map.get(it_c_by, it_c_by),
                    'lastmodified_by': it_m_by,
                    'lastmodified_by_name': employee_map.get(it_m_by, it_m_by),
                    'branch_code': it.get('branch_code') or doc_branch,
                    'hospital_code': it.get('hospital_code') or doc_hospital,
                }
                processed_items.append(item_obj)
                flattened_items.append(item_obj)

            if processed_items:
                reports.append({
                    'record_date': doc_date_str,
                    'created_by': c_by,
                    'created_by_name': c_by_name,
                    'lastmodified_by': m_by,
                    'lastmodified_by_name': m_by_name,
                    'branch_code': doc_branch,
                    'hospital_code': doc_hospital,
                    'items': processed_items
                })

        # Sort descending by date
        flattened_items.sort(key=lambda x: x['date'], reverse=True)
        reports.sort(key=lambda x: x['record_date'], reverse=True)

        return Response({
            'success': True,
            'from_date': from_date,
            'to_date': to_date,
            'total_items_count': len(flattened_items),
            'reports': reports,
            'flattened_items': flattened_items
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        return Response({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- General Store Vendor Views ---

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def general_store_vendor_list_create(request):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    if request.method == 'GET':
        vendors = list(GeneralStoreVendor.objects.filter(is_active__in=[True]))
        vendors.sort(key=lambda x: x.created_date if x.created_date else timezone.now(), reverse=True)
        serializer = GeneralStoreVendorSerializer(vendors, many=True)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('vendor_id'):
            data['vendor_id'] = generate_custom_id(GeneralStoreVendor, 'vendor_id', 'GSV', 5)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        data['hospital_code'] = hospital_code

        serializer = GeneralStoreVendorSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "data": serializer.data}, status=status.HTTP_201_CREATED)
        return Response({"success": False, "error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def general_store_vendor_detail(request, pk):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    try:
        vendor = GeneralStoreVendor.objects.filter(pk=pk, is_active__in=[True]).first()
        if not vendor:
            return Response({"success": False, "error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = GeneralStoreVendorSerializer(vendor)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = GeneralStoreVendorSerializer(vendor, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)
        return Response({"success": False, "error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        vendor.is_active = False
        vendor.save()
        return Response({"success": True, "message": "Vendor deleted successfully"}, status=status.HTTP_200_OK)


# --- Vending Machine API Views ---

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def vending_machine_sales_list_create(request):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')

    if request.method == 'GET':
        from_date = request.query_params.get('from_date') or request.GET.get('from_date')
        to_date = request.query_params.get('to_date') or request.GET.get('to_date')
        item_id = request.query_params.get('item_id') or request.GET.get('item_id')

        qs = VendingMachineSale.objects.filter(is_active__in=[True]).order_by('-date', '-created_date')
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        if item_id:
            qs = qs.filter(item_id=item_id)

        serializer = VendingMachineSaleSerializer(qs, many=True)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy()
        if isinstance(data, list):
            saved_records = []
            for item in data:
                if not item.get('sale_id'):
                    item['sale_id'] = generate_custom_id_without_fy(VendingMachineSale, 'sale_id', 'VMS', 8)
                item['created_by'] = employee_id
                item['branch_code'] = branch_code
                item['outlet_code'] = outlet_code
                ser = VendingMachineSaleSerializer(data=item)
                if ser.is_valid():
                    sale_inst = ser.save()
                    # Add quantity_sold to approved_quantity in ItemMaster
                    if sale_inst.item_id:
                        it_obj = ItemMaster.objects.filter(item_id=sale_inst.item_id, is_active__in=[True]).first()
                        if it_obj:
                            it_obj.approved_quantity = int(it_obj.approved_quantity or 0) + int(sale_inst.quantity_sold or 1)
                            it_obj.save()
                    saved_records.append(ser.data)
            return Response({"success": True, "data": saved_records}, status=status.HTTP_201_CREATED)

        if not data.get('sale_id'):
            data['sale_id'] = generate_custom_id_without_fy(VendingMachineSale, 'sale_id', 'VMS', 8)

        qty = int(data.get('quantity_sold') or 1)
        price = float(data.get('unit_price') or 0.0)
        data['quantity_sold'] = qty
        data['unit_price'] = price
        data['total_sales_amount'] = float(data.get('total_sales_amount') or (qty * price))
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = VendingMachineSaleSerializer(data=data)
        if serializer.is_valid():
            sale_inst = serializer.save()
            # Add quantity_sold to approved_quantity in ItemMaster
            if sale_inst.item_id:
                it_obj = ItemMaster.objects.filter(item_id=sale_inst.item_id, is_active__in=[True]).first()
                if it_obj:
                    it_obj.approved_quantity = int(it_obj.approved_quantity or 0) + int(sale_inst.quantity_sold or 1)
                    it_obj.save()
            return Response({"success": True, "data": serializer.data}, status=status.HTTP_201_CREATED)
        return Response({"success": False, "error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def vending_machine_sales_import_excel(request):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')

    excel_file = request.FILES.get('file')
    sales_json_list = request.data.get('items')

    imported_sales = []
    
    # If file uploaded
    if excel_file:
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            from datetime import datetime

            z = zipfile.ZipFile(excel_file)
            sheet_tree = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            rows = sheet_tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
            
            shared_strings = []
            if 'xl/sharedStrings.xml' in z.namelist():
                tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
                for elem in tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                    text = ''.join([t.text for t in elem.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t') if t.text])
                    shared_strings.append(text)

            row_data_list = []
            for r in rows:
                row_vals = []
                for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                    t = c.attrib.get('t')
                    v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                    val = v.text if v is not None else ''
                    if t == 's' and val != '':
                        try:
                            val = shared_strings[int(val)]
                        except Exception:
                            pass
                    row_vals.append(val)
                row_data_list.append(row_vals)

            if len(row_data_list) > 1:
                header = [str(h).strip().lower() for h in row_data_list[0]]
                
                # Map column indices
                def get_idx(candidates):
                    for cand in candidates:
                        for idx, h in enumerate(header):
                            if cand in h:
                                return idx
                    return -1

                id_idx = get_idx(['id', 'raw_id'])
                prod_id_idx = get_idx(['product id', 'product_id', 'item_id'])
                name_idx = get_idx(['name', 'product name', 'product_name'])
                brand_idx = get_idx(['brand name', 'brand'])
                cat_idx = get_idx(['category name', 'category'])
                price_idx = get_idx(['price', 'rate', 'amount'])
                created_idx = get_idx(['createdat', 'created_at', 'date'])
                qty_idx = get_idx(['qty', 'quantity', 'sold'])
                img_idx = get_idx(['imagelink', 'image_link', 'image'])

                for row in row_data_list[1:]:
                    if not row or not any(row):
                        continue
                    p_name = row[name_idx] if name_idx != -1 and name_idx < len(row) else 'Vending Item'
                    p_id = row[prod_id_idx] if prod_id_idx != -1 and prod_id_idx < len(row) else ''
                    p_price_str = row[price_idx] if price_idx != -1 and price_idx < len(row) else '0'
                    p_date_str = row[created_idx] if created_idx != -1 and created_idx < len(row) else ''
                    p_qty_str = row[qty_idx] if qty_idx != -1 and qty_idx < len(row) else '1'
                    brand_name = row[brand_idx] if brand_idx != -1 and brand_idx < len(row) else ''
                    cat_name = row[cat_idx] if cat_idx != -1 and cat_idx < len(row) else ''
                    image_link = row[img_idx] if img_idx != -1 and img_idx < len(row) else None

                    try:
                        price = float(p_price_str)
                    except Exception:
                        price = 0.0

                    try:
                        qty = int(float(p_qty_str))
                    except Exception:
                        qty = 1

                    sale_date = timezone.now().date()
                    if p_date_str:
                        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
                            try:
                                sale_date = datetime.strptime(p_date_str.strip(), fmt).date()
                                break
                            except Exception:
                                pass

                    # Dynamic resolution for Group, GroupType, Department, Category, Vendor
                    grp = Group.objects.filter(group_name__iexact='Vending Machine', is_active__in=[True]).first()
                    if not grp:
                        grp_id = generate_custom_id_without_fy(Group, 'group_id', 'GRP', 5)
                        grp = Group.objects.create(group_id=grp_id, group_name='Vending Machine', is_active=True, created_by=employee_id, branch_code=branch_code, outlet_code=outlet_code)

                    grpt = GroupType.objects.filter(group_type_name__iexact='Vending Machine', is_active__in=[True]).first()
                    if not grpt:
                        grpt_id = generate_custom_id_without_fy(GroupType, 'group_type_id', 'GRPT', 5)
                        grpt = GroupType.objects.create(group_type_id=grpt_id, group_type_name='Vending Machine', is_active=True, created_by=employee_id, branch_code=branch_code, outlet_code=outlet_code)

                    dept = Department.objects.filter(department_name__iexact='Vending Machine', is_active__in=[True]).first()
                    if not dept:
                        dept_id = generate_custom_id_without_fy(Department, 'department_id', 'DPT', 5)
                        dept = Department.objects.create(department_id=dept_id, department_name='Vending Machine', is_active=True, created_by=employee_id, branch_code=branch_code, outlet_code=outlet_code)

                    cat_obj = None
                    if cat_name:
                        cat_obj = Category.objects.filter(category_name__iexact=cat_name.strip(), is_active__in=[True]).first()
                        if not cat_obj:
                            cat_id = generate_custom_id_without_fy(Category, 'category_id', 'CAT', 5)
                            cat_obj = Category.objects.create(category_id=cat_id, category_name=cat_name.strip(), is_active=True, created_by=employee_id, branch_code=branch_code, outlet_code=outlet_code)

                    vendor_obj = None
                    if brand_name:
                        vendor_obj = GeneralStoreVendor.objects.filter(name__iexact=brand_name.strip(), is_active__in=[True]).first()
                        if not vendor_obj:
                            vendor_id = generate_custom_id(GeneralStoreVendor, 'vendor_id', 'GSV', 5)
                            vendor_obj = GeneralStoreVendor.objects.create(vendor_id=vendor_id, name=brand_name.strip(), vendor_type='BOTH', is_active=True, created_by=employee_id, branch_code=branch_code, outlet_code=outlet_code)

                    # Auto-match or create/update ItemMaster with proper IDs and add approved_quantity
                    item_master_obj = None
                    if p_id:
                        item_master_obj = ItemMaster.objects.filter(item_id=p_id, is_active__in=[True]).first()
                    if not item_master_obj and p_name:
                        item_master_obj = ItemMaster.objects.filter(itemName__iexact=p_name.strip(), is_active__in=[True]).first()

                    if not item_master_obj:
                        item_master_obj = ItemMaster(item_id=p_id or generate_custom_id(ItemMaster, 'item_id', 'ITM', 7))

                    item_master_obj.itemName = p_name.strip()
                    item_master_obj.group = grp.group_id if grp else None
                    item_master_obj.group_type = grpt.group_type_id if grpt else None
                    item_master_obj.category = cat_obj.category_id if cat_obj else item_master_obj.category
                    item_master_obj.department = dept.department_id if dept else item_master_obj.department
                    item_master_obj.supplier = vendor_obj.vendor_id if vendor_obj else item_master_obj.supplier
                    item_master_obj.manufacturer = vendor_obj.vendor_id if vendor_obj else item_master_obj.manufacturer
                    item_master_obj.unit_price = price if price > 0 else (item_master_obj.unit_price or 0.00)
                    item_master_obj.approved_quantity = int(item_master_obj.approved_quantity or 0) + qty
                    item_master_obj.is_VM = True
                    item_master_obj.is_active = True
                    item_master_obj.created_by = item_master_obj.created_by or employee_id
                    item_master_obj.branch_code = item_master_obj.branch_code or branch_code
                    item_master_obj.outlet_code = item_master_obj.outlet_code or outlet_code
                    item_master_obj.save()

                    sale_rec = VendingMachineSale(
                        sale_id=generate_custom_id_without_fy(VendingMachineSale, 'sale_id', 'VMS', 8),
                        item_id=item_master_obj.item_id if item_master_obj else p_id,
                        product_name=p_name.strip(),
                        brand_id=vendor_obj.vendor_id if vendor_obj else None,
                        brand_name=vendor_obj.name if vendor_obj else brand_name.strip(),
                        category_id=cat_obj.category_id if cat_obj else None,
                        category_name=cat_obj.category_name if cat_obj else cat_name.strip(),
                        unit_price=price,
                        quantity_sold=qty,
                        total_sales_amount=price * qty,
                        date=sale_date,
                        image_link=image_link,
                        excel_product_id=p_id,
                        source='EXCEL_IMPORT',
                        created_by=employee_id,
                        branch_code=branch_code,
                        outlet_code=outlet_code
                    )
                    sale_rec.save()
                    imported_sales.append(VendingMachineSaleSerializer(sale_rec).data)

        except Exception as e:
            return Response({"success": False, "error": f"Failed to parse Excel file: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    elif sales_json_list:
        if isinstance(sales_json_list, str):
            sales_json_list = json.loads(sales_json_list)
        for item in sales_json_list:
            p_name = item.get('name') or item.get('product_name') or 'Vending Item'
            p_id = item.get('Product Id') or item.get('product_id') or item.get('item_id') or ''
            brand_name = item.get('Brand Name') or item.get('brand_name') or item.get('brand') or ''
            cat_name = item.get('Category Name') or item.get('category_name') or item.get('category') or ''
            price = float(item.get('Price') or item.get('price') or 0.0)
            qty = int(item.get('quantity_sold') or item.get('quantity') or 1)
            p_date_str = item.get('createdAt') or item.get('date') or ''
            image_link = item.get('imageLink') or item.get('image_link') or None

            sale_date = timezone.now().date()
            if p_date_str:
                for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
                    try:
                        sale_date = datetime.strptime(str(p_date_str).strip(), fmt).date()
                        break
                    except Exception:
                        pass

            # Dynamic resolution
            grp = Group.objects.filter(group_name__iexact='Vending Machine', is_active__in=[True]).first()
            grpt = GroupType.objects.filter(group_type_name__iexact='Vending Machine', is_active__in=[True]).first()
            dept = Department.objects.filter(department_name__iexact='Vending Machine', is_active__in=[True]).first()

            cat_obj = None
            if cat_name:
                cat_obj = Category.objects.filter(category_name__iexact=cat_name.strip(), is_active__in=[True]).first()
                if not cat_obj:
                    cat_id = generate_custom_id_without_fy(Category, 'category_id', 'CAT', 5)
                    cat_obj = Category.objects.create(category_id=cat_id, category_name=cat_name.strip(), is_active=True, created_by=employee_id, branch_code=branch_code, outlet_code=outlet_code)

            vendor_obj = None
            if brand_name:
                vendor_obj = GeneralStoreVendor.objects.filter(name__iexact=brand_name.strip(), is_active__in=[True]).first()
                if not vendor_obj:
                    vendor_id = generate_custom_id(GeneralStoreVendor, 'vendor_id', 'GSV', 5)
                    vendor_obj = GeneralStoreVendor.objects.create(vendor_id=vendor_id, name=brand_name.strip(), vendor_type='BOTH', is_active=True, created_by=employee_id, branch_code=branch_code, outlet_code=outlet_code)

            item_master_obj = None
            if p_id:
                item_master_obj = ItemMaster.objects.filter(item_id=p_id, is_active__in=[True]).first()
            if not item_master_obj and p_name:
                item_master_obj = ItemMaster.objects.filter(itemName__iexact=p_name.strip(), is_active__in=[True]).first()

            if not item_master_obj:
                item_master_obj = ItemMaster(item_id=p_id or generate_custom_id(ItemMaster, 'item_id', 'ITM', 7))

            item_master_obj.itemName = p_name.strip()
            item_master_obj.group = grp.group_id if grp else None
            item_master_obj.group_type = grpt.group_type_id if grpt else None
            item_master_obj.category = cat_obj.category_id if cat_obj else item_master_obj.category
            item_master_obj.department = dept.department_id if dept else item_master_obj.department
            item_master_obj.supplier = vendor_obj.vendor_id if vendor_obj else item_master_obj.supplier
            item_master_obj.manufacturer = vendor_obj.vendor_id if vendor_obj else item_master_obj.manufacturer
            item_master_obj.unit_price = price if price > 0 else (item_master_obj.unit_price or 0.00)
            item_master_obj.approved_quantity = int(item_master_obj.approved_quantity or 0) + qty
            item_master_obj.is_VM = True
            item_master_obj.is_active = True
            item_master_obj.created_by = item_master_obj.created_by or employee_id
            item_master_obj.branch_code = item_master_obj.branch_code or branch_code
            item_master_obj.outlet_code = item_master_obj.outlet_code or outlet_code
            item_master_obj.save()

            sale_rec = VendingMachineSale(
                sale_id=generate_custom_id_without_fy(VendingMachineSale, 'sale_id', 'VMS', 8),
                item_id=item_master_obj.item_id if item_master_obj else p_id,
                product_name=p_name.strip(),
                brand_id=vendor_obj.vendor_id if vendor_obj else None,
                brand_name=vendor_obj.name if vendor_obj else brand_name.strip(),
                category_id=cat_obj.category_id if cat_obj else None,
                category_name=cat_obj.category_name if cat_obj else cat_name.strip(),
                unit_price=price,
                quantity_sold=qty,
                total_sales_amount=price * qty,
                date=sale_date,
                image_link=image_link,
                excel_product_id=p_id,
                source='EXCEL_IMPORT',
                created_by=employee_id,
                branch_code=branch_code,
                outlet_code=outlet_code
            )
            sale_rec.save()
            imported_sales.append(VendingMachineSaleSerializer(sale_rec).data)

    return Response({
        "success": True,
        "message": f"Successfully imported {len(imported_sales)} sales records.",
        "data": imported_sales
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def vending_machine_report(request):
    from_date_str = request.query_params.get('from_date') or request.GET.get('from_date')
    to_date_str = request.query_params.get('to_date') or request.GET.get('to_date')

    def _safe_num(v):
        if v is None or v == '':
            return 0.0
        try:
            return float(str(v))
        except Exception:
            return 0.0

    # 1. Load Category & Department mappings
    cat_map = {
        c.category_id: c.category_name
        for c in Category.objects.filter(is_active__in=[True])
        if c.category_id and c.category_name
    }
    dept_map = {}
    for doc in department_collection.find({'is_active': True}):
        code = doc.get('department_code') or doc.get('department_id') or str(doc.get('_id'))
        name = doc.get('department_name')
        if code and name:
            dept_map[str(code)] = name
    for d in Department.objects.filter(is_active__in=[True]):
        if d.department_id and d.department_name and str(d.department_id) not in dept_map:
            dept_map[str(d.department_id)] = d.department_name

    vendor_map = {
        str(v.vendor_id): v.name
        for v in GeneralStoreVendor.objects.filter(is_active__in=[True])
        if v.vendor_id and v.name
    }

    # 2. Get all VM items and index ItemMaster
    vm_items = list(ItemMaster.objects.filter(is_VM__in=[True], is_active__in=[True]))
    all_active_items = list(ItemMaster.objects.filter(is_active__in=[True]))
    item_master_by_id = {item.item_id: item for item in all_active_items if item.item_id}
    item_master_by_name = {item.itemName.strip().lower(): item for item in all_active_items if item.itemName}

    # 3. Fetch Sales
    sales_qs = VendingMachineSale.objects.filter(is_active__in=[True])
    if from_date_str:
        sales_qs = sales_qs.filter(date__gte=from_date_str)
    if to_date_str:
        sales_qs = sales_qs.filter(date__lte=to_date_str)

    # 4. Fetch Approved GRNs
    grn_qs = storesGRN.objects.filter(is_active__in=[True], is_approved__in=[True])
    if from_date_str:
        grn_qs = grn_qs.filter(date__gte=from_date_str)
    if to_date_str:
        grn_qs = grn_qs.filter(date__lte=to_date_str)

    # 5. Process and Aggregate Sales by Canonical Product Key
    sales_by_item = {}
    for sale in sales_qs:
        matched_item = None
        if sale.item_id and sale.item_id in item_master_by_id:
            matched_item = item_master_by_id[sale.item_id]
        elif sale.product_name and sale.product_name.strip().lower() in item_master_by_name:
            matched_item = item_master_by_name[sale.product_name.strip().lower()]

        canonical_key = matched_item.item_id if matched_item else (sale.item_id or sale.product_name.strip())
        prod_name = matched_item.itemName if matched_item else sale.product_name.strip()
        
        qty = int(sale.quantity_sold or 0)
        u_price = _safe_num(sale.unit_price)
        s_amt = _safe_num(sale.total_sales_amount)
        if s_amt == 0 and qty > 0 and u_price > 0:
            s_amt = qty * u_price

        if canonical_key not in sales_by_item:
            sales_by_item[canonical_key] = {
                'product_name': prod_name,
                'item_id': canonical_key,
                'quantity_sold': 0,
                'total_sales_amount': 0.0,
                'unit_price': u_price,
                'matched_item': matched_item
            }
        
        sales_by_item[canonical_key]['quantity_sold'] += qty
        sales_by_item[canonical_key]['total_sales_amount'] += s_amt
        if u_price > 0:
            sales_by_item[canonical_key]['unit_price'] = u_price

    # 6. Process and Aggregate GRNs by Canonical Product Key
    grn_by_item = {}
    for grn in grn_qs:
        items = grn.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if not isinstance(items, list):
            continue

        for it in items:
            it_id = str(it.get('item_id') or it.get('id') or '').strip()
            it_name = str(it.get('itemName') or it.get('name') or '').strip()
            qty = int(it.get('quantity') or 0)
            free = int(it.get('free') or 0)
            total_qty = qty + free
            cost_amt = _safe_num(
                it.get('purchaseCost') or 
                it.get('total_amount') or 
                it.get('itemValue') or 
                it.get('baseAmount') or 
                (total_qty * _safe_num(it.get('unitPrice')))
            )

            matched_item = None
            if it_id and it_id in item_master_by_id:
                matched_item = item_master_by_id[it_id]
            elif it_name and it_name.lower() in item_master_by_name:
                matched_item = item_master_by_name[it_name.lower()]

            canonical_key = matched_item.item_id if matched_item else (it_id or it_name)
            prod_name = matched_item.itemName if matched_item else it_name

            if not canonical_key:
                continue

            if canonical_key not in grn_by_item:
                grn_by_item[canonical_key] = {
                    'item_id': canonical_key,
                    'product_name': prod_name,
                    'grn_qty': 0,
                    'grn_value': 0.0,
                    'matched_item': matched_item
                }
            grn_by_item[canonical_key]['grn_qty'] += total_qty
            grn_by_item[canonical_key]['grn_value'] += cost_amt

    # 7. Collect unique items in order
    seen_keys = set()
    all_keys = []

    for item in vm_items:
        if item.item_id and item.item_id not in seen_keys:
            seen_keys.add(item.item_id)
            all_keys.append(item.item_id)

    for key in sales_by_item.keys():
        if key not in seen_keys:
            seen_keys.add(key)
            all_keys.append(key)

    for key, g_info in grn_by_item.items():
        if key not in seen_keys:
            if g_info.get('matched_item') and g_info['matched_item'].is_VM:
                seen_keys.add(key)
                all_keys.append(key)

    report_list = []
    total_sales_qty_sum = 0
    total_sales_val_sum = 0.0
    total_grn_qty_sum = 0
    total_grn_val_sum = 0.0
    total_margin_sum = 0.0

    for key in all_keys:
        item_master = item_master_by_id.get(key)
        if not item_master and key in item_master_by_name:
            item_master = item_master_by_name[key]

        s_info = sales_by_item.get(key, {})
        g_info = grn_by_item.get(key, {})

        prod_name = (
            (item_master.itemName if item_master else None) or 
            s_info.get('product_name') or 
            g_info.get('product_name') or 
            key
        )
        item_id_val = (
            (item_master.item_id if item_master else None) or 
            s_info.get('item_id') or 
            g_info.get('item_id') or 
            key
        )

        s_qty = s_info.get('quantity_sold', 0)
        s_val = s_info.get('total_sales_amount', 0.0)
        
        unit_price = s_info.get('unit_price')
        if not unit_price or unit_price <= 0:
            unit_price = _safe_num(item_master.unit_price if item_master else 0.0)

        if s_val == 0.0 and s_qty > 0 and unit_price > 0:
            s_val = s_qty * unit_price

        g_qty = g_info.get('grn_qty', 0)
        g_val = g_info.get('grn_value', 0.0)
        avg_grn_unit_cost = round(g_val / g_qty, 2) if g_qty > 0 else 0.0

        total_qty = int(item_master.total_quantity or 0) if item_master else 0
        approved_qty = int(item_master.approved_quantity or 0) if item_master else 0
        available_stock = max(0, total_qty - approved_qty)

        cost_per_unit = avg_grn_unit_cost if avg_grn_unit_cost > 0 else 0.0
        cogs = s_qty * cost_per_unit
        item_margin = round(s_val - cogs, 2) if s_qty > 0 else 0.0

        total_sales_qty_sum += s_qty
        total_sales_val_sum += s_val
        total_grn_qty_sum += g_qty
        total_grn_val_sum += g_val
        total_margin_sum += item_margin

        cat_raw = item_master.category if item_master else '-'
        cat_display = cat_map.get(cat_raw) or cat_raw or '-'

        dept_raw = item_master.department if item_master else '-'
        dept_display = dept_map.get(dept_raw) or dept_raw or '-'

        supp_raw = item_master.supplier if item_master else '-'
        supp_display = vendor_map.get(str(supp_raw)) or supp_raw or '-'

        report_list.append({
            'item_id': item_id_val,
            'product_name': prod_name,
            'category': cat_display,
            'category_code': cat_raw,
            'department': dept_display,
            'department_code': dept_raw,
            'supplier': supp_display,
            'supplier_code': supp_raw,
            'unit_price': round(unit_price, 2),
            'sales_qty': s_qty,
            'sales_value': round(s_val, 2),
            'grn_received_qty': g_qty,
            'grn_total_value': round(g_val, 2),
            'avg_grn_unit_cost': avg_grn_unit_cost,
            'total_quantity': total_qty,
            'approved_quantity': approved_qty,
            'available_quantity': available_stock,
            'current_master_stock': total_qty,
            'stock_balance': available_stock,
            'estimated_margin': item_margin,
            'is_VM': True if item_master else False
        })

    summary = {
        'total_vm_products': len(report_list),
        'total_sales_quantity': total_sales_qty_sum,
        'total_sales_value': round(total_sales_val_sum, 2),
        'total_grn_quantity': total_grn_qty_sum,
        'total_grn_value': round(total_grn_val_sum, 2),
        'total_master_stock': sum(it.get('total_quantity', 0) for it in report_list),
        'total_approved_quantity': sum(it.get('approved_quantity', 0) for it in report_list),
        'total_available_stock': sum(it.get('available_quantity', 0) for it in report_list),
        'net_margin': round(total_margin_sum, 2)
    }

    return Response({
        "success": True,
        "summary": summary,
        "data": report_list
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_grn_supplier_report(request):
    from_date = request.query_params.get('from_date') or request.GET.get('from_date')
    to_date = request.query_params.get('to_date') or request.GET.get('to_date')
    vendor_id = request.query_params.get('vendor_id') or request.GET.get('vendor_id')
    search_query = request.query_params.get('search') or request.GET.get('search') or ''

    # Get all active vendors
    vendors_qs = GeneralStoreVendor.objects.filter(is_active__in=[True])
    vendor_map = {str(v.vendor_id): v.name for v in vendors_qs}

    # Fetch GRNs
    grn_qs = storesGRN.objects.filter(is_active__in=[True]).order_by('-date')
    if from_date:
        grn_qs = grn_qs.filter(date__gte=from_date)
    if to_date:
        grn_qs = grn_qs.filter(date__lte=to_date)
    if vendor_id:
        grn_qs = grn_qs.filter(vendor_id=vendor_id)

    # Group GRNs by Supplier
    supplier_groups = {}
    total_grns_count = 0
    grand_total_amount = 0.0
    grand_total_paid = 0.0
    grand_pending_amount = 0.0
    grand_tax_amount = 0.0

    for grn in grn_qs:
        v_id = str(grn.vendor_id or 'UNKNOWN')
        v_name = vendor_map.get(v_id) or v_id

        # Search filter match
        if search_query:
            sq = search_query.lower()
            if sq not in v_name.lower() and sq not in v_id.lower() and sq not in str(grn.grn_number).lower() and sq not in str(grn.invoice_no).lower():
                continue

        if v_id not in supplier_groups:
            supplier_groups[v_id] = {
                'vendor_id': v_id,
                'vendor_name': v_name,
                'total_grns': 0,
                'taxable_amount': 0.0,
                'tax_amount': 0.0,
                'total_amount': 0.0,
                'total_paid': 0.0,
                'pending_amount': 0.0,
                'total_items_qty': 0,
                'grns': []
            }

        # Calculate GRN items count & amounts
        items = grn.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if not isinstance(items, list):
            items = []

        def _safe_num(v):
            if v is None or v == '':
                return 0.0
            try:
                return float(str(v))
            except Exception:
                return 0.0

        item_qty = 0
        for it in items:
            if isinstance(it, dict):
                q = _safe_num(it.get('quantity'))
                f = _safe_num(it.get('free'))
                item_qty += int(q + f)
        
        tot_amt = _safe_num(grn.total_amount or grn.net_invoice_amount)
        tot_paid = _safe_num(grn.total_amount_paid)
        pend_amt = max(0.0, tot_amt - tot_paid)
        tax_amt = _safe_num(grn.cgst) + _safe_num(grn.sgst) + _safe_num(grn.igst) + _safe_num(grn.local_tax)
        taxable_amt = _safe_num(grn.taxable_amount) or max(0.0, tot_amt - tax_amt)

        group = supplier_groups[v_id]
        group['total_grns'] += 1
        group['taxable_amount'] += taxable_amt
        group['tax_amount'] += tax_amt
        group['total_amount'] += tot_amt
        group['total_paid'] += tot_paid
        group['pending_amount'] += pend_amt
        group['total_items_qty'] += item_qty

        group['grns'].append({
            'grn_number': grn.grn_number,
            'date': grn.date,
            'invoice_no': grn.invoice_no,
            'invoice_date': grn.invoice_date,
            'total_amount': round(tot_amt, 2),
            'total_paid': round(tot_paid, 2),
            'pending_amount': round(pend_amt, 2),
            'items_count': len(items),
            'items': items,
            'is_approved': grn.is_approved
        })

        total_grns_count += 1
        grand_total_amount += tot_amt
        grand_total_paid += tot_paid
        grand_pending_amount += pend_amt
        grand_tax_amount += tax_amt

    supplier_list = list(supplier_groups.values())
    for s in supplier_list:
        s['taxable_amount'] = round(s['taxable_amount'], 2)
        s['tax_amount'] = round(s['tax_amount'], 2)
        s['total_amount'] = round(s['total_amount'], 2)
        s['total_paid'] = round(s['total_paid'], 2)
        s['pending_amount'] = round(s['pending_amount'], 2)

    summary = {
        'total_suppliers': len(supplier_list),
        'total_grns': total_grns_count,
        'grand_tax_amount': round(grand_tax_amount, 2),
        'grand_total_amount': round(grand_total_amount, 2),
        'grand_total_paid': round(grand_total_paid, 2),
        'grand_pending_amount': round(grand_pending_amount, 2)
    }

    return Response({
        "success": True,
        "summary": summary,
        "data": supplier_list
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_indent_department_report(request):
    from_date = request.query_params.get('from_date') or request.GET.get('from_date')
    to_date = request.query_params.get('to_date') or request.GET.get('to_date')
    department_filter = request.query_params.get('department') or request.GET.get('department')
    search_query = request.query_params.get('search') or request.GET.get('search') or ''

    # Get department names map (from Global.backend_diagnostics_Departments and Department model)
    dept_map = {}
    for doc in department_collection.find({'is_active': True}):
        code = doc.get('department_code') or doc.get('department_id') or str(doc.get('_id'))
        name = doc.get('department_name')
        if code and name:
            dept_map[str(code)] = name
    for d in Department.objects.filter(is_active__in=[True]):
        if d.department_id and d.department_name and str(d.department_id) not in dept_map:
            dept_map[str(d.department_id)] = d.department_name

    # Fetch Indents
    indent_qs = storesIntent.objects.filter(is_active__in=[True]).order_by('-date')
    if from_date:
        indent_qs = indent_qs.filter(date__gte=from_date)
    if to_date:
        indent_qs = indent_qs.filter(date__lte=to_date)
    if department_filter:
        indent_qs = indent_qs.filter(department=department_filter)

    # Group Indents by Department
    dept_groups = {}
    total_indents_count = 0
    total_approved_count = 0
    total_pending_count = 0
    total_requested_qty = 0

    for indent in indent_qs:
        d_id = str(indent.department or 'GENERAL')
        d_name = dept_map.get(d_id) or d_id

        if search_query:
            sq = search_query.lower()
            if sq not in d_name.lower() and sq not in d_id.lower() and sq not in str(indent.intent_id).lower():
                continue

        if d_id not in dept_groups:
            dept_groups[d_id] = {
                'department_id': d_id,
                'department_name': d_name,
                'total_indents': 0,
                'approved_indents': 0,
                'pending_indents': 0,
                'total_items_count': 0,
                'total_requested_qty': 0,
                'intents': []
            }

        items = indent.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if not isinstance(items, list):
            items = []

        indent_item_qty = 0
        for it in items:
            if isinstance(it, dict):
                try:
                    indent_item_qty += int(float(str(it.get('quantity') or it.get('intent_qty') or 0)))
                except Exception:
                    pass
        is_appr = bool(indent.is_approved)

        grp = dept_groups[d_id]
        grp['total_indents'] += 1
        if is_appr:
            grp['approved_indents'] += 1
            total_approved_count += 1
        else:
            grp['pending_indents'] += 1
            total_pending_count += 1

        grp['total_items_count'] += len(items)
        grp['total_requested_qty'] += indent_item_qty

        grp['intents'].append({
            'intent_id': indent.intent_id,
            'date': indent.date,
            'department': indent.department,
            'department_name': d_name,
            'is_approved': is_appr,
            'items_count': len(items),
            'items': items
        })

        total_indents_count += 1
        total_requested_qty += indent_item_qty

    department_list = list(dept_groups.values())

    summary = {
        'total_departments': len(department_list),
        'total_indents': total_indents_count,
        'total_approved': total_approved_count,
        'total_pending': total_pending_count,
        'total_requested_quantity': total_requested_qty
    }

    return Response({
        "success": True,
        "summary": summary,
        "data": department_list
    }, status=status.HTTP_200_OK)


# ==============================================================================
# Helper functions for safe numerical and date conversions with Decimal128 support
# ==============================================================================

def safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(str(val))
    except Exception:
        return default

def safe_int(val, default=0):
    if val is None:
        return default
    try:
        return int(float(str(val)))
    except Exception:
        return default

def safe_date(val, default=None):
    if val is None:
        return default
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(val.strip(), fmt).date()
            except Exception:
                pass
    return default


# ==============================================================================
# 1. Purchase Order Views
# ==============================================================================

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_purchase_order_list_create(request):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    if request.method == 'GET':
        from_date = request.query_params.get('from_date') or request.GET.get('from_date')
        to_date = request.query_params.get('to_date') or request.GET.get('to_date')
        vendor_id = request.query_params.get('vendor_id') or request.GET.get('vendor_id')
        status_filter = request.query_params.get('status') or request.GET.get('status')
        search_query = request.query_params.get('search') or request.GET.get('search') or ''

        qs = StoresPurchaseOrder.objects.filter(is_active__in=[True]).order_by('-po_date', '-created_date')
        if from_date:
            qs = qs.filter(po_date__gte=from_date)
        if to_date:
            qs = qs.filter(po_date__lte=to_date)
        if vendor_id:
            qs = qs.filter(vendor_id=vendor_id)
        if status_filter:
            qs = qs.filter(status=status_filter)

        serializer = StoresPurchaseOrderSerializer(qs, many=True)
        po_list = serializer.data

        if search_query:
            sq = search_query.lower()
            po_list = [
                p for p in po_list 
                if sq in str(p.get('po_number', '')).lower() 
                or sq in str(p.get('vendor_name', '')).lower()
                or sq in str(p.get('vendor_id', '')).lower()
            ]

        total_amount = sum(safe_float(p.get('total_amount')) for p in po_list)

        return Response({
            "success": True,
            "count": len(po_list),
            "total_amount": round(total_amount, 2),
            "data": po_list
        }, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('po_number'):
            data['po_number'] = generate_custom_id(StoresPurchaseOrder, 'po_number', 'PO', 5)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        data['hospital_code'] = hospital_code

        # If vendor_name is missing, look it up
        v_id = data.get('vendor_id')
        if v_id and not data.get('vendor_name'):
            vendor = GeneralStoreVendor.objects.filter(vendor_id=v_id, is_active__in=[True]).first()
            if vendor:
                data['vendor_name'] = vendor.name

        serializer = StoresPurchaseOrderSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def stores_purchase_order_detail(request, pk):
    employee_id = request.data.get('auth-user-id', 'system')
    po = StoresPurchaseOrder.objects.filter(po_number=pk, is_active__in=[True]).first()
    if not po:
        return Response({"error": "Purchase Order not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = StoresPurchaseOrderSerializer(po)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        serializer = StoresPurchaseOrderSerializer(po, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        po.is_active = False
        po.lastmodified_by = employee_id
        po.save()
        return Response({"message": "Purchase order deleted successfully"}, status=status.HTTP_200_OK)


# ==============================================================================
# 2. Purchase Return Views (Return to Vendor & Debit Note)
# ==============================================================================

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_purchase_return_list_create(request):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    if request.method == 'GET':
        from_date = request.query_params.get('from_date') or request.GET.get('from_date')
        to_date = request.query_params.get('to_date') or request.GET.get('to_date')
        vendor_id = request.query_params.get('vendor_id') or request.GET.get('vendor_id')
        search_query = request.query_params.get('search') or request.GET.get('search') or ''

        qs = StoresPurchaseReturn.objects.filter(is_active__in=[True]).order_by('-return_date', '-created_date')
        if from_date:
            qs = qs.filter(return_date__gte=from_date)
        if to_date:
            qs = qs.filter(return_date__lte=to_date)
        if vendor_id:
            qs = qs.filter(vendor_id=vendor_id)

        serializer = StoresPurchaseReturnSerializer(qs, many=True)
        return_list = serializer.data

        if search_query:
            sq = search_query.lower()
            return_list = [
                r for r in return_list
                if sq in str(r.get('return_id', '')).lower()
                or sq in str(r.get('grn_number', '')).lower()
                or sq in str(r.get('vendor_name', '')).lower()
                or sq in str(r.get('debit_note_no', '')).lower()
            ]

        total_return_value = sum(safe_float(r.get('total_return_amount')) for r in return_list)

        return Response({
            "success": True,
            "count": len(return_list),
            "total_return_value": round(total_return_value, 2),
            "data": return_list
        }, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('return_id'):
            data['return_id'] = generate_custom_id(StoresPurchaseReturn, 'return_id', 'RTV', 5)
        if not data.get('debit_note_no'):
            data['debit_note_no'] = generate_custom_id(StoresPurchaseReturn, 'debit_note_no', 'DBN', 5)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        data['hospital_code'] = hospital_code

        # If vendor_name is missing, look it up
        v_id = data.get('vendor_id')
        if v_id and not data.get('vendor_name'):
            vendor = GeneralStoreVendor.objects.filter(vendor_id=v_id, is_active__in=[True]).first()
            if vendor:
                data['vendor_name'] = vendor.name

        serializer = StoresPurchaseReturnSerializer(data=data)
        if serializer.is_valid():
            return_obj = serializer.save()

            # Automatic stock deduction from ItemMaster for returned items
            items = data.get('items', [])
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []

            for it in items:
                it_id = it.get('item_id') or it.get('id')
                ret_qty = safe_int(it.get('return_qty') or it.get('quantity'))

                if it_id and ret_qty > 0:
                    item_master = ItemMaster.objects.filter(item_id=it_id, is_active__in=[True]).first()
                    if item_master:
                        curr_qty = safe_int(item_master.total_quantity)
                        item_master.total_quantity = max(0, curr_qty - ret_qty)
                        item_master.lastmodified_by = employee_id
                        item_master.save()

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def stores_purchase_return_detail(request, pk):
    employee_id = request.data.get('auth-user-id', 'system')
    ret = StoresPurchaseReturn.objects.filter(return_id=pk, is_active__in=[True]).first()
    if not ret:
        return Response({"error": "Purchase Return not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = StoresPurchaseReturnSerializer(ret)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        serializer = StoresPurchaseReturnSerializer(ret, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        ret.is_active = False
        ret.lastmodified_by = employee_id
        ret.save()
        return Response({"message": "Purchase return deleted successfully"}, status=status.HTTP_200_OK)


# ==============================================================================
# 3. Purchase Analysis Report
# ==============================================================================

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_purchase_analysis_report(request):
    from_date = request.query_params.get('from_date') or request.GET.get('from_date')
    to_date = request.query_params.get('to_date') or request.GET.get('to_date')
    vendor_filter = request.query_params.get('vendor_id') or request.GET.get('vendor_id')

    vendor_map = {v.vendor_id: v.name for v in GeneralStoreVendor.objects.filter(is_active__in=[True]) if v.vendor_id}

    grn_qs = storesGRN.objects.filter(is_active__in=[True]).order_by('-date')
    if from_date:
        grn_qs = grn_qs.filter(date__gte=from_date)
    if to_date:
        grn_qs = grn_qs.filter(date__lte=to_date)
    if vendor_filter:
        grn_qs = grn_qs.filter(vendor_id=vendor_filter)

    monthly_spend = {}
    vendor_spend = {}
    item_analysis = {}
    total_spend = 0.0
    total_tax = 0.0
    total_discount = 0.0
    total_grns = 0

    for grn in grn_qs:
        tot_amt = safe_float(grn.total_amount or grn.net_invoice_amount)
        tax = safe_float(grn.cgst) + safe_float(grn.sgst) + safe_float(grn.igst) + safe_float(grn.local_tax)
        disc = safe_float(grn.total_discount)
        v_id = str(grn.vendor_id or 'UNKNOWN')
        v_name = vendor_map.get(v_id) or v_id

        total_spend += tot_amt
        total_tax += tax
        total_discount += disc
        total_grns += 1

        # Month grouping (YYYY-MM)
        m_key = grn.date.strftime('%Y-%m') if grn.date else 'Unknown'
        if m_key not in monthly_spend:
            monthly_spend[m_key] = {'month': m_key, 'total_amount': 0.0, 'tax_amount': 0.0, 'grn_count': 0}
        monthly_spend[m_key]['total_amount'] += tot_amt
        monthly_spend[m_key]['tax_amount'] += tax
        monthly_spend[m_key]['grn_count'] += 1

        # Vendor grouping
        if v_id not in vendor_spend:
            vendor_spend[v_id] = {'vendor_id': v_id, 'vendor_name': v_name, 'total_amount': 0.0, 'grn_count': 0}
        vendor_spend[v_id]['total_amount'] += tot_amt
        vendor_spend[v_id]['grn_count'] += 1

        # Item-wise spend & rate tracking
        items = grn.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                i_id = str(it.get('item_id') or it.get('id') or it.get('itemName') or 'UNKNOWN')
                i_name = it.get('itemName') or it.get('name') or i_id
                rate = safe_float(it.get('rate') or it.get('purchase_price') or it.get('unit_price') or it.get('price'))
                qty = safe_float(it.get('quantity'))
                net = safe_float(it.get('net_amount')) or (rate * qty)

                if i_id not in item_analysis:
                    item_analysis[i_id] = {
                        'item_id': i_id,
                        'item_name': i_name,
                        'total_quantity': 0.0,
                        'total_spend': 0.0,
                        'rates': [],
                        'min_rate': rate,
                        'max_rate': rate
                    }
                item_analysis[i_id]['total_quantity'] += qty
                item_analysis[i_id]['total_spend'] += net
                if rate > 0:
                    item_analysis[i_id]['rates'].append(rate)
                    item_analysis[i_id]['min_rate'] = min(item_analysis[i_id]['min_rate'], rate)
                    item_analysis[i_id]['max_rate'] = max(item_analysis[i_id]['max_rate'], rate)

    # Format monthly trends
    monthly_trends = sorted(list(monthly_spend.values()), key=lambda x: x['month'])
    for m in monthly_trends:
        m['total_amount'] = round(m['total_amount'], 2)
        m['tax_amount'] = round(m['tax_amount'], 2)

    # Format vendor breakdown (sorted desc)
    vendor_breakdown = sorted(list(vendor_spend.values()), key=lambda x: x['total_amount'], reverse=True)
    for v in vendor_breakdown:
        v['total_amount'] = round(v['total_amount'], 2)
        v['share_percentage'] = round((v['total_amount'] / total_spend * 100) if total_spend > 0 else 0, 2)

    # Format top items (sorted desc by spend)
    top_items = sorted(list(item_analysis.values()), key=lambda x: x['total_spend'], reverse=True)
    for it in top_items:
        it['total_spend'] = round(it['total_spend'], 2)
        it['avg_rate'] = round(sum(it['rates'])/len(it['rates']), 2) if it['rates'] else 0.0
        it.pop('rates', None)

    return Response({
        "success": True,
        "summary": {
            "total_spend": round(total_spend, 2),
            "total_tax": round(total_tax, 2),
            "total_discount": round(total_discount, 2),
            "total_grns": total_grns,
            "average_grn_value": round(total_spend / total_grns, 2) if total_grns > 0 else 0.0
        },
        "monthly_trends": monthly_trends,
        "vendor_breakdown": vendor_breakdown,
        "top_items": top_items[:50]
    }, status=status.HTTP_200_OK)


# ==============================================================================
# 4. Previous Day / Daily Stock Movement Report
# ==============================================================================

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_previous_day_stock_report(request):
    report_date_str = request.query_params.get('date') or request.GET.get('date')
    search_query = request.query_params.get('search') or request.GET.get('search') or ''
    department_filter = request.query_params.get('department') or request.GET.get('department')
    group_filter = request.query_params.get('group') or request.GET.get('group')

    today = datetime.now().date()
    if report_date_str:
        try:
            target_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
        except Exception:
            target_date = today - timedelta(days=1)
    else:
        target_date = today - timedelta(days=1)

    target_date_str = target_date.strftime("%Y-%m-%d")

    # Fetch all items
    items_qs = ItemMaster.objects.filter(is_active__in=[True]).order_by('itemName')
    if department_filter:
        items_qs = items_qs.filter(department=department_filter)
    if group_filter:
        items_qs = items_qs.filter(group=group_filter)

    # Inward for target date from GRN
    inward_map = {}
    grns_on_date = storesGRN.objects.filter(is_active__in=[True], date=target_date)
    for grn in grns_on_date:
        items = grn.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                i_id = str(it.get('item_id') or it.get('id') or '')
                qty = safe_float(it.get('quantity')) + safe_float(it.get('free'))
                inward_map[i_id] = inward_map.get(i_id, 0.0) + qty

    # Outward for target date from approved Indents
    outward_map = {}
    intents_on_date = storesIntent.objects.filter(is_active__in=[True], date=target_date, is_approved__in=[True])
    for ind in intents_on_date:
        items = ind.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                i_id = str(it.get('item_id') or '')
                qty = safe_float(it.get('approved_quantity') or it.get('quantity'))
                outward_map[i_id] = outward_map.get(i_id, 0.0) + qty

    # Purchase returns on target date
    returns_map = {}
    returns_on_date = StoresPurchaseReturn.objects.filter(is_active__in=[True], return_date=target_date)
    for ret in returns_on_date:
        items = ret.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                i_id = str(it.get('item_id') or it.get('id') or '')
                qty = safe_float(it.get('return_qty') or it.get('quantity'))
                returns_map[i_id] = returns_map.get(i_id, 0.0) + qty

    stock_records = []
    total_opening_qty = 0.0
    total_inward_qty = 0.0
    total_outward_qty = 0.0
    total_returns_qty = 0.0
    total_closing_qty = 0.0
    total_closing_value = 0.0

    for itm in items_qs:
        i_id = str(itm.item_id)
        i_name = itm.itemName

        if search_query:
            sq = search_query.lower()
            if sq not in i_name.lower() and sq not in i_id.lower():
                continue

        current_stock = safe_float(itm.total_quantity)
        inward = inward_map.get(i_id, 0.0)
        outward = outward_map.get(i_id, 0.0)
        returned = returns_map.get(i_id, 0.0)
        
        # If target_date is today or previous day, calculate Opening = Closing - Inward + Outward + Returned
        closing = current_stock
        opening = max(0.0, closing - inward + outward + returned)
        unit_price = safe_float(itm.unit_price)
        valuation = closing * unit_price

        total_opening_qty += opening
        total_inward_qty += inward
        total_outward_qty += outward
        total_returns_qty += returned
        total_closing_qty += closing
        total_closing_value += valuation

        stock_records.append({
            'item_id': i_id,
            'item_name': i_name,
            'department': itm.department or 'Stores',
            'group': itm.group or '',
            'category': itm.category or '',
            'rack_no': itm.rack_no or '',
            'shelf_no': itm.shelf_no or '',
            'opening_stock': round(opening, 2),
            'inward_qty': round(inward, 2),
            'outward_qty': round(outward, 2),
            'return_qty': round(returned, 2),
            'closing_stock': round(closing, 2),
            'unit_price': round(unit_price, 2),
            'stock_valuation': round(valuation, 2)
        })

    return Response({
        "success": True,
        "date": target_date_str,
        "summary": {
            "total_items": len(stock_records),
            "total_opening_qty": round(total_opening_qty, 2),
            "total_inward_qty": round(total_inward_qty, 2),
            "total_outward_qty": round(total_outward_qty, 2),
            "total_returns_qty": round(total_returns_qty, 2),
            "total_closing_qty": round(total_closing_qty, 2),
            "total_closing_value": round(total_closing_value, 2)
        },
        "data": stock_records
    }, status=status.HTTP_200_OK)


# ==============================================================================
# 5. Supplier Wise List & Purchase Report
# ==============================================================================

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_supplier_wise_list_report(request):
    search_query = request.query_params.get('search') or request.GET.get('search') or ''
    city_filter = request.query_params.get('city') or request.GET.get('city')
    state_filter = request.query_params.get('state') or request.GET.get('state')

    vendors = GeneralStoreVendor.objects.filter(is_active__in=[True]).order_by('name')
    if city_filter:
        vendors = vendors.filter(city__iexact=city_filter)
    if state_filter:
        vendors = vendors.filter(state__iexact=state_filter)

    # Pre-aggregate GRN data per vendor
    grn_stats = {}
    for grn in storesGRN.objects.filter(is_active__in=[True]):
        v_id = str(grn.vendor_id or '')
        if not v_id:
            continue
        tot = safe_float(grn.total_amount or grn.net_invoice_amount)
        paid = safe_float(grn.total_amount_paid)
        pend = max(0.0, tot - paid)

        if v_id not in grn_stats:
            grn_stats[v_id] = {
                'total_grns': 0,
                'total_purchase_amount': 0.0,
                'total_paid': 0.0,
                'total_pending': 0.0,
                'last_purchase_date': None,
                'items_supplied': set()
            }
        grn_stats[v_id]['total_grns'] += 1
        grn_stats[v_id]['total_purchase_amount'] += tot
        grn_stats[v_id]['total_paid'] += paid
        grn_stats[v_id]['total_pending'] += pend
        if grn.date:
            if not grn_stats[v_id]['last_purchase_date'] or grn.date > grn_stats[v_id]['last_purchase_date']:
                grn_stats[v_id]['last_purchase_date'] = grn.date

        items = grn.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                name = it.get('itemName') or it.get('name')
                if name:
                    grn_stats[v_id]['items_supplied'].add(name)

    supplier_list = []
    grand_total_purchases = 0.0
    grand_total_paid = 0.0
    grand_total_pending = 0.0

    for v in vendors:
        v_id = str(v.vendor_id)
        name = v.name

        if search_query:
            sq = search_query.lower()
            if (sq not in name.lower() and sq not in v_id.lower() 
                and sq not in str(v.phone or '').lower() 
                and sq not in str(v.email or '').lower()
                and sq not in str(v.gstin or '').lower()):
                continue

        stats = grn_stats.get(v_id, {
            'total_grns': 0,
            'total_purchase_amount': 0.0,
            'total_paid': 0.0,
            'total_pending': 0.0,
            'last_purchase_date': None,
            'items_supplied': set()
        })

        tot_p = stats['total_purchase_amount']
        tot_pd = stats['total_paid']
        tot_pnd = stats['total_pending']

        grand_total_purchases += tot_p
        grand_total_paid += tot_pd
        grand_total_pending += tot_pnd

        supplier_list.append({
            'vendor_id': v_id,
            'vendor_name': name,
            'vendor_type': v.vendor_type,
            'contact_person': v.contact_person or '',
            'phone': v.phone or '',
            'email': v.email or '',
            'city': v.city or '',
            'state': v.state or '',
            'gstin': v.gstin or '',
            'payment_terms': v.payment_terms or '',
            'total_grns': stats['total_grns'],
            'total_purchase_amount': round(tot_p, 2),
            'total_paid': round(tot_pd, 2),
            'pending_amount': round(tot_pnd, 2),
            'last_purchase_date': stats['last_purchase_date'].strftime('%Y-%m-%d') if stats['last_purchase_date'] else None,
            'items_supplied_count': len(stats['items_supplied']),
            'items_sample': list(stats['items_supplied'])[:5]
        })

    return Response({
        "success": True,
        "summary": {
            "total_suppliers": len(supplier_list),
            "grand_total_purchases": round(grand_total_purchases, 2),
            "grand_total_paid": round(grand_total_paid, 2),
            "grand_total_pending": round(grand_total_pending, 2)
        },
        "data": supplier_list
    }, status=status.HTTP_200_OK)


# ==============================================================================
# 6. Non-Moving Items Report (Dead Stock / Slow Moving)
# ==============================================================================

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_non_moving_items_report(request):
    days_threshold = safe_int(request.query_params.get('days') or request.GET.get('days'), 30)
    search_query = request.query_params.get('search') or request.GET.get('search') or ''
    department_filter = request.query_params.get('department') or request.GET.get('department')
    group_filter = request.query_params.get('group') or request.GET.get('group')

    today = datetime.now().date()
    cutoff_date = today - timedelta(days=days_threshold)

    # Collect all items with recent outward movement (indents within cutoff_date)
    recent_moved_item_ids = set()
    recent_intents = storesIntent.objects.filter(is_active__in=[True], date__gte=cutoff_date, is_approved__in=[True])
    for ind in recent_intents:
        items = ind.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                i_id = str(it.get('item_id') or '')
                if i_id:
                    recent_moved_item_ids.add(i_id)

    # Find last outward date for all items
    last_outward_map = {}
    for ind in storesIntent.objects.filter(is_active__in=[True], is_approved__in=[True]).order_by('-date'):
        items = ind.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                i_id = str(it.get('item_id') or '')
                if i_id and i_id not in last_outward_map and ind.date:
                    last_outward_map[i_id] = ind.date

    # Find last inward date for all items
    last_inward_map = {}
    for grn in storesGRN.objects.filter(is_active__in=[True]).order_by('-date'):
        items = grn.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                i_id = str(it.get('item_id') or it.get('id') or '')
                if i_id and i_id not in last_inward_map and grn.date:
                    last_inward_map[i_id] = grn.date

    items_qs = ItemMaster.objects.filter(is_active__in=[True], total_quantity__gt=0).order_by('-total_quantity')
    if department_filter:
        items_qs = items_qs.filter(department=department_filter)
    if group_filter:
        items_qs = items_qs.filter(group=group_filter)

    non_moving_items = []
    total_idle_qty = 0.0
    total_idle_value = 0.0

    for itm in items_qs:
        i_id = str(itm.item_id)
        if i_id in recent_moved_item_ids:
            continue

        i_name = itm.itemName
        if search_query:
            sq = search_query.lower()
            if sq not in i_name.lower() and sq not in i_id.lower():
                continue

        qty = safe_float(itm.total_quantity)
        unit_price = safe_float(itm.unit_price)
        idle_value = qty * unit_price

        last_out_d = safe_date(last_outward_map.get(i_id))
        last_in_d = safe_date(last_inward_map.get(i_id))
        created_d = safe_date(itm.created_date)

        # Days without movement
        ref_date = last_out_d or last_in_d or created_d or today
        days_idle = max(0, (today - ref_date).days) if ref_date else days_threshold

        total_idle_qty += qty
        total_idle_value += idle_value

        non_moving_items.append({
            'item_id': i_id,
            'item_name': i_name,
            'department': itm.department or 'Stores',
            'group': itm.group or '',
            'category': itm.category or '',
            'rack_no': itm.rack_no or '',
            'shelf_no': itm.shelf_no or '',
            'stock_on_hand': qty,
            'unit_price': round(unit_price, 2),
            'idle_valuation': round(idle_value, 2),
            'last_inward_date': last_in_d.strftime('%Y-%m-%d') if last_in_d else None,
            'last_outward_date': last_out_d.strftime('%Y-%m-%d') if last_out_d else None,
            'days_idle': max(days_threshold, days_idle)
        })

    non_moving_items.sort(key=lambda x: x['days_idle'], reverse=True)

    return Response({
        "success": True,
        "days_threshold": days_threshold,
        "summary": {
            "total_non_moving_items": len(non_moving_items),
            "total_idle_quantity": round(total_idle_qty, 2),
            "total_idle_value": round(total_idle_value, 2)
        },
        "data": non_moving_items
    }, status=status.HTTP_200_OK)


# ==============================================================================
# 7. Short Expiry List Report
# ==============================================================================

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_short_expiry_report(request):
    days_threshold = safe_int(request.query_params.get('days') or request.GET.get('days'), 90)
    search_query = request.query_params.get('search') or request.GET.get('search') or ''
    vendor_filter = request.query_params.get('vendor_id') or request.GET.get('vendor_id')

    today = datetime.now().date()
    expiry_limit = today + timedelta(days=days_threshold)

    vendor_map = {v.vendor_id: v.name for v in GeneralStoreVendor.objects.filter(is_active__in=[True]) if v.vendor_id}

    expiry_items = []
    total_short_expiry_qty = 0.0
    total_short_expiry_value = 0.0
    critical_count = 0
    expired_count = 0

    grn_qs = storesGRN.objects.filter(is_active__in=[True]).order_by('-date')
    if vendor_filter:
        grn_qs = grn_qs.filter(vendor_id=vendor_filter)

    for grn in grn_qs:
        v_id = str(grn.vendor_id or '')
        v_name = vendor_map.get(v_id) or v_id
        items = grn.items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            for it in items:
                exp_str = it.get('expiry_date') or it.get('exp_date') or it.get('expiry')
                if not exp_str:
                    continue

                try:
                    exp_date = None
                    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%Y", "%Y/%m/%d"):
                        try:
                            exp_date = datetime.strptime(str(exp_str).strip(), fmt).date()
                            break
                        except Exception:
                            pass
                    if not exp_date:
                        continue
                except Exception:
                    continue

                if exp_date <= expiry_limit:
                    i_id = str(it.get('item_id') or it.get('id') or '')
                    i_name = it.get('itemName') or it.get('name') or i_id
                    qty = safe_float(it.get('quantity'))
                    rate = safe_float(it.get('rate') or it.get('purchase_price') or it.get('unit_price'))
                    val = qty * rate
                    days_remaining = (exp_date - today).days

                    status_label = 'EXPIRED' if days_remaining < 0 else ('CRITICAL' if days_remaining <= 30 else 'ALERT')
                    if days_remaining < 0:
                        expired_count += 1
                    elif days_remaining <= 30:
                        critical_count += 1

                    if search_query:
                        sq = search_query.lower()
                        if sq not in i_name.lower() and sq not in i_id.lower() and sq not in str(it.get('batch_no', '')).lower():
                            continue

                    total_short_expiry_qty += qty
                    total_short_expiry_value += val

                    expiry_items.append({
                        'grn_number': grn.grn_number,
                        'grn_date': grn.date.strftime('%Y-%m-%d') if grn.date else None,
                        'vendor_id': v_id,
                        'vendor_name': v_name,
                        'item_id': i_id,
                        'item_name': i_name,
                        'batch_no': it.get('batch_no') or it.get('batch') or 'N/A',
                        'expiry_date': exp_date.strftime('%Y-%m-%d'),
                        'days_remaining': days_remaining,
                        'status': status_label,
                        'quantity': qty,
                        'rate': round(rate, 2),
                        'total_value': round(val, 2),
                        'rack_no': it.get('rack_no') or '',
                        'shelf_no': it.get('shelf_no') or ''
                    })

    expiry_items.sort(key=lambda x: x['days_remaining'])

    return Response({
        "success": True,
        "days_threshold": days_threshold,
        "summary": {
            "total_items": len(expiry_items),
            "expired_count": expired_count,
            "critical_count": critical_count,
            "total_quantity": round(total_short_expiry_qty, 2),
            "total_value": round(total_short_expiry_value, 2)
        },
        "data": expiry_items
    }, status=status.HTTP_200_OK)


# ==============================================================================
# 8. Reorder Level Indication Report
# ==============================================================================

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def stores_reorder_level_report(request):
    status_filter = request.query_params.get('status') or request.GET.get('status') # OUT_OF_STOCK, LOW_STOCK, ADEQUATE
    search_query = request.query_params.get('search') or request.GET.get('search') or ''
    department_filter = request.query_params.get('department') or request.GET.get('department')
    group_filter = request.query_params.get('group') or request.GET.get('group')

    items_qs = ItemMaster.objects.filter(is_active__in=[True]).order_by('itemName')
    if department_filter:
        items_qs = items_qs.filter(department=department_filter)
    if group_filter:
        items_qs = items_qs.filter(group=group_filter)

    report_items = []
    out_of_stock_count = 0
    low_stock_count = 0
    adequate_count = 0
    total_reorder_est_cost = 0.0

    for itm in items_qs:
        i_id = str(itm.item_id)
        i_name = itm.itemName

        if search_query:
            sq = search_query.lower()
            if sq not in i_name.lower() and sq not in i_id.lower():
                continue

        current_stock = safe_float(itm.total_quantity)
        reorder_level = safe_float(itm.stockReorderLevel)

        if current_stock <= 0:
            stock_status = 'OUT_OF_STOCK'
            out_of_stock_count += 1
        elif reorder_level > 0 and current_stock <= reorder_level:
            stock_status = 'LOW_STOCK'
            low_stock_count += 1
        else:
            stock_status = 'ADEQUATE'
            adequate_count += 1

        if status_filter and stock_status != status_filter:
            continue

        unit_price = safe_float(itm.unit_price)
        suggested_reorder_qty = max(0.0, (reorder_level * 2) - current_stock) if reorder_level > 0 else (10.0 if current_stock <= 0 else 0.0)
        est_cost = suggested_reorder_qty * unit_price
        total_reorder_est_cost += est_cost

        report_items.append({
            'item_id': i_id,
            'item_name': i_name,
            'department': itm.department or 'Stores',
            'group': itm.group or '',
            'category': itm.category or '',
            'ved_category': itm.ved_category or 'D',
            'abc_category': itm.abc_category or 'C',
            'rack_no': itm.rack_no or '',
            'shelf_no': itm.shelf_no or '',
            'current_stock': current_stock,
            'reorder_level': reorder_level,
            'stock_status': stock_status,
            'unit_price': round(unit_price, 2),
            'suggested_reorder_qty': round(suggested_reorder_qty, 2),
            'estimated_reorder_cost': round(est_cost, 2)
        })

    # Sort so OUT_OF_STOCK and LOW_STOCK appear first
    order_map = {'OUT_OF_STOCK': 0, 'LOW_STOCK': 1, 'ADEQUATE': 2}
    report_items.sort(key=lambda x: (order_map.get(x['stock_status'], 3), -x['suggested_reorder_qty']))

    return Response({
        "success": True,
        "summary": {
            "total_items_tracked": len(report_items),
            "out_of_stock_count": out_of_stock_count,
            "low_stock_count": low_stock_count,
            "adequate_count": adequate_count,
            "total_estimated_reorder_cost": round(total_reorder_est_cost, 2)
        },
        "data": report_items
    }, status=status.HTTP_200_OK)


# ==============================================================================
# 9. Barcode Entry & Rack Classification Views
# ==============================================================================

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_item_rack_update(request):
    employee_id = request.data.get('auth-user-id', 'system')

    if request.method == 'GET':
        rack = request.query_params.get('rack_no') or request.GET.get('rack_no')
        shelf = request.query_params.get('shelf_no') or request.GET.get('shelf_no')
        barcode = request.query_params.get('barcode') or request.GET.get('barcode')
        search_query = request.query_params.get('search') or request.GET.get('search') or ''

        qs = ItemMaster.objects.filter(is_active__in=[True]).order_by('rack_no', 'shelf_no', 'itemName')
        if rack:
            qs = qs.filter(rack_no__iexact=rack)
        if shelf:
            qs = qs.filter(shelf_no__iexact=shelf)
        if barcode:
            qs = qs.filter(barcode=barcode)

        serializer = ItemMasterSerializer(qs, many=True)
        items_list = serializer.data

        if search_query:
            sq = search_query.lower()
            items_list = [
                i for i in items_list
                if sq in str(i.get('itemName', '')).lower()
                or sq in str(i.get('item_id', '')).lower()
                or sq in str(i.get('barcode', '')).lower()
                or sq in str(i.get('rack_no', '')).lower()
            ]

        # Distinct racks & shelves list for dropdowns (from Rack & Shelf masters + ItemMaster)
        master_racks = list(Rack.objects.filter(is_active__in=[True]).values_list('rack_name', flat=True))
        item_racks = list(ItemMaster.objects.filter(is_active__in=[True]).values_list('rack_no', flat=True).distinct())
        all_racks = sorted(list(set([r for r in (master_racks + item_racks) if r])))

        master_shelves = list(Shelf.objects.filter(is_active__in=[True]).values_list('shelf_name', flat=True))
        item_shelves = list(ItemMaster.objects.filter(is_active__in=[True]).values_list('shelf_no', flat=True).distinct())
        all_shelves = sorted(list(set([s for s in (master_shelves + item_shelves) if s])))

        rack_objects = list(Rack.objects.filter(is_active__in=[True]).values('rack_id', 'rack_name', 'description'))
        shelf_objects = list(Shelf.objects.filter(is_active__in=[True]).values('shelf_id', 'shelf_name', 'rack_id', 'description'))

        return Response({
            "success": True,
            "racks": all_racks,
            "shelves": all_shelves,
            "rack_masters": rack_objects,
            "shelf_masters": shelf_objects,
            "data": items_list
        }, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        # Support bulk update via "items" list or single item update
        items_payload = request.data.get('items')
        if items_payload and isinstance(items_payload, list):
            updated_count = 0
            for entry in items_payload:
                it_id = entry.get('item_id')
                if not it_id:
                    continue
                itm = ItemMaster.objects.filter(item_id=it_id, is_active__in=[True]).first()
                if itm:
                    if 'rack_no' in entry:
                        itm.rack_no = entry.get('rack_no')
                    if 'shelf_no' in entry:
                        itm.shelf_no = entry.get('shelf_no')
                    if 'bin_no' in entry:
                        itm.bin_no = entry.get('bin_no')
                    if 'barcode' in entry:
                        itm.barcode = entry.get('barcode')
                    itm.lastmodified_by = employee_id
                    itm.save()
                    updated_count += 1

            return Response({
                "success": True,
                "message": f"Successfully updated {updated_count} items with rack and barcode details"
            }, status=status.HTTP_200_OK)

        item_id = request.data.get('item_id')
        if not item_id:
            return Response({"error": "item_id or items list is required"}, status=status.HTTP_400_BAD_REQUEST)

        item = ItemMaster.objects.filter(item_id=item_id, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Item not found"}, status=status.HTTP_404_NOT_FOUND)

        if 'rack_no' in request.data:
            item.rack_no = request.data.get('rack_no')
        if 'shelf_no' in request.data:
            item.shelf_no = request.data.get('shelf_no')
        if 'bin_no' in request.data:
            item.bin_no = request.data.get('bin_no')
        if 'barcode' in request.data:
            item.barcode = request.data.get('barcode')

        item.lastmodified_by = employee_id
        item.save()

        serializer = ItemMasterSerializer(item)
        return Response({
            "success": True,
            "message": "Item rack & barcode details updated successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)


# ==============================================================================
# 10. Stores Indent Return Views (Department Indent Returns & Approval)
# ==============================================================================

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_indent_return_list_create(request):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    if request.method == 'GET':
        from_date = request.query_params.get('from_date') or request.GET.get('from_date')
        to_date = request.query_params.get('to_date') or request.GET.get('to_date')
        department = request.query_params.get('department') or request.GET.get('department')
        status_filter = request.query_params.get('status') or request.GET.get('status')
        intent_id = request.query_params.get('intent_id') or request.GET.get('intent_id')
        search_query = request.query_params.get('search') or request.GET.get('search') or ''

        qs = StoresIndentReturn.objects.filter(is_active__in=[True]).order_by('-return_date', '-created_date')
        if from_date:
            qs = qs.filter(return_date__gte=from_date)
        if to_date:
            qs = qs.filter(return_date__lte=to_date)
        if department:
            qs = qs.filter(department=department)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if intent_id:
            qs = qs.filter(intent_id=intent_id)

        serializer = StoresIndentReturnSerializer(qs, many=True)
        return_list = serializer.data

        if search_query:
            sq = search_query.lower()
            return_list = [
                r for r in return_list
                if sq in str(r.get('return_id', '')).lower()
                or sq in str(r.get('intent_id', '')).lower()
                or sq in str(r.get('department_name', '')).lower()
                or sq in str(r.get('remarks', '')).lower()
            ]

        return Response({
            "success": True,
            "count": len(return_list),
            "data": return_list
        }, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('return_id'):
            data['return_id'] = generate_custom_id(StoresIndentReturn, 'return_id', 'INRET', 5)

        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        data['hospital_code'] = hospital_code

        # Department name lookup if not provided
        dept_code = data.get('department')
        if dept_code and not data.get('department_name'):
            dept = Department.objects.filter(department_id=dept_code, is_active__in=[True]).first()
            if dept:
                data['department_name'] = dept.department_name

        items = data.get('items', [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []

        total_qty = sum(safe_int(it.get('return_quantity') or it.get('quantity') or 0) for it in items)
        total_val = sum(safe_float(it.get('return_quantity') or it.get('quantity') or 0) * safe_float(it.get('unit_price') or 0) for it in items)

        data['total_returned_qty'] = total_qty
        data['total_returned_value'] = total_val
        data['status'] = 'Pending'

        serializer = StoresIndentReturnSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Indent return submitted successfully and sent for approval",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_indent_return_approve(request, pk):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    ret_obj = StoresIndentReturn.objects.filter(return_id=pk, is_active__in=[True]).first()
    if not ret_obj:
        return Response({"error": "Indent return record not found"}, status=status.HTTP_404_NOT_FOUND)

    if ret_obj.status == 'Approved':
        return Response({"error": "This return is already approved"}, status=status.HTTP_400_BAD_REQUEST)

    items = ret_obj.items or []
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            items = []

    # Optional custom approval item adjustments passed in request
    req_items = request.data.get('items')
    if req_items and isinstance(req_items, list):
        items = req_items
        ret_obj.items = req_items

    for it in items:
        item_id = it.get('item_id')
        ret_qty = safe_int(it.get('return_quantity') or it.get('quantity') or 0)

        if item_id and ret_qty > 0:
            # 1. Deduct approved_quantity from ItemMaster (which increases available stock in Central Stores)
            try:
                item_master = ItemMaster.objects.filter(item_id=item_id).first()
                if item_master:
                    item_master.approved_quantity = max(0, (item_master.approved_quantity or 0) - ret_qty)
                    item_master.lastmodified_by = employee_id
                    item_master.save()
            except Exception as e:
                print(f"Error updating ItemMaster on return: {e}")

            # 2. If Department is DEPT002 (Lab), deduct from Stores_LabApprovedItem
            if ret_obj.department == 'DEPT002':
                lab_item = Stores_LabApprovedItem.objects.filter(
                    item_id=item_id,
                    branch_code=branch_code,
                    hospital_code=hospital_code
                ).first()
                if lab_item:
                    lab_item.quantity = max(0, (lab_item.quantity or 0) - ret_qty)
                    lab_item.lastmodified_by = employee_id
                    lab_item.save()

            # 3. Update original storesIntent record returned_quantity
            if ret_obj.intent_id:
                intent_obj = storesIntent.objects.filter(intent_id=ret_obj.intent_id, is_active__in=[True]).first()
                if intent_obj and intent_obj.items:
                    updated_items = []
                    for ind_it in intent_obj.items:
                        if str(ind_it.get('item_id')) == str(item_id):
                            curr_ret = int(ind_it.get('returned_quantity') or 0)
                            ind_it['returned_quantity'] = curr_ret + ret_qty
                        updated_items.append(ind_it)
                    intent_obj.items = updated_items
                    intent_obj.lastmodified_by = employee_id
                    intent_obj.save()

    ret_obj.status = 'Approved'
    ret_obj.approved_by = employee_id
    ret_obj.approved_date = timezone.now()
    ret_obj.lastmodified_by = employee_id
    ret_obj.save()

    serializer = StoresIndentReturnSerializer(ret_obj)
    return Response({
        "success": True,
        "message": "Indent return approved successfully. Stock restored to central inventory.",
        "data": serializer.data
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_indent_return_reject(request, pk):
    employee_id = request.data.get('auth-user-id', 'system')
    ret_obj = StoresIndentReturn.objects.filter(return_id=pk, is_active__in=[True]).first()
    if not ret_obj:
        return Response({"error": "Indent return record not found"}, status=status.HTTP_404_NOT_FOUND)

    if ret_obj.status == 'Approved':
        return Response({"error": "Approved returns cannot be rejected"}, status=status.HTTP_400_BAD_REQUEST)

    rejection_reason = request.data.get('rejection_reason', 'Rejected by Stores Manager')
    ret_obj.status = 'Rejected'
    ret_obj.rejection_reason = rejection_reason
    ret_obj.approved_by = employee_id
    ret_obj.approved_date = timezone.now()
    ret_obj.lastmodified_by = employee_id
    ret_obj.save()

    serializer = StoresIndentReturnSerializer(ret_obj)
    return Response({
        "success": True,
        "message": "Indent return marked as Rejected.",
        "data": serializer.data
    }, status=status.HTTP_200_OK)


@api_view(['DELETE'])
@permission_classes([HasRoleAndDataPermission])
def stores_indent_return_delete(request, pk):
    employee_id = request.data.get('auth-user-id', 'system')
    ret_obj = StoresIndentReturn.objects.filter(return_id=pk, is_active__in=[True]).first()
    if not ret_obj:
        return Response({"error": "Indent return record not found"}, status=status.HTTP_404_NOT_FOUND)

    if ret_obj.status == 'Approved':
        return Response({"error": "Approved returns cannot be deleted"}, status=status.HTTP_400_BAD_REQUEST)

    ret_obj.is_active = False
    ret_obj.lastmodified_by = employee_id
    ret_obj.save()
    return Response({"success": True, "message": "Indent return deleted successfully"}, status=status.HTTP_200_OK)



