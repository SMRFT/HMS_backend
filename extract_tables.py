import os
import django
import csv
from django.apps import apps

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

all_models = apps.get_models()
with open('e:/SAHIS/SHANMUGALIVE_CSV/django_tables.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['ModelName', 'TableName'])
    for model in all_models:
        writer.writerow([model.__name__, model._meta.db_table])
