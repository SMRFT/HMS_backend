import requests
import os
import django

# Setup django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'HMS_backend.settings')
django.setup()

from hospital.Views.abdm_integration import get_session_token
from cryptography.hazmat.primitives.serialization import load_pem_public_key

client_id = 'SBXID_057691'
client_secret = 'b195cb4f-4f69-4355-b60e-d0de26ad5008'
success, token, err = get_session_token(client_id, client_secret)
if success:
    cert_url = "https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(cert_url, headers=headers)
    print("Cert status:", resp.status_code)
    cert_text = resp.text
    print("Cert text:", cert_text[:100])
    try:
        public_key = load_pem_public_key(cert_text.encode('utf-8'))
        print("Successfully loaded PEM")
    except Exception as e:
        print("Failed to load PEM:", e)
else:
    print("Token failed")
