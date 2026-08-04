import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import ItemMaster, Department, Group, Category, GroupType, storesGRN, storesIntent
from ...models import LabApprovedItem
from ...serializers import LabApprovedItemSerializer
from .serializer import (
    ItemMasterSerializer, DepartmentSerializer, 
    GroupSerializer, CategorySerializer, GroupTypeSerializer, StoresGRNSerializer, StoresIntentSerializer
)
from django.shortcuts import get_object_or_404
from datetime import datetime
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
        history = []
        grns = storesGRN.objects.filter(is_active__in=[True]).order_by('-date')
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
            
            # Update Item quantities
            items = grn_instance.items
            if isinstance(items, list):
                for item_data in items:
                    item_id = item_data.get('item_id')
                    quantity = item_data.get('quantity', 0)
                    free = item_data.get('free', 0)
                    
                    try:
                        quantity = int(quantity)
                    except ValueError:
                        quantity = 0
                        
                    try:
                        free = int(free)
                    except ValueError:
                        free = 0
                        
                    total_addition = quantity + free
                    
                    if item_id and total_addition > 0:
                        try:
                            item = ItemMaster.objects.get(item_id=item_id)
                            item.total_quantity += total_addition
                        except ItemMaster.DoesNotExist:
                            pass
                            
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
                    item_id = item.get('item_id') or item.get('id') or item.get('itemId')
                    qty = int(item.get('quantity') or 0)
                    free = int(item.get('free') or 0)
                    total_addition = qty + free
                    
                    if item_id and total_addition > 0:
                        try:
                            master = ItemMaster.objects.get(item_id=str(item_id))
                            master.total_quantity = (master.total_quantity or 0) + total_addition
                            master.save()
                        except ItemMaster.DoesNotExist:
                            pass  # Item not in master — skip silently
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

    query = {
        "is_active": True
    }

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

    # ✅ Department mapping (using ORM for robustness)
    dept_map = {
        d.department_id: d.department_name
        for d in Department.objects.all()
    }

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
        d["department_name"] = dept_map.get(dept_code, None)

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
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    obj = get_object_or_404(storesIntent, intent_id=pk)
    if not obj.is_active:
        return Response({"error": "Intent not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    
    # Store old items to compare quantities if needed
    old_items = {it.get('item_id'): it.get('approved_quantity', 0) for it in (obj.items or []) if it.get('item_id')}
    
    data = request.data.copy()
    data['lastmodified_by'] = employee_id
    data['branch_code'] = branch_code
    data['outlet_code'] = outlet_code

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



@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def LabApprovedItemCreate(request):
    """
    POST /lab-approved-items/create/
    Body: { "items": [ { "item_id", "name", "hsn", "quantity" }, ... ] }
    """
    items = request.data.get('items', [])
 
    if not items or not isinstance(items, list):
        return Response(
            {"error": "items must be a non-empty list"},
            status=status.HTTP_400_BAD_REQUEST
        )
 
    serializer = LabApprovedItemSerializer(data=items, many=True)
    if serializer.is_valid():
        serializer.save()
        return Response(
            {
                "message": "Lab approved items saved successfully",
                "data": serializer.data
            },
            status=status.HTTP_201_CREATED
        )
 
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 


