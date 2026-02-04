from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission
from ..models import IPGRN, OPGRN
from ..serializers import IPGRNSerializer, OPGRNSerializer
from pymongo import MongoClient
import os
from bson import ObjectId
import json

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def ip_grn_view(request, pk=None):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_ipgrn

        if request.method == 'POST':
            data = request.data.copy()
            employee_id = request.data.get('auth-user-id', 'system')
            
            # Complex fields as strings if they are objects/arrays
            if isinstance(data.get('items'), (list, dict)):
                data['items'] = json.dumps(data['items'])
            if isinstance(data.get('payment_status'), (list, dict)):
                data['payment_status'] = json.dumps(data['payment_status'])
            
            data["created_by"] = employee_id
            data["lastmodified_by"] = employee_id
            data["is_active"] = True

            serializer = IPGRNSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                    if not doc:
                        doc = collection.find_one({"grn_number": pk, "is_active": True})
                    
                    if not doc:
                        return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    doc['id'] = str(doc['_id'])
                    del doc['_id']
                    return Response(doc)
                except Exception as e:
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                grns = list(collection.find({"is_active": True}).sort("created_date", -1))
                for grn in grns:
                    grn['id'] = str(grn['_id'])
                    del grn['_id']
                return Response(grns)

        elif request.method == 'PATCH':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                grn = IPGRN.objects.get(pk=pk)
                data = request.data.copy()
                
                if isinstance(data.get('items'), (list, dict)):
                    data['items'] = json.dumps(data['items'])
                if isinstance(data.get('payment_status'), (list, dict)):
                    data['payment_status'] = json.dumps(data['payment_status'])
                
                data["lastmodified_by"] = request.data.get('auth-user-id', 'system')
                
                serializer = IPGRNSerializer(grn, data=data, partial=True)
                if serializer.is_valid():
                    serializer.save()
                    return Response(serializer.data)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except IPGRN.DoesNotExist:
                return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            result = collection.update_one({"_id": ObjectId(pk)}, {"$set": {"is_active": False}})
            if result.matched_count == 0:
                result = collection.update_one({"grn_number": pk}, {"$set": {"is_active": False}})
                
            if result.matched_count == 0:
                return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": "GRN deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def op_grn_view(request, pk=None):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_opgrn

        if request.method == 'POST':
            data = request.data.copy()
            employee_id = request.data.get('auth-user-id', 'system')
            
            if isinstance(data.get('items'), (list, dict)):
                data['items'] = json.dumps(data['items'])
            if isinstance(data.get('payment_status'), (list, dict)):
                data['payment_status'] = json.dumps(data['payment_status'])
            
            data["created_by"] = employee_id
            data["lastmodified_by"] = employee_id
            data["is_active"] = True

            serializer = OPGRNSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                    if not doc:
                        doc = collection.find_one({"grn_number": pk, "is_active": True})
                    
                    if not doc:
                        return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    doc['id'] = str(doc['_id'])
                    del doc['_id']
                    return Response(doc)
                except Exception as e:
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                grns = list(collection.find({"is_active": True}).sort("created_date", -1))
                for grn in grns:
                    grn['id'] = str(grn['_id'])
                    del grn['_id']
                return Response(grns)

        elif request.method == 'PATCH':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                grn = OPGRN.objects.get(pk=pk)
                data = request.data.copy()
                
                if isinstance(data.get('items'), (list, dict)):
                    data['items'] = json.dumps(data['items'])
                if isinstance(data.get('payment_status'), (list, dict)):
                    data['payment_status'] = json.dumps(data['payment_status'])
                
                data["lastmodified_by"] = request.data.get('auth-user-id', 'system')
                
                serializer = OPGRNSerializer(grn, data=data, partial=True)
                if serializer.is_valid():
                    serializer.save()
                    return Response(serializer.data)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except OPGRN.DoesNotExist:
                return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            result = collection.update_one({"_id": ObjectId(pk)}, {"$set": {"is_active": False}})
            if result.matched_count == 0:
                result = collection.update_one({"grn_number": pk}, {"$set": {"is_active": False}})
                
            if result.matched_count == 0:
                return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": "GRN deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
