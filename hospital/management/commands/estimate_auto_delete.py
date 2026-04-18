from django.core.management.base import BaseCommand
from datetime import datetime, timedelta
from pymongo import MongoClient
import os


class Command(BaseCommand):
    help = "Delete expired estimate bills, release stock, and log deletion"
    print("Delete expired estimate bills,")

    def handle(self, *args, **kwargs):

        # =====================================
        # ✅ MONGO CONFIG (YOUR PROVIDED SETUP)
        # =====================================
        MONGO_URI = os.getenv("GLOBAL_DB_HOST")
        DB_NAME = "HMS"

        client = MongoClient(MONGO_URI)
        mongo_db = client[DB_NAME]

        stock_collection = mongo_db["hospital_pharmacystock"]
        bill_collection = mongo_db["hospital_pharmacybilling"]
        log_collection = mongo_db["hospital_pharmacy_deleted_logs"]  

        now = datetime.utcnow()
        expiry_time = now - timedelta(hours=24)
        print("current time",now)

        # =====================================
        # ✅ FIND EXPIRED ESTIMATES
        # =====================================
        expired_bills = bill_collection.find({
            "billing_status": "Estimate",
            "created_date": {"$lte": expiry_time}
        })

        count = 0

        for bill in expired_bills:
            Bill_id = bill.get("Bill_id")

            hospital_code = bill.get("hospital_code")
            branch_code = bill.get("branch_code")
            outlet_code = bill.get("outlet_code")
            uhid = bill.get("uhid")


            medicines = bill.get("medicine_particulars", [])

            # =====================================
            # ✅ STOCK RESET (STRICT MATCH)
            # =====================================
            for med in medicines:
                item_id = med.get("item_id")
                batch_number = med.get("batch_number")
                qty = med.get("qty", 0)

                stock = stock_collection.find_one({
                    "item_id": item_id,
                    "batch_number": batch_number,
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code
                })
                print("stock",stock)

                if not stock:
                    print(
                        f"[WARNING] Stock not found | "
                        f"Bill: {Bill_id}, Item: {item_id}, Batch: {batch_number}"
                    )
                    continue

                current_blocked = stock.get("blocked_quantity", 0)
                print("current_blocked",current_blocked)

                # ✅ SAFE RELEASE
                release_qty = min(qty, current_blocked)

                if release_qty > 0:
                    stock_collection.update_one(
                        {"_id": stock["_id"]},
                        {"$inc": {"blocked_quantity": -release_qty}}
                    )

            # =====================================
            # ✅ LOGGING
            # =====================================
            log_collection.insert_one({
                "Bill_id": Bill_id,
                "deleted_at": datetime.utcnow(),
                "uhid":uhid,
                "reason": "Estimate expired after 24 hours",
                "medicine_particulars": medicines,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
            })

            # =====================================
            # ✅ DELETE BILL
            # =====================================
            bill_collection.delete_one({"Bill_id": Bill_id})

            count += 1

        self.stdout.write(
            self.style.SUCCESS(f"{count} expired bills deleted and stock restored")
        )