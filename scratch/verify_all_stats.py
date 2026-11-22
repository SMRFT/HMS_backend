import os, sys, time
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')

import django
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.views import patient_registration_stats

factory = APIRequestFactory()

# Test 1: No params (defaults to today)
t0 = time.time()
r1 = patient_registration_stats(factory.get('/patient-registration-stats/'))
print(f'Test 1 (default today): Status {r1.status_code} in {time.time()-t0:.3f}s -> {r1.data}', flush=True)

# Test 2: With doctorId
t0 = time.time()
r2 = patient_registration_stats(factory.get('/patient-registration-stats/?doctorId=50697'))
print(f'Test 2 (with doctorId): Status {r2.status_code} in {time.time()-t0:.3f}s -> {r2.data}', flush=True)

# Test 3: Past date range (2026-11-15 to 2026-11-20)
t0 = time.time()
r3 = patient_registration_stats(factory.get('/patient-registration-stats/?fromDate=2026-11-15&toDate=2026-11-20'))
print(f'Test 3 (date range): Status {r3.status_code} in {time.time()-t0:.3f}s -> {r3.data}', flush=True)
