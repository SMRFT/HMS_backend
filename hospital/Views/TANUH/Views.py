from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import BreastCancerScreening, StudentSurveyorRegistration
from .serializer import BreastCancerScreeningSerializer, StudentSurveyorRegistrationSerializer


# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission
from rest_framework.decorators import api_view, permission_classes

@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def tanuh_breast_cancer_screening(request):
    """
    GET  - List all breast cancer screening records.
    POST - Create a new breast cancer screening record.
    """
    try:
        if request.method == 'GET':
            if request.GET.get('action') == 'next_bill_no':
                return Response({'next_bill_number': BreastCancerScreening.generate_next_bill_number()}, status=status.HTTP_200_OK)
            records = BreastCancerScreening.objects.all().order_by('-date')
            serializer = BreastCancerScreeningSerializer(records, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
            employee_id = (
                data.get("auth-user-id")
                or request.headers.get("auth-user-id")
                or getattr(request.user, "username", "")
            )
            if employee_id:
                data['created_by'] = str(employee_id)
            data['created_date'] = timezone.now()

            # If bill_number is blank, let the model auto-generate it on save
            if not data.get('bill_number') or not str(data.get('bill_number')).strip():
                data.pop('bill_number', None)

            serializer = BreastCancerScreeningSerializer(data=data)
            if serializer.is_valid():
                instance = serializer.save()
                return Response(
                    {
                        'success': True,
                        'message': 'Screening record saved successfully',
                        'data': serializer.data
                    },
                    status=status.HTTP_201_CREATED
                )

            # Format serializer errors into a clear backend message
            error_list = []
            for field, errs in serializer.errors.items():
                if isinstance(errs, list):
                    clean_errs = [str(e) for e in errs]
                    error_list.append(f"{field}: {', '.join(clean_errs)}")
                elif isinstance(errs, dict):
                    error_list.append(f"{field}: {str(errs)}")
                else:
                    error_list.append(f"{field}: {str(errs)}")
            error_msg = "; ".join(error_list) if error_list else "Validation error occurred"

            return Response(
                {
                    'success': False,
                    'message': error_msg,
                    'error': error_msg,
                    'errors': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e) or "An internal server error occurred"
        return Response(
            {
                'success': False,
                'message': error_msg,
                'error': error_msg
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def tanuh_student_surveyor_registration(request):
    """
    GET  - List all student surveyor registration records.
    POST - Create a new student surveyor registration record (stored separately).
    """
    try:
        if request.method == 'GET':
            records = StudentSurveyorRegistration.objects.all().order_by('-created_date')
            serializer = StudentSurveyorRegistrationSerializer(records, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
            employee_id = (
                data.get("auth-user-id")
                or request.headers.get("auth-user-id")
                or getattr(request.user, "username", "")
            )
            if employee_id:
                data['created_by'] = str(employee_id)
            data['created_date'] = timezone.now()

            serializer = StudentSurveyorRegistrationSerializer(data=data)
            if serializer.is_valid():
                instance = serializer.save()
                return Response(
                    {
                        'success': True,
                        'message': 'Student Surveyor registered successfully',
                        'data': serializer.data
                    },
                    status=status.HTTP_201_CREATED
                )

            error_list = []
            for field, errs in serializer.errors.items():
                if isinstance(errs, list):
                    clean_errs = [str(e) for e in errs]
                    error_list.append(f"{field}: {', '.join(clean_errs)}")
                elif isinstance(errs, dict):
                    error_list.append(f"{field}: {str(errs)}")
                else:
                    error_list.append(f"{field}: {str(errs)}")
            error_msg = "; ".join(error_list) if error_list else "Validation error occurred"

            return Response(
                {
                    'success': False,
                    'message': error_msg,
                    'error': error_msg,
                    'errors': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e) or "An internal server error occurred"
        return Response(
            {
                'success': False,
                'message': error_msg,
                'error': error_msg
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
