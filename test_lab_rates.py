import os, django, json
from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.Views.departmentBilling import get_investigation_items
from django.test import RequestFactory
from unittest.mock import patch

rf = RequestFactory()

# Bypass permission check for test
with patch('pyauth.auth.HasRoleAndDataPermission.has_permission', return_value=True):
    for btn in ['LAB01', 'LAB02', 'LAB03']:
        request = rf.get(f'/investigation-items/?billTypeNo={btn}&billType=1')
        response = get_investigation_items(request)
        data = json.loads(response.content)
        items = data.get('items', [])
        test_506 = [it for it in items if it.get('test_id') == 506]
        print(f"=== {btn} (Total items: {len(items)}) ===")
        if test_506:
            print("Test 506 item:", json.dumps(test_506[0], indent=2))
        else:
            print("Test 506 not in results")
