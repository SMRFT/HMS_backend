import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]
gdb = client['global_db'] if 'global_db' in client.list_database_names() else db

prof = db['backend_diagnostics_profile'].find_one({'employeeId': '60318'})
if not prof:
    prof = client['shanmuga_global']['backend_diagnostics_profile'].find_one({'employeeId': '60318'})

print("Employee profile for 60318:")
if prof:
    print("  employeeId:", prof.get('employeeId'))
    print("  name:", prof.get('employeeName') or prof.get('name'))
    print("  cashcounter:", prof.get('cashcounter'))
    print("  hms_outlets:", prof.get('hms_outlets'))
    
    # check cashcounter doc
    cc = db['hospital_cashcounter'].find_one({'counter_id': prof.get('cashcounter')})
    if cc:
        print("  counter_id:", cc.get('counter_id'))
        print("  outlet:", cc.get('outlet'))
        print("  bill_type:", cc.get('bill_type'))
