import requests
import uuid
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .abdm_integration import get_session_token, BASE_URL
from ..models import ABHAProfile
from ..serializers import ABHAProfileSerializer

import base64
import uuid
import json
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import load_pem_public_key

def encrypt_with_abdm_public_key(text, token):
    try:
        cert_url = "https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate"
        headers = {
            "Authorization": f"Bearer {token}",
            "REQUEST-ID": str(uuid.uuid4()),
            "TIMESTAMP": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        }
        cert_response = requests.get(cert_url, headers=headers)
        if cert_response.status_code == 200:
            cert_json = cert_response.json()
            pub_key_base64 = cert_json.get("publicKey", "")
            
            # Format as PEM
            pem_string = f"-----BEGIN PUBLIC KEY-----\n{pub_key_base64}\n-----END PUBLIC KEY-----"
            
            public_key = load_pem_public_key(pem_string.encode('utf-8'))
            encrypted = public_key.encrypt(
                text.encode('utf-8'),
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA1()),
                    algorithm=hashes.SHA1(),
                    label=None
                )
            )
            return base64.b64encode(encrypted).decode('utf-8')
    except Exception as e:
        print("Encryption error:", e)
    return text

@api_view(['POST'])
@permission_classes([AllowAny])
def generate_otp_api(request):
    try:
        data = request.data
        client_id = data.get('clientId', 'SBXID_057691')
        client_secret = data.get('clientSecret', 'b195cb4f-4f69-4355-b60e-d0de26ad5008')
        aadhaar = data.get('aadhaar')
        
        if not aadhaar:
            return Response({"error": "Aadhaar number is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        success, token, err = get_session_token(client_id, client_secret)
        if not success:
            return Response({"error": "Failed to get session token", "details": err}, status=status.HTTP_401_UNAUTHORIZED)
            
        url = "https://abhasbx.abdm.gov.in/abha/api/v3/enrollment/request/otp"
        payload = {
            "scope": ["abha-enrol"],
            "loginHint": "aadhaar",
            "loginId": encrypt_with_abdm_public_key(aadhaar, token),
            "otpSystem": "aadhaar"
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "REQUEST-ID": str(uuid.uuid4()),
            "TIMESTAMP": "2023-11-20T12:00:00Z" # Dummy timestamp format, ABDM expects ISO
        }
        from datetime import datetime, timezone
        headers["TIMESTAMP"] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            return Response(response.json(), status=status.HTTP_200_OK)
        else:
            return Response({"error": "Failed to generate OTP", "details": response.json() if response.text else "Unknown error"}, status=response.status_code)
            
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp_api(request):
    try:
        data = request.data
        client_id = data.get('clientId', 'SBXID_057691')
        client_secret = data.get('clientSecret', 'b195cb4f-4f69-4355-b60e-d0de26ad5008')
        otp = data.get('otp')
        txn_id = data.get('txnId')
        mobile = data.get('mobile')
        
        if not all([otp, txn_id]):
            return Response({"error": "OTP and txnId are required"}, status=status.HTTP_400_BAD_REQUEST)
            
        success, token, err = get_session_token(client_id, client_secret)
        if not success:
            return Response({"error": "Failed to get session token", "details": err}, status=status.HTTP_401_UNAUTHORIZED)
            
        url = "https://abhasbx.abdm.gov.in/abha/api/v3/enrollment/enrol/byAadhaar"
        payload = {
            "authData": {
                "authMethods": ["otp"],
                "otp": {
                    "txnId": txn_id,
                    "otpValue": encrypt_with_abdm_public_key(otp, token)
                }
            },
            "consent": {
                "code": "abha-enrollment",
                "version": "1.4"
            }
        }
        if mobile:
            payload["authData"]["otp"]["mobile"] = mobile

        from datetime import datetime, timezone
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "REQUEST-ID": str(uuid.uuid4()),
            "TIMESTAMP": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "T-TOKEN": txn_id
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            resp_data = response.json()
            profile = resp_data.get('ABHAProfile', {})
            abha_number = profile.get('ABHANumber')
            if abha_number:
                # Save to database
                defaults = {
                    'first_name': profile.get('firstName'),
                    'last_name': profile.get('lastName'),
                    'dob': profile.get('dob'),
                    'gender': profile.get('gender'),
                    'abha_address': profile.get('preferredAddress') or (profile.get('phrAddress')[0] if isinstance(profile.get('phrAddress'), list) and profile.get('phrAddress') else None) or profile.get('address'),
                    'abha_mobile': profile.get('mobile'),
                    'abha_photo': profile.get('photo'),
                    'abha_status': profile.get('abhaStatus'),
                    'abha_type': profile.get('abhaType'),
                    'abha_district_name': profile.get('districtName'),
                    'abha_state_name': profile.get('stateName'),
                    'abha_pincode': profile.get('pinCode') or profile.get('pincode'),
                    'abha_full_address': profile.get('address')
                }
                ABHAProfile.objects.update_or_create(abha_number=abha_number, defaults=defaults)
            return Response(resp_data, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Failed to verify OTP", "details": response.json() if response.text else "Unknown error"}, status=response.status_code)
            
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def abha_profile_list_api(request):
    try:
        profiles = ABHAProfile.objects.all().order_by('-id')
        serializer = ABHAProfileSerializer(profiles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
