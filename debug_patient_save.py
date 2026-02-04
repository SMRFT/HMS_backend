
import os
import django
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.models import Patient

print("Attempting to save a test patient...")
try:
    p = Patient(
        firstName="Test",
        lastName="User",
        mobilePhone="9998887776",
        age=25,
        gender="Male",
        dob=date(2000, 1, 1),
        uhid="" # Should trigger auto-generation
    )
    p.save()
    print(f"Success! UHID: {p.uhid}")
except Exception as e:
    print("Failed to save patient.")
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
