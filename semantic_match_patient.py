import os
import django
import csv
import difflib

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from django.apps import apps
Patient = apps.get_model('hospital', 'Patient')

# Get Django fields
django_fields = [f.name for f in Patient._meta.fields]
django_fields_lower = {f.name.lower().replace('_', ''): f.name for f in Patient._meta.fields}

csv_path = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER.csv'
out_path = 'e:/SAHIS/SHANMUGALIVE_CSV/PatientMaster_Detailed_Mapping.csv'

results = [['CSV_Column', 'Matched_Django_Field', 'Confidence', 'Django_Field_Type']]

manual_overrides = {
    'opnumber': 'uhid',
    'dateofbirth': 'dob',
    'patientsex': 'gender',
    'patientphone': 'mobilephone',
    'tphone2': 'home_phone',
    'patientemaili': 'email',
    'patientweight': 'weight',
    'patientnationality': None,
    'patientmiddlename': None,
    'patientphotograph': None,
    'machineid': None
}

with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
    reader = csv.reader(f)
    headers = next(reader)

if headers:
    headers[0] = headers[0].lstrip('\ufeff')

for col in headers:
    if not col.strip():
        continue
    
    clean_col = col.lower().replace('_', '').strip()
    
    # 1. Manual Overrides
    if clean_col in manual_overrides:
        match_name = manual_overrides[clean_col]
        if match_name is None:
            results.append([col, 'NOT FOUND', '0% (Manual Override)', ''])
            continue
        # Find exact case in django_fields
        actual_name = next(f for f in django_fields if f.lower() == match_name.lower())
        f_type = Patient._meta.get_field(actual_name).get_internal_type()
        results.append([col, actual_name, '100% (Manual Override)', f_type])
        continue
    
    # 2. Exact match
    if clean_col in django_fields_lower:
        match_name = django_fields_lower[clean_col]
        f_type = Patient._meta.get_field(match_name).get_internal_type()
        results.append([col, match_name, '100% (Exact)', f_type])
        continue
        
    # 3. Substring or Fuzzy Match
    clean_col_no_prefix = clean_col.replace('patient', '')
    
    best_match = None
    best_ratio = 0
    
    for df in django_fields:
        clean_df = df.lower().replace('_', '')
        
        # Fuzzy match
        ratio = difflib.SequenceMatcher(None, clean_col_no_prefix, clean_df).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = df
            
        # Hardcode some obvious mappings
        if 'address' in clean_col and 'address' in clean_df:
            best_ratio = 0.9
            best_match = df

    if best_match and best_ratio > 0.6: # 60% threshold
        f_type = Patient._meta.get_field(best_match).get_internal_type()
        results.append([col, best_match, f"{int(best_ratio*100)}% (Fuzzy/Partial)", f_type])
    else:
        results.append([col, 'NOT FOUND', '0%', ''])

with open(out_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerows(results)

print("Mapping refined.")
