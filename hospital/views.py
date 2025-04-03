from django.shortcuts import render
from rest_framework.decorators import api_view
from django.views.decorators.csrf import csrf_exempt
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128
import json

from .serializers import RegisterSerializer
@api_view(['POST'])
def register_user(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"message": "Registration successful!"}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from django.contrib.auth.hashers import check_password
from .models import Register,Patient
@api_view(['POST'])
def login_user(request):
    name = request.data.get('name')
    user_id = request.data.get('id')
    password = request.data.get('password')

    try:
        user = Register.objects.get(name=name, id=user_id)
        if check_password(password, user.password):  # Compare the hashed password
            return Response({"message": "Login successful!", "user": {"name": user.name, "id": user.id, "role": user.role}}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
    except Register.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    

from .serializers import PatientSerializer
@api_view(['GET', 'POST'])
@csrf_exempt
def patientCreateView(request):
    if request.method == 'GET':
        uhid = request.GET.get('uhid', None)
        ip_number = request.GET.get('ip_number', None)
        mobile = request.GET.get('mobile', None)
        # Filter based on given parameters
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
        serializer = PatientSerializer(data=request.data)
        if serializer.is_valid():
            patient = serializer.save()
            return Response({
                "message": "Patient registered successfully.",
                "uhid": patient.uhid,  # Include the generated UHID
                "patient": serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from .models import PharmacyStock
from .serializers import PharmacyStockSerializer
@api_view(['GET', 'POST'])
def create_stock_entry(request):
    if request.method == 'POST':
        # Handle POST request to create a stock entry
        serializer = PharmacyStockSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'GET':
        # Handle GET request to retrieve stock entries
        stocks = PharmacyStock.objects.all()
        serializer = PharmacyStockSerializer(stocks, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


from .models import HSNCode
from .serializers import HSNCodeSerializer
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
def hsn_code_list(request):
    # MongoDB connection
    client = MongoClient('mongodb://3.109.210.34:27017/')
    db = client.ShanmugaHospital
    collection = db.hospital_hsncode
    if request.method == 'GET':
        hsn_codes = HSNCode.objects.all()
        serializer = HSNCodeSerializer(hsn_codes, many=True)
        return Response(serializer.data)

    if request.method == 'POST':
        serializer = HSNCodeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # Update the PUT method in your view:
    if request.method == 'PUT':
        data = request.data
        hsn_code_value = data.get('hsn_code')

        if not hsn_code_value:
            return Response({'error': 'HSN Code is required'}, status=status.HTTP_400_BAD_REQUEST)

        print(f"Received hsn_code for update: {hsn_code_value}")  # Log hsn_code
        
        # Query MongoDB to update the existing document using hsn_code
        result = collection.update_one(
            {'hsn_code': hsn_code_value},  # Ensure the field hsn_code exists in the document
            {'$set': data}  # Update the matching document
        )

        print(f"Update result: {result.matched_count} matched, {result.modified_count} modified")

        if result.matched_count == 0:
            return Response({'error': 'HSN Code not found'}, status=status.HTTP_404_NOT_FOUND)

        updated_data = collection.find_one({'hsn_code': hsn_code_value})

        # Convert ObjectId to string to make it JSON serializable
        updated_data['_id'] = str(updated_data['_id'])

        return Response(updated_data, status=status.HTTP_200_OK)

    if request.method == 'DELETE':
        hsn_code_value = request.query_params.get('hsn_code')
        if not hsn_code_value:
            return Response({'error': 'HSN Code is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            hsn_code = HSNCode.objects.get(hsn_code=hsn_code_value)
        except HSNCode.DoesNotExist:
            return Response({'error': 'HSN Code not found'}, status=status.HTTP_404_NOT_FOUND)

        hsn_code.delete()  # Delete based on `_id`
        return Response({'message': 'Deleted successfully'}, status=status.HTTP_204_NO_CONTENT)
    

from .models import Ventor
from .serializers import VentorSerializer
@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
def ventor_list(request):
    try:
        ventor_name = request.query_params.get('ventor_name', None)  # Get `ventor_name` from query params
        if request.method == 'GET':
            if ventor_name:
                ventor = Ventor.objects.get(ventor_name=ventor_name)
                serializer = VentorSerializer(ventor)
                return Response(serializer.data)
            else:
                ventors = Ventor.objects.all()
                serializer = VentorSerializer(ventors, many=True)
                return Response(serializer.data)
        elif request.method == 'POST':
            serializer = VentorSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        elif request.method == 'PATCH':
            if not ventor_name:
                return Response({"error": "ventor_name parameter is required for update"}, status=status.HTTP_400_BAD_REQUEST)
            ventor = Ventor.objects.get(ventor_name=ventor_name)
            serializer = VentorSerializer(ventor, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        elif request.method == 'DELETE':
            if not ventor_name:
                return Response({"error": "ventor_name parameter is required for delete"}, status=status.HTTP_400_BAD_REQUEST)
            ventor = Ventor.objects.get(ventor_name=ventor_name)
            ventor.delete()
            return Response({"message": "Ventor deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
    except Ventor.DoesNotExist:
        return Response({"error": "Ventor not found"}, status=status.HTTP_404_NOT_FOUND)
    

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


@api_view(['GET'])
def doctor_list(request):
    doctors = Doctor.objects.all()
    serializer = DoctorSerializer(doctors, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


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
    client = MongoClient(f'mongodb://3.109.210.34:27017/')
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
    client = MongoClient(f'mongodb://3.109.210.34:27017/')
    db = client['ShanmugaHospital']
    collection = db['hospital_investigations']
    # Query MongoDB to get only investigations where "Type of Investigation" is "CT"
    investigations = list(collection.find({'Type of Investigation': 'CT'}, {'_id': 0}))  # Exclude _id field
    return JsonResponse(investigations, safe=False)


def get_patient_report(request, uhid, subUhid):
    # MongoDB connection setup
    client = MongoClient(f'mongodb://3.109.210.34:27017/')
    db = client['ShanmugaHospital']
    collection = db['hospital_investigations']
    # Combine uhid and subUhid to get the full UHID
    full_uhid = f'{uhid}/{subUhid}'
    
    # Fetch the document from MongoDB
    patient_details = collection.find_one({'UHID': full_uhid})

    # Check if patient_details exists and convert ObjectId fields to string
    if patient_details:
        # Convert ObjectId fields to string
        if '_id' in patient_details:
            patient_details['_id'] = str(patient_details['_id'])

        return JsonResponse(patient_details, safe=False)
    else:
        return JsonResponse({'error': 'Patient not found'}, status=404)
    

from .models import CTReport
from .serializers import CTReportSerializer
@api_view(['POST'])
def create_ct_report(request):
    if request.method == 'POST':
        serializer = CTReportSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(serializer.data, status=201)
        return JsonResponse(serializer.errors, status=400)

    
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
    

@csrf_exempt
def approve_ct_report(request, patient_id):
    # MongoDB connection setup
    client = MongoClient('mongodb://3.109.210.34:27017/')
    db = client['ShanmugaHospital']
    collection = db['hospital_ctreport']

    if request.method == 'PATCH':
        try:
            # Find the report by patientId
            report = collection.find_one({"patientId": patient_id})
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Update the approve field and approve_time
            update_result = collection.update_one(
                {"patientId": patient_id},
                {
                    "$set": {
                        "approve": True,
                        "approve_time": now().isoformat()  # Save as ISO format for consistency
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # Retrieve the updated report
            updated_report = collection.find_one({"patientId": patient_id})

            # Convert ObjectId to string for JSON serialization
            if '_id' in updated_report:
                updated_report['_id'] = str(updated_report['_id'])

            # Return the updated report
            return JsonResponse(updated_report, status=200, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


# View to list all MRI investigations
def get_mri_investigations(request):
    # MongoDB connection setup
    client = MongoClient(f'mongodb://3.109.210.34:27017/')
    db = client['ShanmugaHospital']
    collection = db['hospital_investigations']
    # Query MongoDB to get only investigations where "Type of Investigation" is "MRI"
    investigations = list(collection.find({'Type of Investigation': 'MRI'}, {'_id': 0}))  # Exclude _id field
    return JsonResponse(investigations, safe=False)


def get_mri_patient_report(request, uhid, subUhid):
    # MongoDB connection setup
    client = MongoClient(f'mongodb://3.109.210.34:27017/')
    db = client['ShanmugaHospital']
    collection = db['hospital_investigations']
    # Combine uhid and subUhid to get the full UHID
    full_uhid = f'{uhid}/{subUhid}'
    
    # Fetch the document from MongoDB
    patient_details = collection.find_one({'UHID': full_uhid})

    # Check if patient_details exists and convert ObjectId fields to string
    if patient_details:
        # Convert ObjectId fields to string
        if '_id' in patient_details:
            patient_details['_id'] = str(patient_details['_id'])

        return JsonResponse(patient_details, safe=False)
    else:
        return JsonResponse({'error': 'Patient not found'}, status=404)


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


@csrf_exempt
def approve_mri_report(request, patient_id):
    # MongoDB connection setup
    client = MongoClient('mongodb://3.109.210.34:27017/')
    db = client['ShanmugaHospital']
    collection = db['hospital_mrireport']  # Changed collection name to 'hospital_mrireport'

    if request.method == 'PATCH':
        try:
            # Find the report by patientId
            report = collection.find_one({"patientId": patient_id})
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)
            
            # Update the approve field and approve_time
            update_result = collection.update_one(
                {"patientId": patient_id},
                {
                    "$set": {
                        "approve": True,
                        "approve_time": now().isoformat()  # Save as ISO format for consistency
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # Retrieve the updated report
            updated_report = collection.find_one({"patientId": patient_id})

            # Convert ObjectId to string for JSON serialization
            if '_id' in updated_report:
                updated_report['_id'] = str(updated_report['_id'])

            # Return the updated report
            return JsonResponse(updated_report, status=200, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)
    

from .models import Admission
from .serializers import AdmissionSerializer
@api_view(['POST'])
def create_admission(request):
    parser_classes = (MultiPartParser, FormParser)
    serializer = AdmissionSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return JsonResponse({'message': 'Admission created successfully!'}, status=201)
    return JsonResponse(serializer.errors, status=400)


@api_view(['GET'])
def list_admissions(request):
    admissions = Admission.objects.all()
    serializer = AdmissionSerializer(admissions, many=True)
    return JsonResponse(serializer.data, safe=False)




from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
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
# MongoDB connection setup
client = MongoClient('mongodb://3.109.210.34:27017/')
db = client['ShanmugaHospital']
collection = db['hospital_summary']  # Changed collection name to 'hospital_summary'
@api_view(['PATCH'])
def approve_summary(request, ip_no):
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
    


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .serializers import qrscanSerializer
@api_view(['POST'])
@csrf_exempt
def qrsubmit_form(request):
    if request.method == 'POST':
        serializer = qrscanSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    




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

