import requests
cert_url = "https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate"
response = requests.get(cert_url)
print("Status:", response.status_code)
print("Content:", response.text[:200])
