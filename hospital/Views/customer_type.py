from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import CustomerType
from ..serializers import CustomerTypeSerializer

@api_view(['GET', 'POST'])
def customer_type_list(request):
    if request.method == 'GET':
        customer_types = CustomerType.objects.all()
        serializer = CustomerTypeSerializer(customer_types, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = CustomerTypeSerializer(data=request.data)
        if serializer.is_valid():
            # Extract audit info from request data (injected by apiRequest)
            employee_id = request.data.get('auth-user-id', 'system')
            hospital_code = request.data.get('auth-hospital-code', 'system')
            
            serializer.save(
                created_by=employee_id,
                hospital_code=hospital_code
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
def customer_type_detail(request, pk):
    try:
        customer_type = CustomerType.objects.get(pk=pk)
    except CustomerType.DoesNotExist:
        return Response({'message': 'Customer Type does not exist'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = CustomerTypeSerializer(customer_type)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = CustomerTypeSerializer(customer_type, data=request.data)
        if serializer.is_valid():
            # Extract audit info from request data (injected by apiRequest)
            employee_id = request.data.get('auth-user-id', 'system')
            serializer.save(lastmodified_by=employee_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        customer_type.delete()
        return Response({'message': 'Customer Type deleted successfully'}, status=status.HTTP_204_NO_CONTENT)
