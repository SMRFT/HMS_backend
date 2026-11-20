import os
import sys
import django

sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views import NursingStation
from hospital.models import PharmacyBilling
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

# Bypass permission check for local unit test
old_check_perms = NursingStation.HasRoleAndDataPermission.has_permission
NursingStation.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

try:
    factory = APIRequestFactory()
    payload = {
        "uhid": "S026/006687",
        "ipNumber": "S026/008383",
        "bill_type": 18,
        "doctor_id": "60043",
        "room_no": "TS-518 | B",
        "medicine_particulars": [
            {"item_id": 999999, "quantity": 1, "dosage": "1-0-1", "noOfDays": 1}
        ],
        "total_amount": 50.0,
        "auth-user-id": "NS3",
        "auth-hospital-code": "SH001",
        "auth-branch-code": "SHB001",
        "auth-outlet-code": "OLET001"
    }

    req = factory.post('/save_medicine_ward_request/', payload, format='json')
    req.user = type('User', (), {'id': 1, 'username': 'admin', 'is_active': True, 'is_authenticated': True})()

    resp = NursingStation.save_medicine_ward_request(req)
    print("save_medicine_ward_request response:", resp.data)

    bill_id = resp.data.get('id')
    req_no = resp.data.get('request_no')
    saved_bill_no = resp.data.get('bill_no')

    print(f"Created Bill_id: {bill_id}, request_no: {req_no}, returned bill_no: {saved_bill_no}")

    # Check MongoDB
    doc = db['hospital_pharmacybilling'].find_one({'Bill_id': bill_id})
    print("MongoDB doc - request_no:", doc.get('request_no'), "bill_no:", doc.get('bill_no'), "billing_status:", doc.get('billing_status'))

    assert doc.get('bill_no') is None, f"Expected bill_no to be None, got {doc.get('bill_no')}"
    assert doc.get('request_no') == req_no, f"Expected request_no to be {req_no}, got {doc.get('request_no')}"
    assert doc.get('billing_status') == "Pending"

    # Clean up test doc
    db['hospital_pharmacybilling'].delete_one({'Bill_id': bill_id})
    PharmacyBilling.objects.filter(Bill_id=bill_id).delete()
    print("Cleaned up test record. Verification successful! 100% OK")
finally:
    NursingStation.HasRoleAndDataPermission.has_permission = old_check_perms
