import os
import django
import json
import csv
import glob

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from django.apps import apps

# 1. Get Django models and their fields
all_models = apps.get_models()
django_models = {}
for model in all_models:
    # lowercased fields for easier comparison
    fields = [f.name.lower().replace('_', '') for f in model._meta.fields]
    django_models[model.__name__] = {
        'table': model._meta.db_table,
        'fields': set(fields)
    }

# 2. Get CSV files and their headers
csv_dir = 'e:/SAHIS/SHANMUGALIVE_CSV/'
csv_files = glob.glob(os.path.join(csv_dir, '*.csv'))

results = []
results.append(['CSVFile', 'BestMatchModel', 'BestMatchTable', 'MatchScore', 'MatchedFields', 'MissingFromDjango', 'ExtraInDjango'])

for csv_path in csv_files:
    csv_filename = os.path.basename(csv_path)
    if csv_filename in ['hms_table_mapping.csv', 'django_tables.csv', 'HMS_to_Django_Mapping.csv', 'export_manifest.csv', 'Field_Based_Mapping.csv']:
        continue
        
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            headers = next(reader)
    except Exception:
        continue
        
    if not headers:
        continue
        
    # Remove BOM if present
    headers[0] = headers[0].lstrip('\ufeff')
    csv_fields = set([h.lower().replace('_', '') for h in headers if h])
    if not csv_fields:
        continue
        
    best_match = None
    best_score = 0
    best_match_details = {}
    
    for model_name, model_info in django_models.items():
        model_fields = model_info['fields']
        intersection = csv_fields.intersection(model_fields)
        if not intersection:
            continue
            
        # Score is percentage of csv fields that exist in model
        score = (len(intersection) / len(csv_fields)) * 100
        
        # Give a huge bonus if table name matches loosely
        csv_base = csv_filename.replace('.csv', '').lower()
        if csv_base == model_info['table'].lower().replace('_', '') or model_name.lower().replace('_', '') == csv_base:
            score += 100
            
        if score > best_score:
            best_score = score
            best_match = model_name
            best_match_details = {
                'table': model_info['table'],
                'matched': intersection,
                'missing': csv_fields - model_fields,
                'extra': model_fields - csv_fields
            }
            
    if best_match and best_score >= 10: # threshold 10%
        results.append([
            csv_filename, 
            best_match, 
            best_match_details['table'], 
            f"{best_score:.2f}", 
            " | ".join(best_match_details['matched']),
            " | ".join(best_match_details['missing']),
            " | ".join(best_match_details['extra'])
        ])
    else:
        results.append([csv_filename, 'NO GOOD MATCH', '', '0', '', '', ''])

# Sort results so matches are at the top
header = results.pop(0)
results.sort(key=lambda x: float(x[3]), reverse=True)
results.insert(0, header)

with open(os.path.join(csv_dir, 'Field_Based_Mapping.csv'), 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerows(results)

print("Matching complete.")
