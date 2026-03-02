from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from ..models import InsuranceProvider
from ..serializers import InsuranceProviderSerializer

@api_view(['GET', 'POST'])
def insurance_provider_list_create(request):
    if request.method == 'GET':
        providers = InsuranceProvider.objects.all().order_by('company_name')
        serializer = InsuranceProviderSerializer(providers, many=True)
        return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)

    if request.method == 'POST':
        data = request.data.copy()
        if not data.get('company_code'):
            codes = InsuranceProvider.objects.values_list('company_code', flat=True)
            max_val = 0
            import re
            for c in codes:
                if c:
                    match = re.search(r'(\d+)$', c)
                    if match:
                        val = int(match.group(1))
                        if val > max_val:
                            max_val = val
            
            if max_val > 0:
                data['company_code'] = str(max_val + 1)
            else:
                data['company_code'] = "COMP001"

        serializer = InsuranceProviderSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({'success': True, 'data': serializer.data}, status=status.HTTP_201_CREATED)
        return Response({'success': False, 'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
def insurance_provider_detail(request, pk):
    try:
        provider = InsuranceProvider.objects.get(company_code=pk)
    except InsuranceProvider.DoesNotExist:
        try:
            from bson import ObjectId
            provider = InsuranceProvider.objects.get(pk=ObjectId(pk))
        except:
            return Response({'error': 'Provider not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = InsuranceProviderSerializer(provider)
        return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)

    if request.method == 'PUT':
        serializer = InsuranceProviderSerializer(provider, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)
        return Response({'success': False, 'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'DELETE':
        provider.delete()
        return Response({'success': True, 'message': 'Provider deleted successfully'}, status=status.HTTP_204_NO_CONTENT)
