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
from hospital.Views.doctormaster import doctor_schedule_list
from hospital.Views import doctormaster as dm_module

old_check = dm_module.HasRoleAndDataPermission.has_permission
dm_module.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

factory = APIRequestFactory()
request = factory.get('/doctor_schedule/')

t0 = time.time()
try:
    response = doctor_schedule_list(request)
    print(f'Status: {response.status_code} in {time.time()-t0:.2f}s')
    data = response.data
    print('Data type:', type(data), 'Count:', len(data) if isinstance(data, list) else data)
except Exception as e:
    import traceback
    print(f'Error in {time.time()-t0:.2f}s: {e}')
    traceback.print_exc()
finally:
    dm_module.HasRoleAndDataPermission.has_permission = old_check
