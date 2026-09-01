import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hospital.settings')
django.setup()

from Views.OPEMR.models import VitalEntry

vitals = VitalEntry.objects.filter(uhid='S026/00551').order_by('-created_date')
print(f"Total entries: {vitals.count()}")
for v in vitals:
    print(f"ID: {v.id}, Height: {v.height}, Weight: {v.weight}, Created: {v.created_date}, Vital Entry Date: {v.vital_entry_date}")
