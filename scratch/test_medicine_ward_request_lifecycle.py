import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath('HMS_backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings-test')
import dotenv
dotenv.load_dotenv('HMS_backend/.env')

import django
django.setup()

from rest_framework.test import APIRequestFactory
from pymongo import MongoClient
from bson import ObjectId

from hospital.Views.NursingStation import save_medicine_ward_request, get_medicine_ward_requests
from hospital.Views.pharmacy import finalize_bill
from hospital.counter_service import get_next_medicine_ward_request_no

class TestMedicineWardRequestLifecycle(unittest.TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        self.db = self.client["HMS"]
        # Clean up any test records
        self.test_uhid = "TEST_UHID_MRIP_99"
        self.db["hospital_pharmacybilling"].delete_many({"uhid": self.test_uhid})
        self.db["counters"].delete_many({"_id": {"$in": ["medicine_ward_request_mrip", "medicine_ward_request_mrop"]}})

    def tearDown(self):
        self.db["hospital_pharmacybilling"].delete_many({"uhid": self.test_uhid})
        self.db["counters"].delete_many({"_id": {"$in": ["medicine_ward_request_mrip", "medicine_ward_request_mrop"]}})

    @patch('pyauth.auth.HasRoleAndDataPermission.has_permission', return_value=True)
    def test_historical_patient_s020_002919(self, mock_perm):
        """Test that patient S020/002919 records return real bill numbers and medicines, not ObjectIds and 0 items."""
        req = self.factory.get("/get_medicine_ward_requests/?uhid=S020/002919&ipNumber=S026/008309")
        res = get_medicine_ward_requests(req)
        self.assertTrue(res.data.get("success"))
        data = res.data.get("data", [])
        self.assertGreater(len(data), 0, "Should have records for S020/002919")

        # Check first record
        first = data[0]
        print(f"\n[Test Historical] First record bill_no: '{first.get('bill_no')}', status: '{first.get('status')}', med_count: {len(first.get('medicines', []))}")
        self.assertFalse(first.get("bill_no", "").startswith("6afc"), f"Should not be ObjectId, got {first.get('bill_no')}")
        self.assertGreater(len(first.get("medicines", [])), 0, "Medicines should not be 0 items")
        self.assertEqual(first.get("status"), "Billed", "Historical paid bill should be Billed status")

    @patch('pyauth.auth.HasRoleAndDataPermission.has_permission', return_value=True)
    def test_new_mrip_request_and_bill_conversion(self, mock_perm):
        """Test raising an IP medicine request (MRIP001) and subsequent conversion to a final bill number."""
        # 1. Raise new IP Medicine Ward Request
        save_payload = {
            "uhid": self.test_uhid,
            "ipNumber": "IP_TEST_001",
            "bill_type": 18,
            "billTypeName": "PHARMACY IP BILL",
            "doctor": "DR. TEST",
            "roomNo": "501 | Bed 1",
            "medicine_particulars": [
                {
                    "item_id": 57013,
                    "item_name": "PARACETAMOL 500MG",
                    "qty": 5,
                    "price": 10.0,
                    "dosage": "1-0-1",
                    "noOfDays": "3"
                }
            ],
            "total_amount": 50.0,
            "outlet_code": "OLET001"
        }
        req_post = self.factory.post("/save_medicine_ward_request/", save_payload, format="json")
        res_post = save_medicine_ward_request(req_post)
        self.assertTrue(res_post.data.get("success"))
        req_no = res_post.data.get("request_no")
        print(f"\n[Test New Request] Generated Request No: '{req_no}'")
        self.assertEqual(req_no, "MRIP001", f"Expected MRIP001, got {req_no}")

        # 2. Query Nursing Station requests
        req_get = self.factory.get(f"/get_medicine_ward_requests/?uhid={self.test_uhid}")
        res_get = get_medicine_ward_requests(req_get)
        self.assertTrue(res_get.data.get("success"))
        records = res_get.data.get("data", [])
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.get("bill_no"), "MRIP001", "Pending request bill_no should display MRIP001")
        self.assertEqual(r.get("request_no"), "MRIP001")
        self.assertEqual(r.get("status"), "Pending")
        self.assertEqual(len(r.get("medicines")), 1)
        self.assertEqual(r.get("medicines")[0].get("quantity"), 5.0)

        # 3. Simulate Pharmacy Conversion to Bill (setting billed_bill_no: 262701000013 and status: Billed)
        self.db["hospital_pharmacybilling"].update_one(
            {"uhid": self.test_uhid},
            {"$set": {
                "billing_status": "Billed",
                "billed_bill_no": "262701000013",
                "converted_bill_no": "262701000013"
            }}
        )

        # 4. Query Nursing Station requests after conversion
        req_after = self.factory.get(f"/get_medicine_ward_requests/?uhid={self.test_uhid}")
        res_after = get_medicine_ward_requests(req_after)
        records_after = res_after.data.get("data", [])
        self.assertEqual(len(records_after), 1)
        converted = records_after[0]
        print(f"[Test Conversion] After conversion bill_no: '{converted.get('bill_no')}', status: '{converted.get('status')}', req_no: '{converted.get('request_no')}'")
        self.assertEqual(converted.get("bill_no"), "262701000013", "Converted request should display final Bill Number")
        self.assertEqual(converted.get("request_no"), "MRIP001", "Original request_no should be preserved")
        self.assertEqual(converted.get("status"), "Billed")
        self.assertTrue(converted.get("is_converted"))

    @patch('pyauth.auth.HasRoleAndDataPermission.has_permission', return_value=True)
    def test_new_mrop_request(self, mock_perm):
        """Test raising an OP medicine request (MROP001)."""
        save_payload = {
            "uhid": self.test_uhid,
            "ipNumber": "",
            "bill_type": 42,
            "billTypeName": "PHARMACY OP BILL",
            "doctor": "DR. TEST",
            "roomNo": "-",
            "medicine_particulars": [{"item_id": 57013, "qty": 2, "price": 10.0}],
            "total_amount": 20.0,
            "outlet_code": "OLET001"
        }
        req_post = self.factory.post("/save_medicine_ward_request/", save_payload, format="json")
        res_post = save_medicine_ward_request(req_post)
        self.assertTrue(res_post.data.get("success"))
        req_no = res_post.data.get("request_no")
        print(f"\n[Test OP Request] Generated OP Request No: '{req_no}'")
        self.assertEqual(req_no, "MROP001", f"Expected MROP001, got {req_no}")

if __name__ == "__main__":
    unittest.main()
