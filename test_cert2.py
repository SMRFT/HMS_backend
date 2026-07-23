import requests
import json
from hospital.Views.abdm_integration import get_session_token

client_id = 'SBXID_057691'
client_secret = 'b195cb4f-4f69-4355-b60e-d0de26ad5008'
success, token, err = get_session_token(client_id, client_secret)
if success:
    cert_url = "https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(cert_url, headers=headers)
    print("Cert status:", resp.status_code)
    print("Cert text:", resp.text[:100])
else:
    print("Token failed")
