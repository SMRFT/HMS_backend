import datetime
import json
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import ItemMaster, Department, Group, Category, GroupType, storesGRN, storesIntent, Stores_LabApprovedItem, Stores_LabUsedQtyDetail, GeneralStoreVendor
from .serializer import (
    ItemMasterSerializer, DepartmentSerializer, 
    GroupSerializer, CategorySerializer, GroupTypeSerializer, StoresGRNSerializer, StoresIntentSerializer,
    Stores_LabApprovedItemSerializer, Stores_LabUsedQtyDetailSerializer, GeneralStoreVendorSerializer
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

    # ✅ Department mapping (from MongoDB department_collection, keyed by department_code)
    dept_map = {
        doc['department_code']: doc['department_name']
        for doc in department_collection.find({'is_active': True})
        if doc.get('department_code') and doc.get('department_name')
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