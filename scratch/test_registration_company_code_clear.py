import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath('HMS_backend'))
from dotenv import load_dotenv
load_dotenv('HMS_backend/.env')

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.models import Patient
from hospital.Views.dbcollection import patient_collection
from unittest.mock import patch, MagicMock
from hospital.views import patientCreateView
from hospital.Views.patient_master import patient_master_update
from rest_framework.test import APIRequestFactory

@patch('pyauth.auth.HasRoleAndDataPermission.has_permission', return_value=True)
def run_tests(mock_perm):
    print("=== STARTING REGISTRATION INSURANCE COMPANY CODE CLEAR TESTS ===")
    factory = APIRequestFactory()

    test_uhid = "TEST_UHID_9999"
    # Clean up any leftover test data
    Patient.objects.filter(uhid=test_uhid).delete()
    patient_collection.delete_many({"uhid": test_uhid})

    try:
        # Step 1: Create initial patient as Insurance
        print("\n--- Test 1: Register patient with customer_type='Insurance' and company_code='COMP_TEST' ---")
        reg_view = patientCreateView

        req1 = factory.post('/patients/register/', {
            "firstName": "TestInsClear",
            "lastName": "Patient",
            "salutation": "Mr",
            "dob": "1990-01-01",
            "gender": "Male",
            "mobilePhone": "9876543210",
            "customer_type": "Insurance",
            "company_code": "COMP_TEST",
            "registrationFee": "100.00",
            "consultingFee": "200.00",
            "totalFees": "300.00",
            "payment_timing": "pay_later",
            "payment_method": "Credit"
        })
        # Simulate auth headers / attributes
        req1.data = req1.POST.copy()
        res1 = reg_view(req1)
        print("Status code 1:", res1.status_code)
        assert res1.status_code == 201, f"Expected 201, got {res1.status_code}: {res1.data}"
        uhid_created = res1.data.get("uhid")
        print("Created UHID:", uhid_created)

        # Check DB
        p1 = Patient.objects.get(uhid=uhid_created)
        print("Patient in ORM company_code:", repr(p1.company_code), "customer_type:", repr(p1.customer_type))
        assert p1.company_code == "COMP_TEST", f"Expected COMP_TEST, got {p1.company_code}"

        doc1 = patient_collection.find_one({"uhid": uhid_created})
        print("Patient in MongoDB company_code:", repr(doc1.get("company_code")), "customer_type:", repr(doc1.get("customer_type")))
        assert doc1.get("company_code") == "COMP_TEST", f"Expected COMP_TEST in mongo, got {doc1.get('company_code')}"
        print("✓ Test 1 Passed: Insurance company_code properly saved.")

        # Step 2: Now re-register or update existing patient with customer_type='General' via patientCreateView
        print("\n--- Test 2: Update existing patient to customer_type='General' via patientCreateView ---")
        req2 = factory.post('/patients/register/', {
            "uhid": uhid_created,
            "firstName": "TestInsClear",
            "lastName": "Patient",
            "salutation": "Mr",
            "dob": "1990-01-01",
            "gender": "Male",
            "mobilePhone": "9876543210",
            "customer_type": "General",
            "registrationFee": "100.00",
            "consultingFee": "200.00",
            "totalFees": "300.00",
            "payment_timing": "pay_now",
            "payment_method": "Cash"
        })
        req2.data = req2.POST.copy()
        res2 = reg_view(req2)
        print("Status code 2:", res2.status_code)
        assert res2.status_code == 201, f"Expected 201, got {res2.status_code}: {res2.data}"

        p2 = Patient.objects.get(uhid=uhid_created)
        print("Patient in ORM company_code:", repr(p2.company_code), "customer_type:", repr(p2.customer_type))
        assert not p2.company_code, f"Expected empty company_code, got {p2.company_code}"

        doc2 = patient_collection.find_one({"uhid": uhid_created})
        print("Patient in MongoDB company_code:", repr(doc2.get("company_code")), "customer_type:", repr(doc2.get("customer_type")))
        assert not doc2.get("company_code"), f"Expected empty company_code in mongo, got {doc2.get('company_code')}"
        print("✓ Test 2 Passed: company_code cleared in ORM and MongoDB when customer_type='General'.")

        # Step 3: Test patient_master_update clearing company_code & company_name
        print("\n--- Test 3: patient_master_update clearing company_code when updated to General ---")
        # First set it back to insurance
        patient_collection.update_one({"uhid": uhid_created}, {"$set": {"customer_type": "Insurance", "company_code": "COMP_TEST_2", "company_name": "Test Insurance"}})
        Patient.objects.filter(uhid=uhid_created).update(customer_type="Insurance", company_code="COMP_TEST_2")

        req3 = factory.put(f'/patient_master/{uhid_created}/', {
            "customer_type": "General"
        }, format='json')
        # attach mock user
        req3.user = type('User', (), {'id': 1, 'username': 'admin', 'is_active': True, 'is_authenticated': True})()
        req3.auth = "mock_auth"
        res3 = patient_master_update(req3, uhid_created)
        print("Status code 3:", res3.status_code)
        assert res3.status_code == 200, f"Expected 200, got {res3.status_code}: {res3.data}"

        p3 = Patient.objects.get(uhid=uhid_created)
        print("Patient in ORM after master update company_code:", repr(p3.company_code))
        assert not p3.company_code, f"Expected empty company_code, got {p3.company_code}"

        doc3 = patient_collection.find_one({"uhid": uhid_created})
        print("Patient in MongoDB after master update company_code:", repr(doc3.get("company_code")), "company_name:", repr(doc3.get("company_name")))
        assert not doc3.get("company_code"), f"Expected empty company_code in mongo, got {doc3.get('company_code')}"
        assert not doc3.get("company_name"), f"Expected empty company_name in mongo, got {doc3.get('company_name')}"
        print("✓ Test 3 Passed: patient_master_update cleanly cleared company_code and company_name.")

        print("\n>>> ALL TESTS PASSED SUCCESSFULLY! 100% OK <<<")

    finally:
        # Cleanup test data
        if 'uhid_created' in locals():
            Patient.objects.filter(uhid=uhid_created).delete()
            patient_collection.delete_many({"uhid": uhid_created})
            from hospital.models import Billing
            Billing.objects.filter(uhid=uhid_created).delete()
            from hospital.Views.dbcollection import hms_db
            hms_db["hospital_billing"].delete_many({"uhid": uhid_created})
            print("Cleanup completed.")

if __name__ == "__main__":
    run_tests()
