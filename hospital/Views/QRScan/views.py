from datetime import datetime, timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt

from .models import InPatientFeedback, OutPatientFeedback
from .serializer import InPatientFeedbackSerializer, OutPatientFeedbackSerializer


@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def inpatient_feedback_list_create(request):
    """
    API view for submitting and retrieving InPatient Feedback records using Serializer and ORM Model.
    """
    if request.method == 'GET':
        queryset = InPatientFeedback.objects.all().order_by('-created_date')
        
        ip_number = request.query_params.get('ip_number', '').strip()
        patient_name = request.query_params.get('patient_name', '').strip()
        feedback_type = request.query_params.get('feedback_type', '').strip()
        doctor_name = request.query_params.get('doctor_name', '').strip()
        category = request.query_params.get('category', '').strip()
        date_param = request.query_params.get('date', '').strip()
        
        if ip_number:
            queryset = queryset.filter(ip_number__icontains=ip_number)
        if patient_name:
            queryset = queryset.filter(patient_name__icontains=patient_name)
        if feedback_type:
            queryset = queryset.filter(feedback_type__icontains=feedback_type)
        if doctor_name:
            queryset = queryset.filter(doctor_name__icontains=doctor_name)
        if category:
            queryset = queryset.filter(category__icontains=category)
        if date_param:
            try:
                start_dt = datetime.strptime(date_param, "%Y-%m-%d")
                end_dt = start_dt + timedelta(days=1)
                queryset = queryset.filter(
                    created_date__gte=start_dt,
                    created_date__lt=end_dt
                )
            except Exception:
                pass

            
        serializer = InPatientFeedbackSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        serializer = InPatientFeedbackSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "Feedback submitted successfully",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['GET', 'DELETE'])
@permission_classes([AllowAny])
def inpatient_feedback_detail(request, feedback_id):
    """
    Retrieve or delete a single feedback entry using Serializer and ORM Model.
    """
    try:
        feedback = InPatientFeedback.objects.get(pk=feedback_id)
    except InPatientFeedback.DoesNotExist:
        return Response({"error": "Feedback record not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = InPatientFeedbackSerializer(feedback)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'DELETE':
        feedback.delete()
        return Response({"message": "Feedback deleted successfully"}, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def outpatient_feedback_list_create(request):
    """
    API view for submitting and retrieving OutPatient Feedback records using Serializer and ORM Model.
    """
    if request.method == 'GET':
        queryset = OutPatientFeedback.objects.all().order_by('-created_date')
        
        op_number = request.query_params.get('op_number', '').strip()
        patient_name = request.query_params.get('patient_name', '').strip()
        doctor_name = request.query_params.get('doctor_name', '').strip()
        category = request.query_params.get('category', '').strip()
        date_param = request.query_params.get('date', '').strip()
        
        if op_number:
            queryset = queryset.filter(op_number__icontains=op_number)
        if patient_name:
            queryset = queryset.filter(patient_name__icontains=patient_name)
        if doctor_name:
            queryset = queryset.filter(doctor_name__icontains=doctor_name)
        if category:
            queryset = queryset.filter(category__icontains=category)
        if date_param:
            try:
                start_dt = datetime.strptime(date_param, "%Y-%m-%d")
                end_dt = start_dt + timedelta(days=1)
                queryset = queryset.filter(
                    created_date__gte=start_dt,
                    created_date__lt=end_dt
                )
            except Exception:
                pass
            
        serializer = OutPatientFeedbackSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        serializer = OutPatientFeedbackSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "OutPatient feedback submitted successfully",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['GET', 'DELETE'])
@permission_classes([AllowAny])
def outpatient_feedback_detail(request, feedback_id):
    """
    Retrieve or delete a single outpatient feedback entry.
    """
    try:
        feedback = OutPatientFeedback.objects.get(pk=feedback_id)
    except OutPatientFeedback.DoesNotExist:
        return Response({"error": "Feedback record not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = OutPatientFeedbackSerializer(feedback)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'DELETE':
        feedback.delete()
        return Response({"message": "Feedback deleted successfully"}, status=status.HTTP_200_OK)

