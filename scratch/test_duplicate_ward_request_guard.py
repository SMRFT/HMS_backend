import os
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.abspath('HMS_backend'))
from dotenv import load_dotenv
load_dotenv('HMS_backend/.env')

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.Views.NursingStation import save_medicine_ward_request
from hospital.Views.dbcollection import hms_db
from hospital.models import PharmacyBilling
from rest_framework.test import APIRequestFactory

def run_tests():
    print("=== TESTING WARD REQUEST DUPLICATE PREVENTION GUARD ===")
    factory = APIRequestFactory()

    test_uhid = "TEST_DUP_UHID"
    test_ip = "TEST_DUP_IP"

    # Cleanup test data
    hms_db["hospital_pharmacybilling"].delete_many({"uhid": test_uhid})
    PharmacyBilling.objects.filter(uhid=test_uhid).delete()

    try:
        payload = {
            "uhid": test_uhid,
            "ipNumber": test_ip,
            "patient_name": "Test Duplicate Patient",
            "bill_type": 18,
            "billTypeNo": "PH01",
            "billTypeName": "PHARMACY IP BILL",
            "wardName": "ICU",
            "roomNo": "501 | Bed 1",
            "doctor": "DR. TEST",
            "doctor_id": "99999",
            "medicine_particulars": [
                {"item_id": 101, "qty": 2, "price": 50.0, "dosage": "1-0-1"},
                {"item_id": 102, "qty": 1, "price": 100.0, "dosage": "1-0-0"}
            ],
            "total_amount": 200.0
        }

        # 1. First submission
        req1 = factory.post('/save_medicine_ward_request/', payload, format='json')
        with patch('pyauth.auth.HasRoleAndDataPermission.has_permission', return_value=True):
            res1 = save_medicine_ward_request(req1)

        print("Response 1:", res1.data)
        assert res1.data.get("success") is True, "First request failed"
        bill_no_1 = res1.data.get("bill_no")
        assert bill_no_1.startswith("MRIP"), f"Expected MRIP request_no, got {bill_no_1}"
        assert not res1.data.get("duplicate_suppressed"), "First request shouldn't be duplicate_suppressed"

        # 2. Second rapid submission with identical items within 1 second
        req2 = factory.post('/save_medicine_ward_request/', payload, format='json')
        with patch('pyauth.auth.HasRoleAndDataPermission.has_permission', return_value=True):
            res2 = save_medicine_ward_request(req2)

        print("Response 2 (rapid duplicate):", res2.data)
        assert res2.data.get("success") is True, "Second request failed"
        assert res2.data.get("duplicate_suppressed") is True, "Second request was NOT suppressed as duplicate!"
        assert res2.data.get("bill_no") == bill_no_1, f"Expected same bill_no {bill_no_1}, got {res2.data.get('bill_no')}"

        # 3. Verify database has only ONE record
        db_count = hms_db["hospital_pharmacybilling"].count_documents({"uhid": test_uhid, "is_deleted": {"$ne": True}})
        print(f"Total active records in DB for {test_uhid}: {db_count}")
        assert db_count == 1, f"Expected exactly 1 record in DB, found {db_count}!"

        print("\n>>> ALL TESTS PASSED SUCCESSFULLY! 100% OK <<<")

    finally:
        hms_db["hospital_pharmacybilling"].delete_many({"uhid": test_uhid})
        PharmacyBilling.objects.filter(uhid=test_uhid).delete()
        print("Cleanup completed.")

if __name__ == "__main__":
    run_tests()
