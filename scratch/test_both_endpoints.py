import os, sys, time
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')

import django
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views.doctormaster import doctor_schedule_list
from hospital.views import patient_visit_list, patient_registration_stats
from hospital.Views import doctormaster as dm_module
from hospital import views as v_module

# Bypass permission check for test runner
dm_module.HasRoleAndDataPermission.has_permission = lambda self, req, view: True
v_module.HasRoleAndDataPermission.has_permission = lambda self, req, view: True

factory = APIRequestFactory()

print('--- Testing Endpoint 1: doctor_schedule_list ---')
t0 = time.time()
r1 = doctor_schedule_list(factory.get('/doctor_schedule/'))
print(f'doctor_schedule: Status {r1.status_code} in {time.time()-t0:.3f}s -> {len(r1.data)} doctors')

print('\n--- Testing Endpoint 2: patient_visit_list ---')
t0 = time.time()
r2 = patient_visit_list(factory.get('/patient-visit-list/?fromDate=2026-11-21&toDate=2026-11-21&doctorId='))
print(f'patient_visit_list: Status {r2.status_code} in {time.time()-t0:.3f}s -> {len(r2.data)} visits')

print('\n--- Testing Endpoint 3: patient_registration_stats ---')
t0 = time.time()
r3 = patient_registration_stats(factory.get('/patient-registration-stats/?fromDate=2026-11-21&toDate=2026-11-21&doctorId='))
print(f'patient_registration_stats: Status {r3.status_code} in {time.time()-t0:.3f}s -> {r3.data}')
