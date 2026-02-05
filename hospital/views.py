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





from .models import Summary
from .serializers import SummarySerializer

@api_view(['GET'])
def get_summaries(request):
    summaries = Summary.objects.all()
    serializer = SummarySerializer(summaries, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)




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

@api_view(['GET'])
def get_last_uhid(request):
    try:
        # Assuming typical Django auto-increment or similar logic, or explicit time field.
        # Since it's often user-provided or custom generated, we just want the latest record.
        # If using standard ID:
        last_patient = Patient.objects.all().order_by('-pk').first()
        if last_patient:
            return Response({"uhid": last_patient.uhid}, status=200)
        return Response({"uhid": "None"}, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)