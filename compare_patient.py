import os
import django
import csv

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from django.apps import apps
Patient = apps.get_model('hospital', 'Patient') # Assuming it's in 'hospital' app

# Get Django fields
django_fields = {}
for f in Patient._meta.fields:
    # Key is lowercase without underscores
    key = f.name.lower().replace('_', '')
    django_fields[key] = {
        'name': f.name,
        'type': f.get_internal_type()
    }

csv_path = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER.csv'
out_path = 'e:/SAHIS/SHANMUGALIVE_CSV/PatientMaster_Comparison.csv'

results = [['CSV_Column_Name', 'Django_Field_Name', 'Django_Field_Type', 'Match_Status']]

with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
    reader = csv.reader(f)
    headers = next(reader)

# Clean BOM if exists
if headers:
    headers[0] = headers[0].lstrip('\ufeff')

for col in headers:
    if not col:
        continue
    clean_col = col.lower().replace('_', '')
    if clean_col in django_fields:
        match = django_fields[clean_col]
        results.append([col, match['name'], match['type'], 'Matched'])
    else:
        results.append([col, 'NOT FOUND', 'NOT FOUND', 'Unmatched'])

with open(out_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerows(results)

print("Patient comparison complete.")
