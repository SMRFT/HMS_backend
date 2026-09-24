import json
import os
import csv

mapping_file = 'e:/SAHIS/SHANMUGALIVE_CSV/PatientMaster_Detailed_Mapping.csv'
json_in = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER_Mongo.json'
json_out = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER_Mongo_Clean.json'

print("Starting cleanup...")

# Get list of valid django fields
valid_fields = set()
with open(mapping_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        django_field = row['Matched_Django_Field']
        if 'NOT FOUND' not in django_field and django_field.strip():
            valid_fields.add(django_field)

count_in = 0
count_out = 0

with open(json_in, 'r', encoding='utf-8') as fin, \
     open(json_out, 'w', encoding='utf-8') as fout:
    
    for line in fin:
        count_in += 1
        data = json.loads(line)
        
        # 1. Skip if 'uhid' contains '===' or is the header 'OPNUMBER'
        uhid = data.get('uhid', '')
        if '===' in uhid or uhid == 'OPNUMBER' or uhid == 'PATIENTPHOT':
            continue
            
        # 2. Check if the values in general look like garbage ('===')
        is_garbage = False
        for val in data.values():
            if '=========' in str(val):
                is_garbage = True
                break
        if is_garbage:
            continue
            
        # 3. Filter keys, keep only valid Django fields
        clean_data = {}
        for k, v in data.items():
            if k in valid_fields:
                # Clean up values slightly (remove leading/trailing spaces)
                clean_val = str(v).strip()
                if clean_val and clean_val != '<null' and clean_val != '<null>':
                    clean_data[k] = clean_val
                    
        # 4. Save if there's meaningful data (at least a uhid)
        if clean_data and 'uhid' in clean_data:
            fout.write(json.dumps(clean_data) + '\n')
            count_out += 1

print(f"Cleanup finished! Processed {count_in} rows, kept {count_out} clean rows.")
