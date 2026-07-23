import requests
import uuid
from datetime import datetime, timezone

client_id = 'SBXID_057691'
client_secret = 'b195cb4f-4f69-4355-b60e-d0de26ad5008'
resp = requests.post("https://dev.abdm.gov.in/gateway/v0.5/sessions", json={"clientId": client_id, "clientSecret": client_secret})
token = resp.json().get("accessToken")

cert_url = "https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate"
headers = {
    "Authorization": f"Bearer {token}",
    "REQUEST-ID": str(uuid.uuid4()),
    "TIMESTAMP": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
}
resp = requests.get(cert_url, headers=headers)
print("Cert status:", resp.status_code)
cert_text = resp.text
print("Cert text:\n", cert_text[:300])

from cryptography.hazmat.primitives.serialization import load_pem_public_key
try:
    public_key = load_pem_public_key(cert_text.encode('utf-8'))
    print("Successfully loaded PEM")
except Exception as e:
    print("Failed to load PEM:", e)
