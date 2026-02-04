from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
from pyauth.auth import HasRoleAndDataPermission
from ..models import IPPharmacyStock, OPPharmacyStock
from ..serializers import IPPharmacyStockSerializer, OPPharmacyStockSerializer
from pymongo import MongoClient
import os
from bson import ObjectId

# Helper to get next numerical ID
def get_next_stock_id(queryset, id_field):
    max_id = 0
    for obj in queryset:
        val = getattr(obj, id_field)
        if val and str(val).isdigit():
            max_id = max(max_id, int(val))
    return str(max_id + 1)

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def ip_pharmacy_stock_view(request, pk=None):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_ippharmacystock

        if request.method == 'POST':
            data = request.data.copy()
            employee_id = request.data.get('auth-user-id', 'system')
            
            data["ip_stock_id"] = get_next_stock_id(IPPharmacyStock.objects.all(), "ip_stock_id")
            data["created_by"] = employee_id
            data["lastmodified_by"] = employee_id
            data["is_active"] = True

            serializer = IPPharmacyStockSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                    if not doc:
                        doc = collection.find_one({"ip_stock_id": pk, "is_active": True})
                    
                    if not doc:
                        return Response({"error": "Stock not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    doc['id'] = str(doc['_id'])
                    del doc['_id']
                    return Response(doc)
                except Exception as e:
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                stocks = list(collection.find({"is_active": True}))
                for stock in stocks:
                    stock['id'] = str(stock['_id'])
                    del stock['_id']
                return Response(stocks)

        elif request.method == 'PATCH':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            employee_id = request.data.get('auth-user-id', 'system')
            update_data = request.data.copy()
            update_data["lastmodified_by"] = employee_id
            update_data["lastmodified_date"] = datetime.now()
            
            # Using MongoDB collection for direct update if preferred, or standard Django save
            # Let's stick to standard Django for consistency if possible, or direct MongoDB for complex objects
            try:
                stock = IPPharmacyStock.objects.get(pk=pk)
                serializer = IPPharmacyStockSerializer(stock, data=update_data, partial=True)
                if serializer.is_valid():
                    serializer.save()
                    return Response(serializer.data)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except IPPharmacyStock.DoesNotExist:
                return Response({"error": "Stock not found"}, status=status.HTTP_404_NOT_FOUND)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            result = collection.update_one({"_id": ObjectId(pk)}, {"$set": {"is_active": False}})
            if result.matched_count == 0:
                # Fallback for ip_stock_id if pk is not ObjectId
                result = collection.update_one({"ip_stock_id": pk}, {"$set": {"is_active": False}})
                
            if result.matched_count == 0:
                return Response({"error": "Stock not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": "Stock deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def op_pharmacy_stock_view(request, pk=None):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_oppharmacystock

        if request.method == 'POST':
            data = request.data.copy()
            employee_id = request.data.get('auth-user-id', 'system')
            
            data["op_stock_id"] = get_next_stock_id(OPPharmacyStock.objects.all(), "op_stock_id")
            data["created_by"] = employee_id
            data["lastmodified_by"] = employee_id
            data["is_active"] = True

            serializer = OPPharmacyStockSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                    if not doc:
                        doc = collection.find_one({"op_stock_id": pk, "is_active": True})
                    
                    if not doc:
                        return Response({"error": "Stock not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    doc['id'] = str(doc['_id'])
                    del doc['_id']
                    return Response(doc)
                except Exception as e:
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                stocks = list(collection.find({"is_active": True}))
                for stock in stocks:
                    stock['id'] = str(stock['_id'])
                    del stock['_id']
                return Response(stocks)

        elif request.method == 'PATCH':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            employee_id = request.data.get('auth-user-id', 'system')
            update_data = request.data.copy()
            update_data["lastmodified_by"] = employee_id
            update_data["lastmodified_date"] = datetime.now()
            
            try:
                stock = OPPharmacyStock.objects.get(pk=pk)
                serializer = OPPharmacyStockSerializer(stock, data=update_data, partial=True)
                if serializer.is_valid():
                    serializer.save()
                    return Response(serializer.data)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except OPPharmacyStock.DoesNotExist:
                return Response({"error": "Stock not found"}, status=status.HTTP_404_NOT_FOUND)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            result = collection.update_one({"_id": ObjectId(pk)}, {"$set": {"is_active": False}})
            if result.matched_count == 0:
                result = collection.update_one({"op_stock_id": pk}, {"$set": {"is_active": False}})
                
            if result.matched_count == 0:
                return Response({"error": "Stock not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": "Stock deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
