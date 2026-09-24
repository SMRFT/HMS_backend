import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from django.apps import apps
Patient = apps.get_model('hospital', 'Patient')
fields = [f.name for f in Patient._meta.fields]
print('Patient fields:', fields)
