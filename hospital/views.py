from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128
import json
from django.views.decorators.csrf import csrf_exempt

# Auth/permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from pyauth.auth import HasRoleAndDataPermission

import os
from dotenv import load_dotenv
load_dotenv()
    
from .models import Billing

from .serializers import PatientSerializer
@api_view(['GET', 'POST'])
@csrf_exempt
def patientCreateView(request):
    if request.method == 'GET':
        uhid = request.GET.get('uhid')
        ip_number = request.GET.get('ip_number')
        mobile = request.GET.get('mobile')

        # Filter based on parameters
        if uhid:
            patients = Patient.objects.filter(uhid=uhid)
        elif ip_number:
            patients = Patient.objects.filter(ip_number=ip_number)
        elif mobile:
            patients = Patient.objects.filter(mobilePhone=mobile)
        else:
            patients = Patient.objects.all()

        serializer = PatientSerializer(patients, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        print("Received POST data:", request.data)
        
        uhid = request.data.get('uhid')
        patient = None

        if uhid:
            try:
                patient = Patient.objects.get(uhid=uhid)
                print(f"Found existing patient: {patient}")
                serializer = PatientSerializer(patient, data=request.data, partial=True)
            except Patient.DoesNotExist:
                print(f"Patient with UHID {uhid} not found. Creating new...")
                serializer = PatientSerializer(data=request.data)
        else:
            print("No UHID provided. Creating new patient...")
            serializer = PatientSerializer(data=request.data)

        if serializer.is_valid():
            print("Serializer Valid. Saving...")
            try:
                patient = serializer.save()
                print("Patient Saved:", patient)
            except Exception as e:
                print("Error saving patient:", e)
                import traceback
                traceback.print_exc()
                raise e


            # ✅ Automatically create Billing record
            registration_fee = request.data.get('registrationFee', 0) or 0
            consulting_fee = request.data.get('consultingFee', 0) or 0
            total_fees = request.data.get('totalFees', 0) or 0
            payment_method = request.data.get('payment_method', None)

            Billing.objects.create(
                patient=patient,
                registration_fee=registration_fee,
                consulting_fee=consulting_fee,
                total_fees=total_fees,
                payment_method=payment_method
            )

            return Response({
                "message": "Patient registered successfully.",
                "uhid": patient.uhid,
                "patient": serializer.data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .models import Doctor
from .serializers import DoctorSerializer

@csrf_exempt
def doctor_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            serializer = DoctorSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return JsonResponse(serializer.data, status=201)
            return JsonResponse(serializer.errors, status=400)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON data"}, status=400)
    return JsonResponse({"error": "Method not allowed"}, status=405)


from .models import Doctor
from .serializers import DoctorSerializer
@api_view(['GET'])
def doctor_list(request):
    doctors = Doctor.objects.all()
    serializer = DoctorSerializer(doctors, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


from bson import Decimal128
# Helper function to convert Decimal128 fields to float
def convert_decimal128_to_float(data):
    for key, value in data.items():
        if isinstance(value, Decimal128):
            data[key] = float(value.to_decimal())
        elif isinstance(value, dict):
            convert_decimal128_to_float(value)  # Recurse if nested dict
    return data


@api_view(['GET', 'PATCH'])
def doctor_detail(request, first_name):
    # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_doctor']

    doctor = collection.find_one({"first_name": first_name})

    if not doctor:
        return Response({"error": "Doctor not found"}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        # Return doctor data (excluding _id field from MongoDB document)
        doctor_data = {key: doctor[key] for key in doctor if key != '_id'}
        doctor_data = convert_decimal128_to_float(doctor_data)  # Convert Decimal128 to float
        return Response(doctor_data, status=status.HTTP_200_OK)
    
    if request.method == 'PATCH':
        # Update the doctor details with the provided data
        update_data = request.data
        result = collection.update_one(
            {"first_name": first_name},
            {"$set": update_data}
        )

        if result.modified_count > 0:
            # Return the updated doctor data
            updated_doctor = collection.find_one({"first_name": first_name})
            updated_doctor_data = {key: updated_doctor[key] for key in updated_doctor if key != '_id'}
            updated_doctor_data = convert_decimal128_to_float(updated_doctor_data)  # Convert Decimal128 to float
            return Response(updated_doctor_data, status=status.HTTP_200_OK)
        else:
            return Response({"error": "No changes were made or invalid data"}, status=status.HTTP_400_BAD_REQUEST)


# View to list all CT investigations
def get_investigations(request):  
    # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['CT Scan']
    investigations = list(collection.find({}, {'_id': 0}))  # Exclude _id field
    return JsonResponse(investigations, safe=False)


def get_patient_report(request, uhid, subUhid):
    # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['CT Scan']
    
    # Combine uhid and subUhid to get the full UHID
    full_uhid = f'{uhid}/{subUhid}'
    
    # Fetch the document from MongoDB
    patient_details = collection.find_one({'uhid': full_uhid})

    # Check if patient_details exists and convert ObjectId fields to string
    if patient_details:
        if '_id' in patient_details:
            patient_details['_id'] = str(patient_details['_id'])

        return JsonResponse(patient_details, safe=False)
    else:
        return JsonResponse({'error': 'Patient not found'}, status=404)

from django.http import JsonResponse
from rest_framework.decorators import api_view
from pymongo import MongoClient
from bson import ObjectId

@api_view(['POST'])
def create_ct_report(request):
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_ctreport']

    data = request.data
    inserted = collection.insert_one(data)
    return JsonResponse({"_id": str(inserted.inserted_id)}, status=201)


from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework import status
from .models import CTReport
from .serializers import CTReportSerializer

@api_view(['GET'])
def get_ct_reports(request, patientId=None):
    if patientId:
        # Fetch CT report for the specific patientId
        try:
            report = CTReport.objects.get(patientId=patientId)
            serializer = CTReportSerializer(report)
            return JsonResponse(serializer.data, status=status.HTTP_200_OK)
        except CTReport.DoesNotExist:
            return JsonResponse({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
    else:
        # Fetch all CT reports
        reports = CTReport.objects.all()
        serializer = CTReportSerializer(reports, many=True)
        return JsonResponse(serializer.data, safe=False, status=status.HTTP_200_OK)
    
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import json

@csrf_exempt
def delete_ct_report(request, patient_id):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_ctreport']

    if request.method == 'DELETE':
        try:
            # Get the investigation from request body if provided
            body_data = {}
            if request.body:
                body_data = json.loads(request.body)
            
            # Create a query filter
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if 'investigation' in body_data and body_data['investigation']:
                query["investigation"] = body_data['investigation']
            
            # Find the report before deletion to return its data
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Convert ObjectId to string for JSON response
            report_copy = report.copy()
            if '_id' in report_copy:
                report_copy['_id'] = str(report_copy['_id'])
            
            # Delete the report
            result = collection.delete_one(query)
            
            if result.deleted_count == 0:
                return JsonResponse({"error": "Failed to delete report"}, status=400)
            
            # Return the deleted report data
            return JsonResponse(report_copy, status=200, safe=False)
            
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from pymongo import MongoClient
import json

@csrf_exempt
def approve_ct_report(request, patient_id):
    
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_ctreport']
    
    if request.method == 'PATCH':
        try:
            # Parse the request body to get investigation and date
            data = json.loads(request.body)
            investigation = data.get('investigation')
            date = data.get('date')
            
            # Create a query with patientId, investigation, and date
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if investigation:
                query["investigation"] = investigation
                
            # Add date to query if provided
            if date:
                query["date"] = date
            
            # Find the report by query
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Update the approve field and approve_time
            update_result = collection.update_one(
                query,
                {
                    "$set": {
                        "approve": True,
                        "approve_time": now().isoformat()
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # Retrieve the updated report
            updated_report = collection.find_one(query)

            # Convert ObjectId to string for JSON serialization
            if '_id' in updated_report:
                updated_report['_id'] = str(updated_report['_id'])

            # Return the updated report
            return JsonResponse(updated_report, status=200, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)

from django.http import JsonResponse
from pymongo import MongoClient
from django.views.decorators.csrf import csrf_exempt

# View to list all MRI investigations
def get_mri_investigations(request):
   # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['MRI Scan']
    investigations = list(collection.find({}, {'_id': 0}))  # Exclude _id field
    return JsonResponse(investigations, safe=False)

def get_mri_patient_report(request, uhid, subUhid):
    # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['MRI Scan']
    
    # Combine uhid and subUhid to get the full UHID
    full_uhid = f'{uhid}/{subUhid}'
    
    # Fetch the document from MongoDB
    patient_details = collection.find_one({'uhid': full_uhid})

    # Check if patient_details exists and convert ObjectId fields to string
    if patient_details:
        if '_id' in patient_details:
            patient_details['_id'] = str(patient_details['_id'])

        return JsonResponse(patient_details, safe=False)
    else:
        return JsonResponse({'error': 'Patient not found'}, status=404)



from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.decorators import api_view
from .models import MRIReport  # Assuming your MRIReport model is similar to CTReport
from .serializers import MRIReportSerializer  # Assuming you have a corresponding serializer for MRIReport

@api_view(['POST'])
def create_mri_report(request):
    if request.method == 'POST':
        serializer = MRIReportSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(serializer.data, status=201)
        return JsonResponse(serializer.errors, status=400)
    

from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework import status
from .models import MRIReport
from .serializers import MRIReportSerializer

@api_view(['GET'])
def get_mri_reports(request, patientId=None):
    if patientId:
        # Fetch MRI report for the specific patientId
        try:
            report = MRIReport.objects.get(patientId=patientId)
            serializer = MRIReportSerializer(report)
            return JsonResponse(serializer.data, status=status.HTTP_200_OK)
        except MRIReport.DoesNotExist:
            return JsonResponse({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
    else:
        # Fetch all MRI reports
        reports = MRIReport.objects.all()
        serializer = MRIReportSerializer(reports, many=True)
        return JsonResponse(serializer.data, safe=False, status=status.HTTP_200_OK)
    
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import json

@csrf_exempt
def delete_mri_report(request, patient_id):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_mrireport']

    if request.method == 'DELETE':
        try:
            # Get the investigation from request body if provided
            body_data = {}
            if request.body:
                body_data = json.loads(request.body)
            
            # Create a query filter
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if 'investigation' in body_data and body_data['investigation']:
                query["investigation"] = body_data['investigation']
            
            # Find the report before deletion to return its data
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Convert ObjectId to string for JSON response
            report_copy = report.copy()
            if '_id' in report_copy:
                report_copy['_id'] = str(report_copy['_id'])
            
            # Delete the report
            result = collection.delete_one(query)
            
            if result.deleted_count == 0:
                return JsonResponse({"error": "Failed to delete report"}, status=400)
            
            # Return the deleted report data
            return JsonResponse(report_copy, status=200, safe=False)
            
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from pymongo import MongoClient
import json

@csrf_exempt
def approve_mri_report(request, patient_id):
    
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_mrireport']  # Changed collection name to 'hospital_mrireport'
 
    if request.method == 'PATCH':
        try:
            # Parse the request body to get investigation and date
            data = json.loads(request.body)
            investigation = data.get('investigation')
            date = data.get('date')
            
            # Create a query with patientId, investigation, and date
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if investigation:
                query["investigation"] = investigation
                
            # Add date to query if provided
            if date:
                query["date"] = date
            
            # Find the report by query
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Update the approve field and approve_time
            update_result = collection.update_one(
                query,
                {
                    "$set": {
                        "approve": True,
                        "approve_time": now().isoformat()
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # Retrieve the updated report
            updated_report = collection.find_one(query)

            # Convert ObjectId to string for JSON serialization
            if '_id' in updated_report:
                updated_report['_id'] = str(updated_report['_id'])

            # Return the updated report
            return JsonResponse(updated_report, status=200, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)
    
from django.http import JsonResponse
from pymongo import MongoClient
from django.views.decorators.csrf import csrf_exempt

# View to list all MRI investigations
def get_usg_investigations(request):
   # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['Scanning']
    investigations = list(collection.find({}, {'_id': 0}))  # Exclude _id field
    return JsonResponse(investigations, safe=False)

def get_usg_patient_report(request, uhid, subUhid):
    # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['Scanning']
    
    # Combine uhid and subUhid to get the full UHID
    full_uhid = f'{uhid}/{subUhid}'
    
    # Fetch the document from MongoDB
    patient_details = collection.find_one({'uhid': full_uhid})

    # Check if patient_details exists and convert ObjectId fields to string
    if patient_details:
        if '_id' in patient_details:
            patient_details['_id'] = str(patient_details['_id'])

        return JsonResponse(patient_details, safe=False)
    else:
        return JsonResponse({'error': 'Patient not found'}, status=404)


from django.http import JsonResponse
from rest_framework.decorators import api_view
from pymongo import MongoClient
from bson import ObjectId

@api_view(['POST'])
def create_usg_report(request):
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_usgreport']

    data = request.data
    inserted = collection.insert_one(data)
    return JsonResponse({"_id": str(inserted.inserted_id)}, status=201)


from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework import status
from .models import USGReport
from .serializers import USGReportSerializer

@api_view(['GET'])
def get_usg_reports(request, patientId=None):
    if patientId:
        # Fetch USG report for the specific patientId
        try:
            report = USGReport.objects.get(patientId=patientId)
            serializer = USGReportSerializer(report)
            return JsonResponse(serializer.data, status=status.HTTP_200_OK)
        except USGReport.DoesNotExist:
            return JsonResponse({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
    else:
        # Fetch all CT reports
        reports = USGReport.objects.all()
        serializer = USGReportSerializer(reports, many=True)
        return JsonResponse(serializer.data, safe=False, status=status.HTTP_200_OK)
    
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import json

@csrf_exempt
def delete_usg_report(request, patient_id):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_usgreport']

    if request.method == 'DELETE':
        try:
            # Get the investigation from request body if provided
            body_data = {}
            if request.body:
                body_data = json.loads(request.body)
            
            # Create a query filter
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if 'investigation' in body_data and body_data['investigation']:
                query["investigation"] = body_data['investigation']
            
            # Find the report before deletion to return its data
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Convert ObjectId to string for JSON response
            report_copy = report.copy()
            if '_id' in report_copy:
                report_copy['_id'] = str(report_copy['_id'])
            
            # Delete the report
            result = collection.delete_one(query)
            
            if result.deleted_count == 0:
                return JsonResponse({"error": "Failed to delete report"}, status=400)
            
            # Return the deleted report data
            return JsonResponse(report_copy, status=200, safe=False)
            
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from pymongo import MongoClient
import json

@csrf_exempt
def approve_usg_report(request, patient_id):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_usgreport']

    if request.method == 'PATCH':
        try:
            # Parse the request body to get investigation and date
            data = json.loads(request.body)
            investigation = data.get('investigation')
            date = data.get('date')
            
            # Create a query with patientId, investigation, and date
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if investigation:
                query["investigation"] = investigation
                
            # Add date to query if provided
            if date:
                query["date"] = date
            
            # Find the report by query
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Update the approve field and approve_time
            update_result = collection.update_one(
                query,
                {
                    "$set": {
                        "approve": True,
                        "approve_time": now().isoformat()
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # Retrieve the updated report
            updated_report = collection.find_one(query)

            # Convert ObjectId to string for JSON serialization
            if '_id' in updated_report:
                updated_report['_id'] = str(updated_report['_id'])

            # Return the updated report
            return JsonResponse(updated_report, status=200, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)

from django.http import JsonResponse
from pymongo import MongoClient
from django.views.decorators.csrf import csrf_exempt

# View to list all MRI investigations
def get_x_ray_investigations(request):
   # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['X-Ray']
    investigations = list(collection.find({}, {'_id': 0}))  # Exclude _id field
    return JsonResponse(investigations, safe=False)

def get_x_ray_patient_report(request, uhid, subUhid):
    # MongoDB connection setup
    client = MongoClient(f'mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['X-Ray']
    
    # Combine uhid and subUhid to get the full UHID
    full_uhid = f'{uhid}/{subUhid}'
    
    # Fetch the document from MongoDB
    patient_details = collection.find_one({'uhid': full_uhid})

    # Check if patient_details exists and convert ObjectId fields to string
    if patient_details:
        if '_id' in patient_details:
            patient_details['_id'] = str(patient_details['_id'])

        return JsonResponse(patient_details, safe=False)
    else:
        return JsonResponse({'error': 'Patient not found'}, status=404)



from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.decorators import api_view
from .models import XRayReport  # Assuming your MRIReport model is similar to CTReport
from .serializers import XRayReportSerializer  # Assuming you have a corresponding serializer for MRIReport

@api_view(['POST'])
def create_x_ray_report(request):
    if request.method == 'POST':
        serializer = XRayReportSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(serializer.data, status=201)
        return JsonResponse(serializer.errors, status=400)
    

from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework import status
from .models import XRayReport
from .serializers import XRayReportSerializer

@api_view(['GET'])
def get_x_ray_reports(request, patientId=None):
    if patientId:
        # Fetch MRI report for the specific patientId
        try:
            report = XRayReport.objects.get(patientId=patientId)
            serializer = XRayReportSerializer(report)
            return JsonResponse(serializer.data, status=status.HTTP_200_OK)
        except XRayReport.DoesNotExist:
            return JsonResponse({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
    else:
        # Fetch all MRI reports
        reports = XRayReport.objects.all()
        serializer = XRayReportSerializer(reports, many=True)
        return JsonResponse(serializer.data, safe=False, status=status.HTTP_200_OK)
    
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import json

@csrf_exempt
def delete_x_ray_report(request, patient_id):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_xrayreport']

    if request.method == 'DELETE':
        try:
            # Get the investigation from request body if provided
            body_data = {}
            if request.body:
                body_data = json.loads(request.body)
            
            # Create a query filter
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if 'investigation' in body_data and body_data['investigation']:
                query["investigation"] = body_data['investigation']
            
            # Find the report before deletion to return its data
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Convert ObjectId to string for JSON response
            report_copy = report.copy()
            if '_id' in report_copy:
                report_copy['_id'] = str(report_copy['_id'])
            
            # Delete the report
            result = collection.delete_one(query)
            
            if result.deleted_count == 0:
                return JsonResponse({"error": "Failed to delete report"}, status=400)
            
            # Return the deleted report data
            return JsonResponse(report_copy, status=200, safe=False)
            
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from pymongo import MongoClient
import json

@csrf_exempt
def approve_x_ray_report(request, patient_id):
    
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_xrayreport']  # Changed collection name to 'hospital_mrireport'

    if request.method == 'PATCH':
        try:
            # Parse the request body to get investigation and date
            data = json.loads(request.body)
            investigation = data.get('investigation')
            date = data.get('date')
            
            # Create a query with patientId, investigation, and date
            query = {"patientId": patient_id}
            
            # Add investigation to query if provided
            if investigation:
                query["investigation"] = investigation
                
            # Add date to query if provided
            if date:
                query["date"] = date
            
            # Find the report by query
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Update the approve field and approve_time
            update_result = collection.update_one(
                query,
                {
                    "$set": {
                        "approve": True,
                        "approve_time": now().isoformat()
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # Retrieve the updated report
            updated_report = collection.find_one(query)

            # Convert ObjectId to string for JSON serialization
            if '_id' in updated_report:
                updated_report['_id'] = str(updated_report['_id'])

            # Return the updated report
            return JsonResponse(updated_report, status=200, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


from .models import Summary
from .serializers import SummarySerializer

@api_view(['GET'])
def get_summaries(request):
    summaries = Summary.objects.all()
    serializer = SummarySerializer(summaries, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

    
@api_view(['POST'])
def create_summary(request):
    serializer = SummarySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from pymongo import MongoClient
from datetime import datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status


@api_view(['PATCH'])
def approve_summary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_summary']  # Changed collection name to 'hospital_summary'
    try:
        # Find the summary by IP number and update
        result = collection.update_one(
            {"ipNo": ip_no},  # Query to find the document by IP No
            {"$set": {
                "approve": True,
                "approve_time": datetime.now().isoformat()  # Set the current time
            }}
        )
        
        # Check if the document was updated
        if result.matched_count > 0:
            return Response({"message": "Summary approved successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
def delete_summary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_summary']  # Changed collection name to 'hospital_summary
    try:
        # Find and delete the summary by IP number
        result = collection.delete_one({"ipNo": ip_no})  # Query to find the document by IP No and delete it
        
        # Check if the document was deleted
        if result.deleted_count > 0:
            return Response({"message": "Summary deleted successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

from urllib.parse import unquote

@api_view(['GET'])
def get_editsummary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_summary']  # Changed collection name to 'hospital_summary'
    decoded_ip_no = unquote(ip_no)  # Decode the IP No
    summary = collection.find_one({"ipNo": decoded_ip_no})
    # Rest of the logic...

    try:
        # Find the document by IP number
        summary = collection.find_one({"ipNo": ip_no})
        
        if summary:
            summary['_id'] = str(summary['_id'])  # Convert ObjectId to string
            return Response(summary, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['PATCH'])
def update_summary_fields(request, ip_no):
    # MongoDB connection setup# MongoDB connection setup
    client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
    db = client['ShanmugaHospital']
    collection = db['hospital_summary']  # Changed collection name to 'hospital_summary'
    try:
        decoded_ip_no = unquote(ip_no)  # Decode the IP No
        data = request.data

        # Check if 'fieldsData' exists and is non-empty
        if 'fieldsData' not in data or not data['fieldsData']:
            return Response({"error": "No fieldsData provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Process the data and update the document in the database
        updated_summary = collection.update_one(
            {"ipNo": decoded_ip_no},
            {"$set": data}
        )

        if updated_summary.matched_count > 0:
            return Response({"message": "Summary updated successfully!"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    


from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import Patient
from .serializers import PatientSerializer

@api_view(['GET'])
def op_patient_detail_by_uhid(request, uhid):
    try:
        patient = Patient.objects.get(uhid=uhid)
        serializer = PatientSerializer(patient)
        return Response(serializer.data)
    except Patient.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)

    

from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import Admission
from .serializers import AdmissionSerializer

@api_view(['GET'])
def ip_patient_detail_by_ipNumber(request, ipNumber):
    try:
        patient = Admission.objects.get(ipNumber=ipNumber)
        serializer = AdmissionSerializer(patient)
        return Response(serializer.data)
    except Admission.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)   
    
    
from rest_framework.response import Response
from rest_framework.decorators import api_view
from django.db import transaction
from .models import EstimateBilling
from .serializers import EstimateBillingSerializer
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@api_view(['POST'])
def estimate_billing_create(request):
    if request.method == 'POST':
        with transaction.atomic():  # Ensures atomic operation
            last_bill = EstimateBilling.objects.select_for_update().order_by('-id').first()

            if last_bill and last_bill.EstBillNo:
                last_number = int(last_bill.EstBillNo)
                next_number = last_number + 1
            else:
                next_number = 1  # Start from 000001 if no previous bill exists

            # Format EstBillNo as a 6-digit number (e.g., 000001, 000002, etc.)
            formatted_bill_no = f"{next_number:06d}"

            # Ensure uniqueness
            while EstimateBilling.objects.filter(EstBillNo=formatted_bill_no).exists():
                next_number += 1
                formatted_bill_no = f"{next_number:06d}"

            # Create a mutable copy of request data
            request_data = request.data.copy()
            request_data['EstBillNo'] = formatted_bill_no

            serializer = EstimateBillingSerializer(data=request_data)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Form data saved successfully!', 'EstBillNo': formatted_bill_no}, status=201)

            return Response(serializer.errors, status=400)


@api_view(['GET'])
def estimate_billing_list(request):
    estimates = EstimateBilling.objects.all().order_by('-id')  # Fetch all records, latest first
    serializer = EstimateBillingSerializer(estimates, many=True)
    return Response(serializer.data)


import json
from django.http import JsonResponse
from pymongo import MongoClient
from django.views.decorators.http import require_http_methods

@require_http_methods(["GET"])
def get_bill_types(request):
    try:
        # Connect to MongoDB
        client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
        db = client['ShanmugaHospital']
        collection = db['hospital_investigationprice']

        # Fetch all documents
        all_bills = list(collection.find({}, {"_id": 0}))
        
        # Compile all items across all bill types
        all_items = []
        for bill in all_bills:
            bill_type = bill.get("BillType", "Unknown")
            items = bill.get("Items", [])
            
            # Add bill type to each item for context
            for item in items:
                item['billType'] = bill_type
            
            all_items.extend(items)

        # Close the MongoDB connection
        client.close()

        # Return JsonResponse with all items
        return JsonResponse({"items": all_items}, safe=True)
    
    except Exception as e:
        # Handle any errors that might occur
        return JsonResponse({
            "error": "An error occurred while fetching bill types",
            "details": str(e)
        }, status=500)
    
import json
from datetime import datetime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from pymongo import MongoClient
from .models import EstimateBilling  # Import EstimateBilling model

@csrf_exempt
@require_http_methods(["POST"])
def invest_billing_create(request):
    try:
        # Parse the JSON request data
        data = json.loads(request.body)

        # Extract EstBillNo from request data for deletion
        est_bill_no = data.get("EstBillNo")
        if est_bill_no:
            deleted_count, _ = EstimateBilling.objects.filter(EstBillNo=est_bill_no).delete()
            if deleted_count == 0:
                print(f"No EstimateBilling found with EstBillNo: {est_bill_no}")

        # Remove EstBillNo and EstBillDate from new data before storing
        data.pop("EstBillNo", None)
        data.pop("EstBillDate", None)

        # Extract the billType to determine the collection name
        bill_type = data.get("billType")
        if not bill_type:
            return JsonResponse({"error": "BillType is required"}, status=400)

        # Connect to MongoDB
        client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
        db = client['ShanmugaHospital']
        collection = db[bill_type]  # Collection named after billType

        # Check if record already exists with same UHID, billType, and investBillDate
        uhid = data.get("uhid")
        invest_bill_date = data.get("investBillDate")
        
        if uhid and invest_bill_date:
            existing_record = collection.find_one({
                "uhid": uhid,
                "billType": bill_type,
                "investBillDate": invest_bill_date
            })
            
            if existing_record:
                # Update existing record instead of creating new one
                # Convert `item` to a JSON string if it exists
                if "item" in data:
                    data["item"] = json.dumps(data["item"])
                
                # Keep the original investBillNo
                invest_bill_no = existing_record["investBillNo"]
                
                # Update the existing record
                collection.update_one(
                    {"_id": existing_record["_id"]},
                    {"$set": data}
                )
                
                client.close()
                return JsonResponse({"message": "Billing updated successfully!", "investBillNo": invest_bill_no}, status=200)
        
        # If no existing record was found, create a new one
        # Get the current date to determine the financial year
        today = datetime.today()
        current_year = today.year
        next_year = current_year + 1

        # Check if we are in the previous financial year
        if today.month < 4:  # If it's Jan, Feb, or March
            financial_year = f"{(current_year-1) % 100}{current_year % 100}"
        else:  # If it's April or later
            financial_year = f"{current_year % 100}{next_year % 100}"

        # Find the latest bill number for the current financial year
        last_bill = collection.find_one(
            {"investBillNo": {"$regex": f"^{financial_year}/"}},
            sort=[("investBillNo", -1)]
        )

        if last_bill:
            try:
                last_number = int(last_bill["investBillNo"].split("/")[-1])  # Extract numeric part
            except ValueError:
                last_number = 0  # Fallback if extraction fails
            next_number = last_number + 1
        else:
            next_number = 1  # Start from 000001 if no previous bill exists

        # Format the new bill number as "2526/000001"
        invest_bill_no = f"{financial_year[-4:]}/{next_number:06d}"

        # Convert `item` to a JSON string
        if "item" in data:
            data["item"] = json.dumps(data["item"])  # Convert list to JSON string

        # Add the new investBillNo to the data
        data["investBillNo"] = invest_bill_no

        # Insert the data into the appropriate collection
        collection.insert_one(data)

        # Close the MongoDB connection
        client.close()

        return JsonResponse({"message": "Billing saved successfully!", "investBillNo": invest_bill_no}, status=201)

    except Exception as e:
        return JsonResponse({"error": "An error occurred while saving billing data", "details": str(e)}, status=500)

from django.http import JsonResponse
from pymongo import MongoClient
from datetime import datetime
import json  # Import JSON library to parse the string
from rest_framework.decorators import api_view

@api_view(['GET'])
def billing_report_view(request):
    try:
        # Connect to MongoDB
        client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
        db = client['ShanmugaHospital']

        # Define bill types (collection names)
        bill_types = ['CT Scan', 'Lab Test', 'Scanning', 'X-Ray']  # Add all your bill types here

        # Optional filtering (e.g., by date range)
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        result = []

        for bill_type in bill_types:
            collection = db[bill_type]
            query = {}

            # Apply date range filtering if provided
            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, "%Y-%m-%d")
                    end = datetime.strptime(end_date, "%Y-%m-%d")
                    query["billDate"] = {"$gte": start, "$lte": end}
                except ValueError:
                    return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

            # Fetch data from the collection
            data = list(collection.find(query))
            for doc in data:
                doc["_id"] = str(doc["_id"])  # Convert ObjectId to string
                doc["billType"] = bill_type   # Add billType field for clarity

                # Check if 'item' is a JSON string and convert it into an array
                if isinstance(doc.get("item"), str):
                    try:
                        doc["item"] = json.loads(doc["item"])  # Convert string to list (if it's a valid JSON string)
                    except json.JSONDecodeError:
                        doc["item"] = []  # If it's not a valid JSON string, default to empty list

            result.extend(data)

        client.close()

        # Sort the combined result by billDate (if available)
        result.sort(key=lambda x: x.get("billDate", ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse({"error": "Failed to generate billing report", "details": str(e)}, status=500)


from bson import ObjectId
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['DELETE'])
@csrf_exempt
def delete_bill_view(request):
    try:
        bill_id = request.data.get('billId')
        bill_type = request.data.get('billType')

        if not bill_id or not bill_type:
            return JsonResponse({'error': 'Missing billId or billType'}, status=400)

        client = MongoClient('mongodb+srv://shanmugainnovations:smrft%402024@cluster0.fgdtg.mongodb.net/')
        db = client['ShanmugaHospital']
        collection = db[bill_type]
        recycle_collection = db['RecycleBin']

        # Find the bill
        bill = collection.find_one({"_id": ObjectId(bill_id)})
        if not bill:
            return JsonResponse({'error': 'Bill not found'}, status=404)

        # Insert into RecycleBin
        bill['deletedAt'] = datetime.now()
        recycle_collection.insert_one(bill)

        # Delete from original collection
        collection.delete_one({"_id": ObjectId(bill_id)})

        client.close()
        return JsonResponse({'message': 'Bill deleted and moved to recycle bin'}, status=200)

    except Exception as e:
        return JsonResponse({'error': 'Failed to delete bill', 'details': str(e)}, status=500)

from django.http import JsonResponse
from .models import CTReport, MRIReport, USGReport, XRayReport
from django.views.decorators.http import require_http_methods
import logging

logger = logging.getLogger(__name__)

@require_http_methods(["GET"])
def get_patient_investigations(request, ip_no):
    """
    Fetch all investigation reports (CT, MRI, USG, XRay) for a specific patient IP number
    """
    if not ip_no:
        return JsonResponse({'error': 'Patient IP number is required'}, status=400)
    
    try:
        # IMPORTANT CHANGE: Removed the approve=True filter to show all reports
        ct_reports = CTReport.objects.filter(patientId=ip_no).values(
            'investigation', 'impression', 'approve'
        )
        
        mri_reports = MRIReport.objects.filter(patientId=ip_no).values(
            'investigation', 'impression', 'approve'
        )
        
        usg_reports = USGReport.objects.filter(patientId=ip_no).values(
            'investigation', 'impression', 'approve'
        )
        
        xray_reports = XRayReport.objects.filter(patientId=ip_no).values(
            'investigation', 'impression', 'approve'
        )
        
        # Combine all reports with type information
        all_reports = []
        
        for report in ct_reports:
            all_reports.append({
                'reportType': 'CT Scan',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'approve': report.get('approve', True)  # Include approval status
            })
            
        for report in mri_reports:
            all_reports.append({
                'reportType': 'MRI',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'approve': report.get('approve', True)
            })
            
        for report in usg_reports:
            all_reports.append({
                'reportType': 'USG',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'approve': report.get('approve', True)
            })
            
        for report in xray_reports:
            all_reports.append({
                'reportType': 'X-Ray',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'approve': report.get('approve', True)
            })
        
        # If no reports found, return empty list with 200 status
        if not all_reports:
            logger.info(f"No investigation reports found for patient IP: {ip_no}")
            return JsonResponse([], safe=False)
        
        logger.info(f"Found {len(all_reports)} reports for patient IP: {ip_no}")
        return JsonResponse(all_reports, safe=False)
        
    except Exception as e:
        logger.error(f"Error fetching patient investigations for IP {ip_no}: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch investigations'}, status=500)
    

from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import ReferenceDoctor
from .serializers import ReferenceDoctorSerializer

# ✅ Save Reference Doctor (POST)
@api_view(['POST'])
def save_reference_doctor(request):
    serializer = ReferenceDoctorSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"message": "Reference doctor saved successfully!"}, status=201)
    return Response(serializer.errors, status=400)

# ✅ Get All Reference Doctors (GET)
@api_view(['GET'])
def get_reference_doctors(request):
    doctors = ReferenceDoctor.objects.all()
    serializer = ReferenceDoctorSerializer(doctors, many=True)
    return Response(serializer.data, status=200)