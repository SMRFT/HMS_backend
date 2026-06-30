import json
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from hospital.models import LaundryWardRequest, LaundryItemMaster
# from hospital.auth.decorators import require_auth
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from bson.decimal128 import Decimal128

MONGO_URI = os.getenv("GLOBAL_DB_HOST")

@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def save_laundry_request(request):
    """
    Saves a new laundry ward request.
    Expected Payload:
    {
        "uhid": "...",
        "ipNumber": "...",
        "patient_name": "...",
        "wardName": "...",
        "roomNo": "...",
        "bedNo": "...",
        "items": [{"item": "Bedsheets", "qty": 2}, ...],
        "request_type": "Normal",
        "remarks": "...",
        "requested_by": "..."
    }
    """
    if request.method == 'POST':
        try:
            data = request.data
            
            uhid = data.get('uhid', '')
            ipNumber = data.get('ipNumber', '')
            patient_name = data.get('patient_name', '')
            wardName = data.get('wardName', '')
            roomNo = data.get('roomNo', '')
            bedNo = data.get('bedNo', '')
            items = data.get('items', [])
            total_amount = float(data.get('total_amount', 0.00))
            request_type = data.get('request_type', 'Normal')
            remarks = data.get('remarks', '')
            requested_by = data.get('requested_by', '')
            
            with MongoClient(MONGO_URI) as client:
                db = client["HMS"]
                col = db["hospital_laundrywardrequest"]
                
                # Get next increment ID
                last = col.find_one(sort=[("id", -1)])
                next_id = (last["id"] + 1) if last and "id" in last else 1
                
                now = timezone.now()
                doc = {
                    "id": next_id,
                    "uhid": uhid,
                    "ipNumber": ipNumber,
                    "patient_name": patient_name,
                    "wardName": wardName,
                    "roomNo": roomNo,
                    "bedNo": bedNo,
                    "items": items,
                    "total_amount": Decimal128(str(total_amount)),
                    "request_type": request_type,
                    "status": "Pending",
                    "remarks": remarks,
                    "requested_by": requested_by,
                    "requested_date": now,
                    "created_date": now,
                    "lastmodified_date": now
                }
                col.insert_one(doc)
            
            return JsonResponse({
                'success': True,
                'message': 'Laundry request saved successfully',
                'data': {'id': str(next_id)}
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def get_laundry_requests(request):
    """
    Get all laundry requests for a given uhid and ipNumber
    Query params: uhid, ipNumber
    """
    if request.method == 'GET':
        try:
            uhid = request.GET.get('uhid', '')
            ipNumber = request.GET.get('ipNumber', '')
            
            requests = LaundryWardRequest.objects.filter(uhid=uhid, ipNumber=ipNumber).order_by('-requested_date')
            
            data = []
            for req in requests:
                data.append({
                    'id': str(req.id),
                    'patient_name': req.patient_name,
                    'uhid': req.uhid,
                    'ipNumber': req.ipNumber,
                    'wardName': req.wardName,
                    'roomNo': req.roomNo,
                    'bedNo': req.bedNo,
                    'items': json.loads(req.items) if isinstance(req.items, str) else req.items,
                    'total_amount': str(getattr(req, 'total_amount', 0.00)),
                    'request_type': req.request_type,
                    'status': req.status,
                    'remarks': req.remarks,
                    'requested_by': req.requested_by,
                    'requested_date': req.requested_date.strftime('%d-%m-%Y %I:%M %p') if req.requested_date else '-'
                })
                
            return JsonResponse({
                'success': True,
                'data': data
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
            
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@api_view(['POST', 'GET', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_laundry_status(request):
    """
    Updates the status of a laundry request.
    Expected Payload:
    {
        "id": 1,
        "status": "Completed"
    }
    """
    if request.method == 'PATCH':
        try:
            data = request.data
            req_id = data.get('id')
            new_status = data.get('status')
            
            if not req_id or not new_status:
                return JsonResponse({'success': False, 'error': 'Missing id or status'}, status=400)
                
            updated = LaundryWardRequest.objects.filter(id=req_id).update(status=new_status)
            if updated == 0:
                return JsonResponse({'success': False, 'error': 'Request not found'}, status=404)
            
            return JsonResponse({
                'success': True,
                'message': f'Status updated to {new_status}'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
            
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def get_all_laundry_requests(request):
    """
    Get all laundry requests across all patients
    """
    if request.method == 'GET':
        try:
            requests = LaundryWardRequest.objects.all().order_by('-requested_date')
            
            data = []
            for req in requests:
                data.append({
                    'id': str(req.id),
                    'patient_name': req.patient_name,
                    'uhid': req.uhid,
                    'ipNumber': req.ipNumber,
                    'wardName': req.wardName,
                    'roomNo': req.roomNo,
                    'bedNo': req.bedNo,
                    'items': json.loads(req.items) if isinstance(req.items, str) else req.items,
                    'total_amount': str(getattr(req, 'total_amount', 0.00)),
                    'request_type': req.request_type,
                    'status': req.status,
                    'remarks': req.remarks,
                    'requested_by': req.requested_by,
                    'requested_date': req.requested_date.strftime('%d-%m-%Y %I:%M %p') if req.requested_date else '-'
                })
                
            return JsonResponse({
                'success': True,
                'data': data
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
            
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def get_laundry_items_master(request):

    if request.method == 'GET':

        try:

            items = LaundryItemMaster.objects.all().order_by(
                'item_name'
            )

            data = []

            for i in items:

                if i.is_active:

                    data.append({
                        'id': str(i.id),
                        'item_name': i.item_name,
                        'item_id': i.item_id,
                        'price': str(i.price)
                    })

            return JsonResponse({
                'success': True,
                'data': data
            })

        except Exception as e:

            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    }, status=405)


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def save_laundry_item_master(request):
    if request.method == 'POST':
        try:
            data = request.data
            item_id = data.get('id')
            item_name = data.get('item_name', '')
            price = data.get('price', 0)
            custom_item_id = data.get('item_id', '')
            
            if not item_name:
                return JsonResponse({'success': False, 'error': 'Item name is required'}, status=400)
                
            if item_id:
                item = LaundryItemMaster.objects.get(id=item_id)
                item.item_name = item_name
                item.price = price
                item.item_id = custom_item_id
                item.save()
                msg = "Item updated successfully"
            else:
                LaundryItemMaster.objects.create(item_name=item_name, price=price, item_id=custom_item_id)
                msg = "Item created successfully"
                
            return JsonResponse({'success': True, 'message': msg})
        except LaundryItemMaster.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Item not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def delete_laundry_item_master(request):
    if request.method == 'POST':
        try:
            data = request.data
            item_id = data.get('id')
            
            if not item_id:
                return JsonResponse({'success': False, 'error': 'Item ID is required'}, status=400)
                
            item = LaundryItemMaster.objects.get(id=item_id)
            item.is_active = False # soft delete
            item.save()
            return JsonResponse({'success': True, 'message': 'Item deleted successfully'})
            
        except LaundryItemMaster.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Item not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)
