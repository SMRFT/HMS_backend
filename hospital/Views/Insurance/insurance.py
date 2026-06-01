from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.http import JsonResponse
from django.utils import timezone
from pyauth.auth import HasRoleAndDataPermission
from ...models import Admission, Patient, InsuranceProvider, RoomCategory, Room
from .models import InsuranceClaim
from .serializer import InsuranceClaimSerializer
import traceback

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_patient_admission_details(request):
    """
    Fetch patient and admission details by UHID or IP Number.
    """
    uhid = request.GET.get('uhid')
    ip_number = request.GET.get('ip_number')
    hospital_code = (
        request.headers.get("auth-hospital-code") or 
        request.headers.get("Branch-Code") or 
        request.headers.get("auth-branch-code") or 
        "system"
    )

    from ...serializers import AdmissionSerializer
    try:
        print(f"--- get_patient_admission_details ---")
        print(f"UHID: {uhid}, IP: {ip_number}, Hospital: {hospital_code}")
        
        # Support both UHID and IP Number search safely for Djongo
        # We fetch without ordering to avoid SQLDecodeError and sort in Python
        admissions = []
        if uhid:
            admissions = list(Admission.objects.filter(uhid=uhid).order_by())
        elif ip_number:
            admissions = list(Admission.objects.filter(ipNumber=ip_number).order_by())
        
        admission = None
        if admissions:
            # Sort by admissionDateTime descending in Python
            admissions.sort(key=lambda x: x.admissionDateTime if x.admissionDateTime else timezone.now(), reverse=True)
            admission = admissions[0]
            print(f"Found admission: {admission.ipNumber} for hospital: {admission.hospital_code}")

        if not admission:
            return Response({"success": False, "error": f"Admission not found for {uhid or ip_number}"}, status=404)

        serializer = AdmissionSerializer(admission)
        return Response({"success": True, "data": serializer.data})

    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def insurance_claim_view(request, claim_id=None):
    hospital_code = request.headers.get("auth-hospital-code") or "system"
    branch_code = request.headers.get("Branch-Code") or "system"
    employee_id = request.headers.get("auth-user-id") or "system"

    if request.method == 'GET':
        try:
            if claim_id:
                claim = InsuranceClaim.objects.filter(claim_id=claim_id, hospital_code=hospital_code).first()
                if not claim:
                    return Response({"success": False, "error": "Claim not found"}, status=404)
                serializer = InsuranceClaimSerializer(claim)
                return Response({"success": True, "data": serializer.data})
            
            # List claims
            from_date = request.GET.get('from_date')
            to_date = request.GET.get('to_date')
            company = request.GET.get('company')
            show_deleted = request.GET.get('show_deleted') == 'true'

            query = InsuranceClaim.objects.filter(hospital_code=hospital_code)
            
            if not show_deleted:
                query = query.filter(is_active=True)
            
            if from_date:
                query = query.filter(claim_date__gte=from_date)
            if to_date:
                query = query.filter(claim_date__lte=to_date)
            if company and company != 'ALL':
                query = query.filter(insurance_company=company)

            claims = query.order_by('-claim_date')
            serializer = InsuranceClaimSerializer(claims, many=True)
            return Response({"success": True, "data": serializer.data})

        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            data['hospital_code'] = hospital_code
            data['branch_code'] = branch_code
            data['created_by'] = employee_id
            
            serializer = InsuranceClaimSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response({"success": True, "message": "Claim created successfully", "data": serializer.data}, status=201)
            return Response({"success": False, "error": serializer.errors}, status=400)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'PATCH':
        try:
            if not claim_id:
                return Response({"success": False, "error": "Claim ID required"}, status=400)
            
            claim = InsuranceClaim.objects.filter(claim_id=claim_id, hospital_code=hospital_code).first()
            if not claim:
                return Response({"success": False, "error": "Claim not found"}, status=404)
            
            data = request.data.copy()
            data['lastmodified_by'] = employee_id
            
            serializer = InsuranceClaimSerializer(claim, data=data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({"success": True, "message": "Claim updated successfully", "data": serializer.data})
            return Response({"success": False, "error": serializer.errors}, status=400)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'DELETE':
        try:
            if not claim_id:
                return Response({"success": False, "error": "Claim ID required"}, status=400)
            
            claim = InsuranceClaim.objects.filter(claim_id=claim_id, hospital_code=hospital_code).first()
            if not claim:
                return Response({"success": False, "error": "Claim not found"}, status=404)
            
            # Soft delete
            claim.is_active = False
            claim.lastmodified_by = employee_id
            claim.save()
            
            return Response({"success": True, "message": "Claim deleted successfully"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)
