import os
import sys
import traceback
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')

import django
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views.doctormaster import doctor_schedule_list
from hospital.Views import doctormaster as dm_module

dm_module.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

factory = APIRequestFactory()
request = factory.get('/doctor_schedule/')

try:
    response = doctor_schedule_list(request)
    print("Response status:", response.status_code)
    print("Response data:", response.data)
except Exception as e:
    traceback.print_exc()
