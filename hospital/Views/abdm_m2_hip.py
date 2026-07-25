import requests
import uuid
from datetime import datetime, timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from .abdm_integration import get_session_token, BASE_URL
from ..models import Patient

def call_gateway(endpoint, payload, token):
    url = f"{BASE_URL}/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-CM-ID": "sbx"
    }
    response = requests.post(url, json=payload, headers=headers)
    return response

@api_view(['POST'])
@permission_classes([AllowAny])
def discover_care_contexts(request):
    try:
        data = request.data
        req_id = data.get('requestId')
        transaction_id = data.get('transactionId')
        patient_data = data.get('patient', {})
        
        client_id = "SBXID_057691"
        client_secret = "b195cb4f-4f69-4355-b60e-d0de26ad5008"
        success, token, err = get_session_token(client_id, client_secret)
        
        if not success:
            return Response({"error": "Failed to get token"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        payload = {
            "requestId": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "transactionId": transaction_id,
            "patient": {
                "referenceNumber": "HOSP_PATIENT_1",
                "display": patient_data.get('name', 'John Doe'),
                "careContexts": [
                    {
                        "referenceNumber": "VISIT_01",
                        "display": "OPD Visit - General Medicine"
                    }
                ],
                "matchedBy": [
                    "MOBILE"
                ]
            },
            "resp": {
                "requestId": req_id
            }
        }
        
        call_gateway("v0.5/care-contexts/on-discover", payload, token)
        return Response(status=status.HTTP_202_ACCEPTED)
        
    except Exception as e:
        print(f"Error in discover: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def link_init(request):
    try:
        data = request.data
        req_id = data.get('requestId')
        transaction_id = data.get('transactionId')
        
        client_id = "SBXID_057691"
        client_secret = "b195cb4f-4f69-4355-b60e-d0de26ad5008"
        success, token, err = get_session_token(client_id, client_secret)
        
        reference_number = str(uuid.uuid4())
        
        payload = {
            "requestId": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "transactionId": transaction_id,
            "link": {
                "referenceNumber": reference_number,
                "authenticationType": "DIRECT",
                "meta": {
                    "communicationMedium": "MOBILE",
                    "communicationHint": "string",
                    "communicationExpiry": "2026-12-31T12:00:00.000Z"
                }
            },
            "resp": {
                "requestId": req_id
            }
        }
        call_gateway("v0.5/links/link/on-init", payload, token)
        return Response(status=status.HTTP_202_ACCEPTED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def link_confirm(request):
    try:
        data = request.data
        req_id = data.get('requestId')
        
        client_id = "SBXID_057691"
        client_secret = "b195cb4f-4f69-4355-b60e-d0de26ad5008"
        success, token, err = get_session_token(client_id, client_secret)
        
        patient_ref = "HOSP_PATIENT_1"
        
        payload = {
            "requestId": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "patient": {
                "referenceNumber": patient_ref,
                "display": "John Doe",
                "careContexts": [
                    {
                        "referenceNumber": "VISIT_01",
                        "display": "OPD Visit - General Medicine"
                    }
                ]
            },
            "resp": {
                "requestId": req_id
            }
        }
        
        call_gateway("v0.5/links/link/on-confirm", payload, token)
        return Response(status=status.HTTP_202_ACCEPTED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
