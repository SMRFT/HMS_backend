import os
import sys
import time
import django

sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views.outlet_stock_report import outlet_wise_stock_report
from hospital.Views import outlet_stock_report as osr_module
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

# Bypass permission check for local integration test
old_check = osr_module.HasRoleAndDataPermission.has_permission
osr_module.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

factory = APIRequestFactory()

def test_outlet(outlet_code):
    print(f"\n================ Testing Outlet: {outlet_code} ================")
    t0 = time.time()
    request = factory.get(f'/outlet-wise-stock-report/?outlet_code={outlet_code}&stock_filter=in_stock')
    response = outlet_wise_stock_report(request)
    elapsed = time.time() - t0
    print(f"Response status: {response.status_code} in {elapsed:.2f}s")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    data = response.data
    assert data.get('success') is True
    summary = data.get('summary', {})
    rows = data.get('data', [])
    print(f"Total items returned: {len(rows)}, Summary total: {summary.get('total_items')}")
    print(f"Summary: {summary}")
    
    # 1. Check no orphan "Item <id>"
    orphan_items = [r for r in rows if str(r.get('item_name', '')).startswith('Item ') and str(r.get('item_name', ''))[5:].isdigit()]
    print(f"Orphan 'Item <id>' count: {len(orphan_items)}")
    assert len(orphan_items) == 0, f"Found orphan items: {orphan_items[:5]}"
    
    # 2. Check no inactive or blocked items
    item_ids = [r['item_id'] for r in rows]
    inactive_items = list(db['hospital_pharmacyitem'].find({
        'item_id': {'$in': item_ids},
        '$or': [{'is_active': False}, {'is_blocked': True}]
    }))
    print(f"Inactive / Blocked items count: {len(inactive_items)}")
    assert len(inactive_items) == 0, f"Found inactive/blocked items: {inactive_items[:5]}"
    
    # 3. Check known inactive items (e.g. 14932 5 STAR, 3735 SURGICAL SPIRIT 100ML)
    assert 14932 not in item_ids, "Item 14932 (5 STAR) should be excluded!"
    assert 3735 not in item_ids, "Item 3735 (SURGICAL SPIRIT 100ML) should be excluded!"
    
    # 4. Check known missing items (e.g. 72193, 63981)
    assert 72193 not in item_ids, "Item 72193 should be excluded!"
    assert 63981 not in item_ids, "Item 63981 should be excluded!"
    
    # 5. Check calculation accuracy
    calculated_units = sum(r['stock'] for r in rows)
    calculated_sales_val = round(sum(r['sales_value'] for r in rows), 2)
    calculated_purchase_val = round(sum(r['purchase_value'] for r in rows), 2)
    
    assert summary['total_items'] == len(rows), "Summary total items mismatch"
    assert abs(summary['total_stock_units'] - calculated_units) < 1, "Summary total stock units mismatch"
    assert abs(summary['total_sales_value'] - calculated_sales_val) < 1, "Summary sales value mismatch"
    assert abs(summary['total_purchase_value'] - calculated_purchase_val) < 1, "Summary purchase value mismatch"
    print("All assertions passed successfully!")

try:
    test_outlet('OLET002') # OP Pharmacy
    test_outlet('OLET001') # IP Pharmacy
    print("\n>>> ALL TESTS PASSED SUCCESSFULLY! 100% <<<")
finally:
    osr_module.HasRoleAndDataPermission.has_permission = old_check
