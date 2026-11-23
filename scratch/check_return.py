import os, datetime
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]
global_db = client["Global"]

salesreturn_collection = mongo_db["hospital_salesreturn"]
refund_collection = mongo_db["hospital_refund"]
ipadvance_refund_collection = mongo_db["hospital_ipadvance_refund"]
investrefund_collection = mongo_db["hospital_investrefund"]

current_date = datetime.date.today()
hospital_code = "SH001"
branch_code = "SHB001"
outlet_code = "OLET002"

salesreturn_docs = list(
    salesreturn_collection.find(
        {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "$or": [
                {"status": "Pending"},
                {
                    "status": "Paid",
                    "$expr": {
                        "$eq": [
                            {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": {"$ifNull": ["$paid_date", "$return_bill_date"]},
                                    "timezone": "Asia/Kolkata"
                                }
                            },
                            current_date.strftime("%Y-%m-%d")
                        ]
                    }
                }
            ]
        }
    )
)

print(f"Total salesreturn_docs returned: {len(salesreturn_docs)}")
doc_94 = [d for d in salesreturn_docs if d.get('return_bill_no') == '262702000094']
print(f"Return Bill 262702000094 included in API result: {len(doc_94) > 0}")
if doc_94:
    d = doc_94[0]
    print(f"  UHID: {d.get('uhid')}, Amount: {d.get('return_amount')}, Date: {d.get('return_bill_date')}, Status: {d.get('status')}")
