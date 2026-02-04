from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from ..models import Admission, Patient, DischargeDetail
from ..serializers import AdmissionSerializer, PatientSerializer, DischargeDetailSerializer
from django.db.models import Q
from pymongo import MongoClient
import os
from bson import ObjectId

from django.views.decorators.csrf import csrf_exempt

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_discharge_patient(request):
    """
    Search for a patient for discharge.
    Supports searching by UHID (OP Number) or IP Number.
    Priority:
    1. Active Admission (by IP or UHID)
    2. Patient Record (by UHID, for OP discharge if no admission found)
    """
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        admission_collection = db.hospital_admission
        patient_collection = db.hospital_patient
        
        uhid = request.GET.get('uhid', '').strip()
        ip_number = request.GET.get('ipNumber', '').strip()
        
        if not uhid and not ip_number:
            return Response({"error": "Please provide a search parameter (UHID or IP Number)"}, status=status.HTTP_400_BAD_REQUEST)

        results = []

        # 1. Search by IP Number (Strictly checks Admission)
        if ip_number:
            admissions = list(admission_collection.find({
                "ipNumber": {"$regex": ip_number, "$options": "i"}
            }))
            for adm in admissions:
                adm['id'] = str(adm['_id'])
                del adm['_id']
            results.extend(admissions)
            
        # 2. Search by UHID (OP Number)
        if uhid:
            # Check Admissions first
            admissions = list(admission_collection.find({
                "uhid": {"$regex": uhid, "$options": "i"}
            }))
            
            for adm in admissions:
                adm['id'] = str(adm['_id'])
                del adm['_id']
                # Avoid duplicates
                if not any(res.get('id') == adm.get('id') for res in results):
                    results.append(adm)
            
            # Check Patients
            patients = list(patient_collection.find({
                "uhid": {"$regex": uhid, "$options": "i"}
            }))
            
            for patient in patients:
                patient['id'] = str(patient['_id'])
                del patient['_id']
                # Check if this patient is already in results (via Admission)
                is_in_results = any(res.get('uhid') == patient.get('uhid') for res in results)
                if not is_in_results:
                    results.append(patient)

        return Response(results, status=status.HTTP_200_OK)
        
    except Exception as e:
        import traceback
        print("Error in search_discharge_patient:", e)
        print(traceback.format_exc())
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def discharge_detail_view(request):
    """
    GET: List all discharge records.
    POST: Create a new discharge record.
    """
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_dischargedetail
        
        if request.method == 'GET':
            discharge_details = list(collection.find().sort("lastmodified_date", -1))
            for detail in discharge_details:
                detail['id'] = str(detail['_id'])
                del detail['_id']
            return Response(discharge_details, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            from datetime import datetime
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['created_date'] = datetime.now()
            data['lastmodified_date'] = datetime.now()
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return Response(data, status=status.HTTP_201_CREATED)
            
    except Exception as e:
        import traceback
        print("Error in discharge_detail_view:", e)
        print(traceback.format_exc())
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

