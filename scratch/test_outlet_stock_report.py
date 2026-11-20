import os
import sys
import django

sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views.outlet_stock_report import outlet_wise_stock_report
from hospital.Views import outlet_stock_report as osr_module

factory = APIRequestFactory()
request = factory.get('/outlet-wise-stock-report/?outlet_code=OLET002&stock_filter=in_stock')

old_check = osr_module.HasRoleAndDataPermission.has_permission
osr_module.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

try:
    response = outlet_wise_stock_report(request)
    print("Status:", response.status_code)
    data = response.data
    print("Summary:", data.get('summary'))
    rows = data.get('data', [])
    print(f"Total rows returned: {len(rows)}")
    for r in rows[:10]:
        print(f"Item ID: {r.get('item_id')} | Name: {r.get('item_name')} | Stock: {r.get('stock')} | MRP: {r.get('mrp')} | Batches count: {len(r.get('batches', []))}")
finally:
    osr_module.HasRoleAndDataPermission.has_permission = old_check
