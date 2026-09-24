import csv
import os

csv_in = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER.csv'
mapping_in = 'e:/SAHIS/SHANMUGALIVE_CSV/PatientMaster_Detailed_Mapping.csv'
csv_out = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER_Django_Format.csv'

# Read mapping
mapping = {}
with open(mapping_in, 'r', encoding='utf-8', errors='ignore') as f:
    reader = csv.DictReader(f)
    for row in reader:
        original = row['CSV_Column']
        django_field = row['Matched_Django_Field']
        confidence = row['Confidence']
        
        # We only map if it's found
        if 'NOT FOUND' not in django_field and django_field.strip() != '':
            mapping[original] = django_field

# Process the data file
with open(csv_in, 'r', encoding='utf-8', errors='ignore') as fin, \
     open(csv_out, 'w', newline='', encoding='utf-8') as fout:
    
    reader = csv.reader(fin)
    writer = csv.writer(fout)
    
    headers = next(reader)
    if headers:
        headers[0] = headers[0].lstrip('\ufeff')
        
    new_headers = []
    for h in headers:
        if h in mapping:
            new_headers.append(mapping[h])
        else:
            new_headers.append(h)
            
    writer.writerow(new_headers)
    
    # Write the rest of the rows
    for row in reader:
        writer.writerow(row)

print("Transformed CSV created.")
