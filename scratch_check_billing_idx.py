import os, django
os.chdir('D:/SMRFT/Projects/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings-test')
django.setup()
from hospital.Views.MasterAccountsReport.core_ledger_engine import get_db
client, db, g_db = get_db()
print('hospital_billing indexes:')
for idx in db['hospital_billing'].list_indexes():
    print(idx['name'], idx['key'])
client.close()
