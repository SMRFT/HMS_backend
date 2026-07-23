import requests
import json
import sys

CLIENT_ID = "SBXID_057691"
CLIENT_SECRET = "b195cb4f-4f69-4355-b60e-d0de26ad5008"
BASE_URL = "https://dev.abdm.gov.in/gateway"

def get_session_token():
    print("Getting session token...")
    url = f"{BASE_URL}/v0.5/sessions"
    payload = {
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET
    }
    headers = {
        "Content-Type": "application/json"
    }
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        data = response.json()
        print("Successfully retrieved access token.")
        return data.get("accessToken")
    else:
        print(f"Failed to get token: {response.status_code} - {response.text}")
        sys.exit(1)

def update_bridge_url(token, bridge_url):
    print(f"\nUpdating bridge URL to {bridge_url}...")
    url = f"{BASE_URL}/v1/bridges"
    payload = {
        "url": bridge_url
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "accept": "*/*"
    }
    response = requests.patch(url, json=payload, headers=headers)
    if response.status_code in [200, 201, 204]:
        print("Bridge URL updated successfully.")
    else:
        print(f"Failed to update bridge URL: {response.status_code} - {response.text}")

def add_update_services(token, service_id, bridge_url):
    print(f"\nAdding/Updating service (HIP) with ID {service_id}...")
    url = f"{BASE_URL}/v1/bridges/addUpdateServices"
    payload = [
        {
            "id": service_id,
            "name": "BRIDGE-TEST-HIP",
            "type": "HIP", # Changed from HEALTH_LOCKER to HIP based on user instructions "Add the services(HIP)"
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
    if response.status_code in [200, 201]:
        print("Service added/updated successfully.")
    else:
        print(f"Failed to add/update service: {response.status_code} - {response.text}")

def get_services(token):
    print("\nFetching added services...")
    url = f"{BASE_URL}/v1/bridges/getServices"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("Successfully fetched services:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Failed to fetch services: {response.status_code} - {response.text}")

if __name__ == "__main__":
    # You can change this URL to your actual webhook or server endpoint
    MY_BRIDGE_URL = "https://webhook.site/b195cb4f-4f69-4355-b60e-d0de26ad5008" # Using a webhook for testing
    MY_SERVICE_ID = "HMS_HIP_SERVICE_001"
    
    token = get_session_token()
    if token:
        update_bridge_url(token, MY_BRIDGE_URL)
        add_update_services(token, MY_SERVICE_ID, MY_BRIDGE_URL)
        get_services(token)
