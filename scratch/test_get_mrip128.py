import os
import sys
import django

sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views.NursingStation import get_medicine_ward_requests
from hospital.Views import NursingStation as ns_module

old_check = ns_module.HasRoleAndDataPermission.has_permission
ns_module.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

factory = APIRequestFactory()
request = factory.get('/get_medicine_ward_requests/?uhid=S024/005189&ipNumber=S026/008310')

try:
    response = get_medicine_ward_requests(request)
    print("Status code:", response.status_code)
    data = response.data.get("data", [])
    print(f"Total requests returned: {len(data)}")
    for r in data:
        req_or_bill = r.get("request_no") or r.get("bill_no") or r.get("id")
        if "128" in str(req_or_bill) or r.get("request_no") == "MRIP128":
            print(f"--> FOUND MRIP128: id={r.get('id')}, bill_no={r.get('bill_no')}, request_no={r.get('request_no')}, status='{r.get('status')}', billing_status='{r.get('billing_status')}'")
finally:
    ns_module.HasRoleAndDataPermission.has_permission = old_check
