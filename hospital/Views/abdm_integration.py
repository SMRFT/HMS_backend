import requests
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

BASE_URL = "https://dev.abdm.gov.in/gateway"

def get_session_token(client_id, client_secret):
    url = f"{BASE_URL}/v0.5/sessions"
    payload = {
        "clientId": client_id,
        "clientSecret": client_secret
    }
    headers = {
        "Content-Type": "application/json"
    }
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return True, data.get("accessToken"), None
    return False, None, response.json() if response.text else "Failed to get token"

@api_view(['POST'])
@permission_classes([AllowAny]) # Change this to appropriate permission later if needed
def update_bridge_url_api(request):
    try:
        data = request.data
        client_id = data.get('clientId')
        client_secret = data.get('clientSecret')
        bridge_url = data.get('bridgeUrl')
        
        if not all([client_id, client_secret, bridge_url]):
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)
            
        success, token, err = get_session_token(client_id, client_secret)
        if not success:
            return Response({"error": "Failed to get session token", "details": err}, status=status.HTTP_401_UNAUTHORIZED)
            
        url = f"{BASE_URL}/v1/bridges"
        payload = {"url": bridge_url}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "accept": "*/*"
        }
        
        response = requests.patch(url, json=payload, headers=headers)
        
        if response.status_code in [200, 201, 204]:
            return Response({"message": "Bridge URL updated successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Failed to update bridge URL", "details": response.json() if response.text else "Unknown error"}, status=response.status_code)
            
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def add_service_api(request):
    try:
        data = request.data
        client_id = data.get('clientId')
        client_secret = data.get('clientSecret')
        service_id = data.get('serviceId')
        bridge_url = data.get('bridgeUrl')
        
        if not all([client_id, client_secret, service_id, bridge_url]):
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)
            
        success, token, err = get_session_token(client_id, client_secret)
        if not success:
            return Response({"error": "Failed to get session token", "details": err}, status=status.HTTP_401_UNAUTHORIZED)
            
        url = f"{BASE_URL}/v1/bridges/addUpdateServices"
        payload = [
            {
                "id": service_id,
                "name": "BRIDGE-TEST-HIP",
                "type": "HIP",
                "active": True,
                "alias": ["allias-name"],
                "endpoints": [
                    {
                        "address": bridge_url,
                        "connectionType": "https",
                        "use": "registration"
                    }
                ]
            }
        ]
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "accept": "*/*"
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code in [200, 201, 204]:
            return Response({"message": "Service added/updated successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Failed to add/update service", "details": response.json() if response.text else "Unknown error"}, status=response.status_code)
            
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def get_services_api(request):
    try:
        data = request.data
        client_id = data.get('clientId')
        client_secret = data.get('clientSecret')
        
        if not all([client_id, client_secret]):
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)
            
        success, token, err = get_session_token(client_id, client_secret)
        if not success:
            return Response({"error": "Failed to get session token", "details": err}, status=status.HTTP_401_UNAUTHORIZED)
            
        url = f"{BASE_URL}/v1/bridges/getServices"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return Response({"message": "Services fetched successfully", "data": response.json()}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Failed to fetch services", "details": response.json() if response.text else "Unknown error"}, status=response.status_code)
            
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
