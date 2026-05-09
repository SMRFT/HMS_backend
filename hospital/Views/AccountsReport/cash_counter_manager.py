from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from ...models import CashCounter
from ...serializers import CashCounterSerializer
from pyauth.auth import HasRoleAndDataPermission
from django.utils import timezone

@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def cash_counter_manager(request):
    """
    CRUD Manager for Cash Counters.
    Supports:
    - GET: List all counters for the hospital.
    - POST: Create a new counter.
    - PATCH: Update/Deactivate a counter.
    """
    # Extract auth details
    hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
    branch_code = request.data.get("auth-branch-code") or request.META.get("HTTP_AUTH_BRANCH_CODE")
    user_id = request.data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID")

    if request.method == 'GET':
        counters = CashCounter.objects.filter(hospital_code=hospital_code)
        serializer = CashCounterSerializer(counters, many=True)
        return Response({
            "success": True, 
            "data": serializer.data
        })

    elif request.method == 'POST':
        data = request.data.copy()
        data['created_by'] = user_id
        data['hospital_code'] = hospital_code
        data['branch_code'] = branch_code
        data['is_active'] = True
        
        # Check if ID already exists (only if provided)
        cid = data.get("counter_id")
        if cid and CashCounter.objects.filter(counter_id=cid).exists():
             return Response({"success": False, "message": f"Counter ID '{cid}' already exists."})

        serializer = CashCounterSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True, 
                "message": "Cash counter created successfully", 
                "data": serializer.data
            })
        return Response({"success": False, "errors": serializer.errors})

    elif request.method == 'PATCH':
        counter_id = request.data.get("counter_id")
        if not counter_id:
            return Response({"success": False, "message": "counter_id is required for update."})

        try:
            counter = CashCounter.objects.get(counter_id=counter_id, hospital_code=hospital_code)
            data = request.data.copy()
            data['lastmodified_by'] = user_id
            data['lastmodified_date'] = timezone.now()
            
            serializer = CashCounterSerializer(counter, data=data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({
                    "success": True, 
                    "message": "Cash counter updated successfully", 
                    "data": serializer.data
                })
            return Response({"success": False, "errors": serializer.errors})
        except CashCounter.DoesNotExist:
            return Response({"success": False, "message": "Cash counter not found."})
