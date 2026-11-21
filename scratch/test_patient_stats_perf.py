import os
import sys
import time
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')

import django
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.views import patient_registration_stats

factory = APIRequestFactory()
request = factory.get('/patient-registration-stats/?fromDate=2026-11-21&toDate=2026-11-21&doctorId=')

t0 = time.time()
try:
    response = patient_registration_stats(request)
    print(f'Status: {response.status_code} in {time.time()-t0:.2f}s')
    print('Data:', response.data)
except Exception as e:
    import traceback
    print(f'Error in {time.time()-t0:.2f}s: {e}')
    traceback.print_exc()
