from pymongo import MongoClient
import os

# Create Mongo client (single place)
mongo_url = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(mongo_url)

# Databases

global_db = client["Global"]
hms_db = client["HMS"]
Diagnostics_db=client["Diagnostics"]
ER_db = client["ER_Billing"]

# Collections

profile_collection                = global_db["backend_diagnostics_profile"]
department_collection             = global_db["backend_diagnostics_Departments"]
user_collection                   = global_db["backend_diagnostics_user"]
company_secretary_collection      = hms_db["hospital_licencemasterdetails"]  
MHC_Package                       = hms_db["hospital_MHC_Package"] 
MHC_Source                        = hms_db["hospital_MHC_Source"]
HMS_Symptoms_list                 = hms_db["hospital_Symptoms_list"]
medicine_package                  = hms_db["hospital_pharmacyitem"]
shanmuga360_collection            = hms_db["hospital_Shanmuga360_MedicineList"]
Diagnostics_test_details          = Diagnostics_db["core_testdetails"]
doctor_list                       = ER_db["doctors_list"]
hms_billtype                      = hms_db["hospital_billtype"]
hospital_investigationprice       = hms_db["hospital_investigationprice"]



doctor_role_code = "SD-R-DOC"
sample_collector = "SD-R-SMC"

def get_employee_name_by_id(employee_id):
    if not employee_id:
        return "Unknown"
    emp_str = str(employee_id).strip()
    emp = profile_collection.find_one({"employeeId": emp_str})
    if not emp and emp_str.isdigit():
        num_val = int(emp_str)
        emp = profile_collection.find_one({
            "$or": [
                {"employeeId": num_val},
                {"employeeId": str(num_val)},
                {"employeeId": f"{num_val:04d}"},
                {"employeeId": f"{num_val:05d}"},
                {"employeeId": f"{num_val:06d}"}
            ]
        })
    if emp and "employeeName" in emp:
        return emp["employeeName"]
    return "Unknown"
