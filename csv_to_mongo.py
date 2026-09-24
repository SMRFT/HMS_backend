import csv
import json

csv_in = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER_Django_Format.csv'
json_out = 'e:/SAHIS/SHANMUGALIVE_CSV/PATIENTMASTER_Mongo.json'

print("Starting conversion to MongoDB JSON format...")

with open(csv_in, 'r', encoding='utf-8', errors='ignore') as fin, \
     open(json_out, 'w', encoding='utf-8') as fout:
    
    reader = csv.DictReader(fin)
    
    count = 0
    for row in reader:
        # Clean up empty fields so MongoDB doesn't get bloated with empty strings
        clean_row = {k: v for k, v in row.items() if k and v and v.strip() != ''}
        if clean_row:
            # Write as JSON Lines (one JSON object per line)
            fout.write(json.dumps(clean_row) + '\n')
            count += 1
            if count % 100000 == 0:
                print(f"Processed {count} rows...")

print(f"Finished! Total rows processed: {count}")
