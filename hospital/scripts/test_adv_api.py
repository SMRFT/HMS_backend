import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.test import RequestFactory
from hospital.Views.AccountsReport.accounting_reports import advance_registration_report

# call advance_registration_report.cls().get(req) or bypass auth
# In DRF, we can call the underlying function or mock permissions
from hospital.Views.AccountsReport.accounting_reports import advance_registration_report
rf = RequestFactory()
req = rf.get('/api/advance_registration_report/?from_date=2026-11-15&to_date=2026-11-15')
from rest_framework.permissions import AllowAny
advance_registration_report.cls.permission_classes = [AllowAny]
resp = advance_registration_report(req)

if hasattr(resp, 'render'):
    resp.render()
print("Status:", resp.status_code)
if hasattr(resp, 'data'):
    data = resp.data
else:
    import json
    data = json.loads(resp.content)
rows = data.get('data', [])
print(f"Total rows: {len(rows)}")
for r in rows:
    print(f"Bill: {r.get('billnumber')}, IP: {r.get('ipNumber')}, UHID: {r.get('uhid')}, Name: {r.get('patientname')}, Cash: {r.get('cash_amount')}, Credit: {r.get('credit_card_amount')}")
print("Summary:", data.get('summary'))
