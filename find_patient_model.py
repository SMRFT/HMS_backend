import os
import django
from django.apps import apps

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

models = apps.get_models()
patient_models = [m.__name__ for m in models if 'patient' in m.__name__.lower()]
print('Patient Models:', patient_models)
