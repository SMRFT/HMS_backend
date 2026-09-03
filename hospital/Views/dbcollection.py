from pymongo import MongoClient
import os

# Create Mongo client (single place)
mongo_url = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(mongo_url)

# Databases

global_db = client["Global"]
hms_db = client["HMS"]
Diagnostics_db=client["Diagnostics"]

# Collections

profile_collection = global_db["backend_diagnostics_profile"]
department_collection = global_db["backend_diagnostics_Departments"]
user_collection = global_db["backend_diagnostics_user"]
company_secretary_collection = hms_db["hospital_licencemasterdetails"]  
MHC_Package =hms_db["hospital_MHC_Package"] 
MHC_Source= hms_db["hospital_MHC_Source"]
HMS_Symptoms_list=hms_db["hospital_Symptoms_list"]
medicine_package=hms_db["hospital_pharmacyitem"]
Diagnostics_test_details = Diagnostics_db["core_testdetails"]

doctor_role_code="SD-R-DOC"

def get_employee_name_by_id(employee_id):
    if not employee_id:
        return "Unknown"
    emp = profile_collection.find_one({"employeeId": str(employee_id)})
    if emp and "employeeName" in emp:
        return emp["employeeName"]
    return "Unknown"
