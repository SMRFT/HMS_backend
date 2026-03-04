import os
import sys
import django
from pymongo import MongoClient

# Setup Django
sys.path.append('/Users/parthibanmurugan/Desktop/Live Projects/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from django.conf import settings

from dotenv import load_dotenv
load_dotenv()

mongo_host = os.getenv('GLOBAL_DB_HOST')
client = MongoClient(mongo_host)
db = client['HMS']
collection = db['frontendendpagemapping']

# Clear existing if any
collection.delete_many({})

# Data based on Sidebar.js structure
sidebar_data = [
    {
        "group": "Admin Controls",
        "order": 1,
        "pages": [
            { "name": "Permission Manager", "route": "/UserPermissions", "icon": "FiUsers", "permissions": ["HMS-P-HMS"] },
            { "name": "Sidebar Configuration", "route": "/SidebarConfiguration", "icon": "FiList", "permissions": ["HMS-P-HMS"] }
        ]
    },
    {
        "group": "Patient Management",
        "order": 2,
        "pages": [
            { "name": "Dashboard", "route": "/Dashboard", "icon": "FiHome", "permissions": ["HMS-API-SUM"] },
            { "name": "Patient Registration", "route": "/PatientRegistrationForm", "icon": "FiUserPlus", "permissions": ["HMS-P-REG", "HMS-P-REG-R", "HMS-P-REG-RW"] },
            { "name": "Registration Bills", "route": "/RegistrationBills", "icon": "FiFileText", "permissions": ["HMS-P-REG"] }
        ]
    },
    {
        "group": "Inventory",
        "order": 3,
        "pages": [
            { "name": "IP Pharmacy Stock", "route": "/IPPharmacyStock", "icon": "FiPackage", "permissions": ["HMS-P-HMSPS", "HMS-P-HMSPS-RW"] },
            { "name": "OP Pharmacy Stock", "route": "/OPPharmacyStock", "icon": "FiShoppingBag", "permissions": ["HMS-P-HMSPS"] },
            { "name": "Vendor Management", "route": "/VendorManagement", "icon": "FiTruck", "permissions": ["HMS-API-VM"] }
        ]
    },
    {
        "group": "Pharmacy",
        "order": 4,
        "pages": [
            { "name": "IP Pharmacy", "route": "/IPPharmacy", "icon": "FiPackage", "permissions": ["HMS-P-PH"] },
            { "name": "OP Pharmacy", "route": "/OPPharmacy", "icon": "FiShoppingBag", "permissions": ["HMS-P-PH"] },
            { "name": "IP GRN Generation", "route": "/IPGRNGeneration", "icon": "FiActivity", "permissions": ["HMS-API-GR", "HMS-API-GR-RW"] },
            { "name": "OP GRN Generation", "route": "/OPGRNGeneration", "icon": "FiActivity", "permissions": ["HMS-API-GR"] }
        ]
    },
    {
        "group": "Doctor Management",
        "order": 5,
        "pages": [
            { "name": "Doctors", "route": "/DoctorList", "icon": "FiUsers", "permissions": ["HMS-API-DRM", "HMS-API-DRM-RW"] }
        ]
    },
    {
        "group": "Investigation Billing",
        "order": 6,
        "pages": [
            { "name": "Billing Entry", "route": "/InvestigationBilling", "icon": "FiFileText", "permissions": ["HMS-API-IB", "HMS-API-IB-RW"] }
        ]
    },
    {
        "group": "Investigation Reports",
        "order": 7,
        "pages": [
            { "name": "CT Reports", "route": "/CTList", "icon": "FiActivity", "permissions": ["HMS-API-ICT", "HMS-API-ICT-RW"] },
            { "name": "MRI Reports", "route": "/MRIList", "icon": "FiActivity", "permissions": ["HMS-API-IMRI", "HMS-API-IMRI-RW"] },
            { "name": "USG Reports", "route": "/USGList", "icon": "FiActivity", "permissions": ["HMS-API-IUSG", "HMS-API-IUSG-RW"] },
            { "name": "X-Ray Reports", "route": "/XRayList", "icon": "FiActivity", "permissions": ["HMS-API-IXRAY", "HMS-API-IXRAY-RW"] }
        ]
    },
    {
        "group": "Rooms",
        "order": 8,
        "pages": [
            { "name": "Block", "route": "/Block", "icon": "FiHome", "permissions": ["HMS-P-BLK"] },
            { "name": "Room Category", "route": "/RoomCategory", "icon": "FiActivity", "permissions": ["HMS-P-RCAT"] },
            { "name": "Room", "route": "/Room", "icon": "FiHome", "permissions": ["HMS-P-RM"] },
            { "name": "Bed", "route": "/Bed", "icon": "FiActivity", "permissions": ["HMS-P-BED"] },
            { "name": "Service", "route": "/Service", "icon": "FiActivity", "permissions": ["HMS-P-SRV"] },
            { "name": "Room Enquiry", "route": "/RoomEnquiry", "icon": "FiActivity", "permissions": ["HMS-P-RENQ"] }
        ]
    },
    {
        "group": "Front Office",
        "order": 9,
        "pages": [
            { "name": "Admission", "route": "/Admission", "icon": "FiUserPlus", "permissions": ["HMS-P-BTD", "HMS-P-BTD-R"] },
            { "name": "Insurance Provider", "route": "/InsuranceProvider", "icon": "FiFileText", "permissions": ["HMS-P-HMSINS"] },
            { "name": "Enquiry", "route": "/Enquiry", "icon": "FiFileText", "permissions": ["HMS-P-ENQ"] },
            { "name": "Discharge Form", "route": "/DischargeForm", "icon": "FiLogOut", "permissions": ["HMS-API-SUM", "HMS-API-SUM-RW"] },
            { "name": "Discharge Summary", "route": "/Summary", "icon": "FiActivity", "permissions": ["HMS-API-SUM"] }
        ]
    },
    {
        "group": "Nursing Station",
        "order": 10,
        "pages": [
            { "name": "Room Shifting", "route": "/RoomShifting", "icon": "FiRepeat", "permissions": ["HMS-P-RSHFT"] }
        ]
    }
]

collection.insert_many(sidebar_data)
print("Successfully inserted sidebar mappings.")
