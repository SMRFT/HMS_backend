import os, sys, django
sys.path.insert(0, r'D:\Parthi\HMS\HMS_backend')
from dotenv import load_dotenv
load_dotenv(r'D:\Parthi\HMS\HMS_backend\.env', override=True)
env = os.getenv('ENV_CLASSIFICATION', 'test')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', f'shanmugahospital_backend.settings-{env}' if env in ['prod', 'test'] else 'shanmugahospital_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views.NursingStation import get_medicine_ward_requests
from hospital.Views import NursingStation as NS
import json

factory = APIRequestFactory()
request = factory.get('/get_medicine_ward_requests/?uhid=S024/005189&ipNumber=S026/008310')

# Temporarily mock permissions
orig_perm = NS.HasRoleAndDataPermission.has_permission
NS.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

try:
    response = get_medicine_ward_requests(request)
    data = response.data.get('data', [])
    for d in data:
        if d.get('request_no') == 'MRIP128' or d.get('bill_no') == 'MRIP128':
            print("MRIP128 API DATA:")
            print(json.dumps(d, indent=2))
finally:
    NS.HasRoleAndDataPermission.has_permission = orig_perm
