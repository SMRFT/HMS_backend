import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from hospital.models import LaundryWardRequest, LaundryItemMaster
# from hospital.auth.decorators import require_auth
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission

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
            
            laundry_req = LaundryWardRequest.objects.create(
                uhid=data.get('uhid', ''),
                ipNumber=data.get('ipNumber', ''),
                patient_name=data.get('patient_name', ''),
                wardName=data.get('wardName', ''),
                roomNo=data.get('roomNo', ''),
                bedNo=data.get('bedNo', ''),
                items=data.get('items', []),
                request_type=data.get('request_type', 'Normal'),
                status='Pending',
                remarks=data.get('remarks', ''),
                requested_by=data.get('requested_by', '')
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Laundry request saved successfully',
                'data': {'id': str(laundry_req.id)}
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
                    'items': req.items,
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
                
            laundry_req = LaundryWardRequest.objects.get(id=req_id)
            laundry_req.status = new_status
            laundry_req.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Status updated to {new_status}'
            })
            
        except LaundryWardRequest.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Request not found'}, status=404)
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
                    'items': req.items,
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
            
            if not item_name:
                return JsonResponse({'success': False, 'error': 'Item name is required'}, status=400)
                
            if item_id:
                item = LaundryItemMaster.objects.get(id=item_id)
                item.item_name = item_name
                item.price = price
                item.save()
                msg = "Item updated successfully"
            else:
                LaundryItemMaster.objects.create(item_name=item_name, price=price)
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
