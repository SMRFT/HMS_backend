import os
import sys
import django

sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views import NursingStation

factory = APIRequestFactory()
request = factory.get('/get_medicine_ward_requests/?uhid=S026/006687&ipNumber=S026/008383')

# Bypass permission check for local unit test
old_check_perms = NursingStation.HasRoleAndDataPermission.has_permission
NursingStation.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

try:
    response = NursingStation.get_medicine_ward_requests(request)
    data = response.data.get('data', [])

    print(f"Total requests returned: {len(data)}")
    for item in data:
        print(f"Req Date: {item.get('reqDate')} | Display Bill/Req No: {item.get('bill_no')} | Request No: {item.get('request_no')} | Billed No: {item.get('billed_bill_no')} | Status: {item.get('status')} | Converted: {item.get('is_converted')}")
finally:
    NursingStation.HasRoleAndDataPermission.has_permission = old_check_perms
