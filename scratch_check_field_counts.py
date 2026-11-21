import os, django
os.chdir('D:/SMRFT/Projects/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings-test')
django.setup()
from hospital.Views.MasterAccountsReport.core_ledger_engine import get_db
client, db, g_db = get_db()
print('has billed_bill_no:', db['hospital_pharmacybilling'].count_documents({'billed_bill_no': {'$exists': True}}))
print('has converted_bill_no:', db['hospital_pharmacybilling'].count_documents({'converted_bill_no': {'$exists': True}}))
print('has bill_number:', db['hospital_pharmacybilling'].count_documents({'bill_number': {'$exists': True}}))
client.close()
