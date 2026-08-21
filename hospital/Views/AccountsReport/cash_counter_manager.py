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

from ..dbcollection import global_db, profile_collection

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_employee_counter_assignments(request):
    """
    Fetch all HMS employees from backend_diagnostics_profile with their assigned cash counter details.
    """
    try:
        dept_collection = global_db['backend_diagnostics_Departments']
        desig_collection = global_db['backend_diagnostics_Designation']

        depts = {}
        for d in dept_collection.find({}, {"department_code": 1, "department_id": 1, "department_name": 1, "_id": 0}):
            code = d.get('department_code') or d.get('department_id')
            name = d.get('department_name')
            if code and name:
                depts[str(code)] = name

        desigs = {}
        for d in desig_collection.find({}, {"Designation_code": 1, "designation_id": 1, "designation": 1, "_id": 0}):
            code = d.get('Designation_code') or d.get('designation_id')
            name = d.get('designation')
            if code and name:
                desigs[str(code)] = name

        # Build map of active Cash Counters (counter_id -> counter_name)
        counters = {}
        try:
            for c in CashCounter.objects.filter(is_active=True):
                counters[str(c.counter_id)] = c.counter_name
        except Exception as e:
            print(f"Error reading CashCounter models: {e}")

        query = {
            "$or": [
                {"primaryRole": {"$regex": "^HMS"}},
                {"additionalRoles": {"$elemMatch": {"$regex": "^HMS"}}},
                {"employeeId": {"$exists": True}}
            ]
        }

        employees = list(profile_collection.find(
            query,
            {
                "employeeId": 1,
                "employeeName": 1,
                "name": 1,
                "designation": 1,
                "department": 1,
                "cashcounter": 1,
                "assigned_counter": 1,
                "assigned_counter_name": 1,
                "_id": 0
            }
        ))

        result = []
        for emp in employees:
            emp_id = emp.get('employeeId')
            emp_name = emp.get('employeeName') or emp.get('name') or emp_id
            if not emp_id or not emp_name:
                continue

            dept_code = str(emp.get('department') or '')
            desig_code = str(emp.get('designation') or '')
            dept_name = depts.get(dept_code, dept_code or '-')
            desig_name = desigs.get(desig_code, desig_code or '-')

            cid = str(emp.get('cashcounter') or emp.get('assigned_counter') or '')
            cname = emp.get('assigned_counter_name') or counters.get(cid, cid)

            result.append({
                "employeeId": str(emp_id),
                "employeeName": str(emp_name),
                "department": dept_name,
                "designation": desig_name,
                "assigned_counter": cid,
                "assigned_counter_name": cname
            })

        return Response({"success": True, "data": result})
    except Exception as e:
        import traceback
        print("🔥 Exception in get_employee_counter_assignments:")
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['POST', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def assign_employee_cash_counter(request):
    """
    Assign or unassign a Cash Counter to an Employee.
    """
    employee_id = request.data.get("employeeId")
    counter_id = request.data.get("counter_id")  # Can be empty string to unassign

    if not employee_id:
        return Response({"success": False, "message": "employeeId is required"}, status=400)

    try:
        counter_name = ""
        if counter_id:
            cc = CashCounter.objects.filter(counter_id=counter_id).first()
            if cc:
                counter_name = cc.counter_name

        res = profile_collection.update_one(
            {"employeeId": str(employee_id)},
            {"$set": {
                "cashcounter": counter_id or "",
                "assigned_counter": counter_id or "",
                "assigned_counter_name": counter_name or ""
            }}
        )

        if res.matched_count > 0:
            msg = f"Cash counter '{counter_name or counter_id}' assigned successfully" if counter_id else "Cash counter assignment removed"
            return Response({"success": True, "message": msg})
        else:
            return Response({"success": False, "message": f"Employee '{employee_id}' not found"}, status=404)
    except Exception as e:
        import traceback
        print("🔥 Exception in assign_employee_cash_counter:")
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)
