from pymongo import MongoClient
import os

# Create Mongo client (single place)
mongo_url = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(mongo_url)

# Databases

global_db = client["Global"]
hms_db = client["HMS"]

# Collections

profile_collection = global_db["backend_diagnostics_profile"]
department_collection = global_db["backend_diagnostics_Departments"]
user_collection = global_db["backend_diagnostics_user"]
company_secretary_collection = hms_db["hospital_licencemasterdetails"]  
MHC_Package =hms_db["hospital_MHC_Package"] 
MHC_Source= hms_db["hospital_MHC_Source"]