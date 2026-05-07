from pymongo import MongoClient, DESCENDING
import os
from rest_framework.decorators import api_view

from rest_framework.response import Response

from django.utils import timezone

import traceback

from datetime import datetime

from bson.decimal128 import Decimal128

from decimal import Decimal

from ..models import Cashcountershiftdetails

from ..serializers import CashcountershiftdetailsSerializer
def format_dt(val):
    if not val: return None
    if isinstance(val, str): return val
    try: return val.strftime("%Y-%m-%d %H:%M:%S")
    except: return str(val)
def safe_dec(val):
    if val is None: return Decimal('0.00')
    if hasattr(val, 'to_decimal'):
        try: return val.to_decimal()
        except: return Decimal('0.00')
    if isinstance(val, str):
        import re
        clean = re.sub(r'[^0-9\.\-]', '', val)
        try: return Decimal(clean or '0.00')
        except: return Decimal('0.00')
    try: return Decimal(str(val))
    except: return Decimal('0.00')

def get_shift_pymongo(query, sort_field=None):
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        col = db["hospital_cashcountershiftdetails"]
        
        sort_query = []
        if sort_field:
            sort_query = [(sort_field, DESCENDING)]
            
        doc = col.find_one(query, sort=sort_query)
        if doc:
            # Convert to model instance for compatibility
            from ..models import Cashcountershiftdetails
            doc.pop('_id', None)
            return Cashcountershiftdetails(**doc)
        return None
    except Exception as e:
        print(f"PyMongo Error: {e}")
        return None

# Auth/permissions

from pyauth.auth import HasRoleAndDataPermission

from rest_framework.decorators import api_view, permission_classes

# =========================================

# 🔢 SHIFT NUMBER GENERATOR (DJONGO SAFE)

# =========================================

def generate_shift_no():
    now = datetime.now()
    if now.month >= 4:
        start, end = now.year, now.year + 1
    else:
        start, end = now.year - 1, now.year
    fy = f"{str(start)[-2:]}{str(end)[-2:]}"

    from pymongo import MongoClient
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    col = db["hospital_cashcountershiftdetails"]
    shifts = list(col.find({"shiftno": {"$regex": f"^{fy}/"}}))
    
    last_number = 0
    for s in shifts:
        try:
            s_no = s.get("shiftno", "")
            if "/" in s_no:
                num_part = s_no.split("/")[1]
                num = int(num_part)
                if num > last_number: last_number = num
        except: continue
            
    new_number = last_number + 1
    return f"{fy}/{str(new_number).zfill(6)}"

def convert_decimal(value):

    if value is None:

        return 0.0

    if isinstance(value, Decimal128):

        return float(value.to_decimal())

    if isinstance(value, (Decimal, int, float)):

        return float(value)

    try:

        return float(value)

    except:

        return 0.0

def convert_decimal128(value):
    if value is None: return Decimal('0.00')
    if hasattr(value, 'to_decimal'): return value.to_decimal()
    if isinstance(value, str):
        clean = value.replace("“", "").replace("”", "").replace("₹", "").replace(",", "").strip()
        try: return Decimal(clean or '0.00')
        except: return Decimal('0.00')
    try: return Decimal(str(value))
    except: return Decimal('0.00')

# =====================================================

# ✅ RESPONSE FORMATTER

# =====================================================

def format_shift_response(shift):

    return {

        "shiftno": shift.shiftno,

        "CashierID": shift.CashierID,

        "CashCounter": shift.CashCounter,

        "OpeningBalance": convert_decimal(shift.OpeningBalance),

        "ClosingBalance": convert_decimal(shift.ClosingBalance),

        "collected_Amount": convert_decimal(shift.collected_Amount),

        "PettyCashBalance": convert_decimal(shift.PettyCashBalance),

        "RemittedToBank": convert_decimal(shift.RemittedToBank),

        "SubmittedToAccount": convert_decimal(shift.SubmittedToAccount),

        "SelectedOutlet": shift.SelectedOutlet,

        "ShiftStatus": shift.ShiftStatus,

        # ✅ FORMAT DATE TIME FOR UI

        "StartingTime": format_dt(shift.StartingTime),

        "closingTime": format_dt(shift.closingTime),

        "date": str(shift.date),

        "hospital_code": shift.hospital_code,

        "branch_code": shift.branch_code,

        "outlet_code": shift.outlet_code,

        "is_active": shift.is_active,

    }

def get_previous_shift_balance(cash_counter, hospital_code, branch_code):

    query = {
        "CashCounter": cash_counter,
        "hospital_code": hospital_code,
        "branch_code": branch_code,
        "ShiftStatus": "inactive"
    }
    last_shift = get_shift_pymongo(query, "closingTime")

    

    if last_shift:

        return convert_decimal(last_shift.ClosingBalance)

    return 0.0



def calculate_shift_collection(shift_no):

    """
    Calculates the total collected amount for a shift across all billing types.
    """
    total = 0.0

    try:

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        # 1. Billing (Registration/Consultation)

        docs = db["hospital_billing"].find({"shiftno": shift_no, "payment_status": "Paid"})

        for d in docs:

            total += convert_decimal(d.get("total_fees", 0))

        # 2. Investigation

        docs = db["hospital_investbilling"].find({"shiftno": shift_no, "paymentStatus": "Paid"})

        for d in docs:

            total += convert_decimal(d.get("finalPrice") or d.get("total") or 0)

            

        # 3. Discharge

        docs = db["hospital_dischargebilling"].find({"shiftno": shift_no, "status": "Paid"})

        for d in docs:

            total += convert_decimal(d.get("net_amount", 0))

            

        # 4. Pharmacy

        docs = db["hospital_pharmacybilling"].find({"shiftno": shift_no, "billing_status": "Paid"})

        for d in docs:

            total += convert_decimal(d.get("net_amount", 0))

            

        # 5. Receipt & Payment

        docs = db["hospital_receiptandpayment"].find({"shiftno": shift_no})

        for d in docs:

            amt = convert_decimal(d.get("amount", 0))

            if d.get("receipt_type") == "Receipt":

                total += amt

            elif d.get("receipt_type") == "Payment":

                total -= amt

        

        client.close()

    except Exception as e:

        print("Error calculating shift collection:", e)

            

    return total



# =====================================================

# ✅ MAIN API

# =====================================================

@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def cash_counter_shiftdetails(request):
    data = request.data
    employee_id   = data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID")
    hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
    branch_code   = data.get("auth-branch-code") or request.META.get("HTTP_BRANCH_CODE") or request.META.get("HTTP_AUTH_BRANCH_CODE")
    outlet_code   = data.get("auth-outlet-code") or request.META.get("HTTP_OUTLET_CODE") or request.META.get("HTTP_AUTH_OUTLET_CODE")

    if not employee_id:
        return Response({"success": False, "message": "User not authenticated"})

    if request.method == "POST":
        try:
            outlet_name = data.get("CashCounter")
            if outlet_name:
                # Bypassing ORM to avoid SQLDecodeError
                active_shift = get_shift_pymongo({
                    "CashCounter": outlet_name,
                    "ShiftStatus": "active",
                    "hospital_code": hospital_code,
                    "branch_code": branch_code
                })
                if active_shift:
                    return Response({
                        "success": False,
                        "message": f"An active shift already exists for {outlet_name}."
                    })
            
            shift_no = generate_shift_no()
            opening_balance = convert_decimal128(data.get("OpeningBalance"))
            if opening_balance == Decimal('0') and data.get("CashCounter"):
                opening_balance = Decimal(str(get_previous_shift_balance(
                    data.get("CashCounter"), hospital_code, branch_code
                )))

            payload = {
                "shiftno": shift_no, "CashierID": employee_id, "CashCounter": data.get("CashCounter"),
                "OpeningBalance": opening_balance, "PettyCashBalance": convert_decimal128(data.get("PettyCashBalance", 1000)),
                "StartingTime": data.get("StartingTime") or timezone.now(),
                "SelectedOutlet": data.get("SelectedOutlet") or data.get("CashCounter"),
                "ShiftStatus": "active", "created_by": employee_id, "created_date": timezone.now(),
                "date": timezone.now().date(), "hospital_code": hospital_code, "branch_code": branch_code,
                "outlet_code": outlet_code, "created_br": branch_code, "is_active": True,
            }

            print("DEBUG: POST Payload:", payload)
            serializer = CashcountershiftdetailsSerializer(data=payload)
            if serializer.is_valid():
                print("DEBUG: Serializer valid, saving...")
                serializer.save()
                print("DEBUG: Serializer saved.")
                shift = get_shift_pymongo({"shiftno": shift_no})
                if shift:
                    return Response({"success": True, "message": "Shift opened", "data": format_shift_response(shift)})
                else:
                    return Response({"success": False, "message": "Shift saved but retrieval failed."})
            return Response({"success": False, "message": "Validation error", "errors": serializer.errors})
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print("❌ POST SHIFT ERROR:\n", error_details)
            return Response({"success": False, "message": str(e), "traceback": error_details}, status=500)

    elif request.method == "PATCH":
        try:
            shift_no = data.get("shiftno")
            # Using global safe_dec

            shift = Cashcountershiftdetails.objects.get(shiftno=shift_no, ShiftStatus="active")
            shift.closingTime = data.get("closingTime") or timezone.now()
            collected = Decimal(str(calculate_shift_collection(shift_no)))
            
            shift.RemittedToBank = safe_dec(data.get("RemittedToBank"))
            shift.SubmittedToAccount = safe_dec(data.get("SubmittedToAccount"))
            shift.OpeningBalance = safe_dec(shift.OpeningBalance)
            shift.collected_Amount = safe_dec(collected)
            shift.OpeningBalance = safe_dec(shift.OpeningBalance)
            shift.ClosingBalance = safe_dec(shift.OpeningBalance + collected - safe_dec(data.get("RemittedToBank")) - safe_dec(data.get("SubmittedToAccount")))
            shift.PettyCashBalance = safe_dec(shift.PettyCashBalance)
            shift.RemittedToBank = safe_dec(data.get("RemittedToBank"))
            shift.SubmittedToAccount = safe_dec(data.get("SubmittedToAccount"))
            
            shift.ShiftStatus = "inactive"
            shift.is_active = False
            shift.lastmodified_by = employee_id
            shift.save()
            return Response({"success": True, "message": "Shift closed", "data": format_shift_response(shift)})
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print("❌ POST SHIFT ERROR:\n", error_details)
            return Response({"success": False, "message": str(e), "traceback": error_details}, status=500)


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_active_shift(request):
    try:
        data = request.data
        cash_counter = data.get("CashCounter") or request.META.get("HTTP_OUTLET_CODE")
        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = data.get("auth-branch-code") or request.META.get("HTTP_BRANCH_CODE")
        
        today = timezone.now().date()
        # Bypassing Djongo ORM for the active shift query to avoid SQLDecodeError
        query = {
            "CashCounter": cash_counter,
            "ShiftStatus": "active",
            "is_active": True,
            "hospital_code": hospital_code,
            "branch_code": branch_code
        }
        # If the date filter is causing issues, we can check it manually after fetch
        # Removing date restriction: if a shift is active, it must be closed regardless of date
        shift = get_shift_pymongo(query, "StartingTime")

        if not shift:
            expected = get_previous_shift_balance(cash_counter, hospital_code, branch_code)
            return Response({
                "success": False, "message": "No active shift found",
                "expected_opening": expected, "default_petty_cash": 1000.0, "is_active": False
            })

        # Using global safe_dec

        # Thoroughly clean all decimal fields before saving to avoid Decimal128/String conflicts
        shift.collected_Amount = safe_dec(calculate_shift_collection(shift.shiftno))
        shift.OpeningBalance = safe_dec(shift.OpeningBalance)
        shift.ClosingBalance = safe_dec(shift.ClosingBalance)
        shift.PettyCashBalance = safe_dec(shift.PettyCashBalance)
        shift.RemittedToBank = safe_dec(shift.RemittedToBank)
        shift.SubmittedToAccount = safe_dec(shift.SubmittedToAccount)
        shift.save()
        
        return Response({"success": True, "data": format_shift_response(shift)})
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("❌ get_active_shift ERROR:\n", error_details)
        return Response({"success": False, "message": str(e), "traceback": error_details}, status=500)

from rest_framework.decorators import api_view

from rest_framework.response import Response

from pymongo import MongoClient

import os



MONGO_URI = os.getenv("GLOBAL_DB_HOST")

DB_NAME = "HMS"

COLLECTION_NAME = "hospital_Receiptpayment"



client = MongoClient(MONGO_URI)

mongo_db = client[DB_NAME]

outlet_collection = mongo_db[COLLECTION_NAME]





@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def get_active_account_heads(request):

    try:

        # ✅ AUTH DATA (your requirement)

        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE") 

        branch_code   = request.data.get("auth-branch-code")   

        outlet_code   = request.data.get("auth-outlet-code")  



        # 🔍 Build query dynamically

        query = {

            "is_active": True

        }



        # ✅ Add filters only if present

        if hospital_code:

            query["hospital_code"] = hospital_code

        if branch_code:

            query["branch_code"] = branch_code

        if outlet_code:

            query["outlet_code"] = outlet_code



        # 🔎 Fetch data

        data = list(outlet_collection.find(query))



        # ✅ Convert MongoDB types

        for item in data:

            item["_id"] = str(item["_id"])

            if "created_date" in item and item["created_date"]:

                item["created_date"] = item["created_date"].isoformat()



        return Response({

            "status": "success",

            "count": len(data),

            "data": data

        })



    except Exception as e:

        return Response({

            "status": "error",

            "message": str(e)

        }, status=500)

    







def generate_voucher_no():

    last_record = ReceiptAndPayment.objects.order_by('-voucher_no').first()



    if last_record and last_record.voucher_no.isdigit():

        next_no = int(last_record.voucher_no) + 1

    else:

        next_no = 1



    return str(next_no).zfill(8)  # 00000001 format





from rest_framework.decorators import api_view

from rest_framework.response import Response

from ..models import ReceiptAndPayment

from ..serializers import ReceiptAndPaymentSerializer





@api_view(["POST"])

@permission_classes([HasRoleAndDataPermission])

def post_receipt_payments(request):

    try:

        data = request.data



        # ✅ AUTH DATA

        employee_id   = data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID") or request.META.get("HTTP_AUTH_USER_ID")

        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")

        branch_code   = data.get("auth-branch-code") or request.META.get("HTTP_BRANCH_CODE") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE"))

        outlet_code   = data.get("auth-outlet-code") or request.META.get("HTTP_OUTLET_CODE") or (request.META.get("HTTP_AUTH_OUTLET_CODE") or request.META.get("HTTP_OUTLET_CODE"))



        # ✅ REQUIRED FIELDS FROM FRONTEND

        receipt_type = data.get("receipt_type")

        account_head = data.get("account_head")

        description  = data.get("description")

        amount       = data.get("amount")

        cash_counter = data.get("CashCounter") or request.META.get("HTTP_OUTLET_CODE")

        shiftno      = data.get("shiftno")



        # 🔴 Validation

        if not all([receipt_type, account_head, amount, cash_counter, shiftno]):

            return Response({

                "status": "error",

                "message": "Missing required fields"

            }, status=400)



        # ✅ Generate voucher number

        voucher_no = generate_voucher_no()



        # ✅ Create record

        obj = ReceiptAndPayment.objects.create(

            receipt_type = receipt_type,

            account_head = account_head,

            description  = description,

            amount       = amount,

            voucher_no   = voucher_no,

            CashCounter  = cash_counter,

            shiftno      = shiftno,



            # ✅ From backend

            CashierID    = employee_id,

            created_by   = employee_id,

            hospital_code = hospital_code,

            branch_code   = branch_code,

            outlet_code   = outlet_code

        )



        serializer = ReceiptAndPaymentSerializer(obj)



        return Response({

            "status": "success",

            "message": "Receipt/Payment created successfully",

            "data": serializer.data

        })



    except Exception as e:

        return Response({

            "status": "error",

            "message": str(e)

        }, status=500)

    





from rest_framework.decorators import api_view, permission_classes

from rest_framework.response import Response

from bson.decimal128 import Decimal128

from bson import ObjectId

from pymongo import MongoClient

from django.utils import timezone

import os, json





@api_view(["POST"])

@permission_classes([HasRoleAndDataPermission])

def get_receipt_payments(request):

    try:

        data = request.data



        employee_id   = data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID") or request.META.get("HTTP_AUTH_USER_ID")

        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")

        branch_code   = data.get("auth-branch-code") or request.META.get("HTTP_BRANCH_CODE") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE"))

        outlet_code   = data.get("auth-outlet-code") or request.META.get("HTTP_OUTLET_CODE") or (request.META.get("HTTP_AUTH_OUTLET_CODE") or request.META.get("HTTP_OUTLET_CODE"))



        if not employee_id:

            return Response({"status": "error", "message": "User not authenticated"}, status=401)



        # ✅ DATE FILTER

        from datetime import datetime, time, timedelta

        today = timezone.localdate()

        start = datetime.combine(today, time.min)

        end   = start + timedelta(days=1)



        # ✅ DB CONNECTION

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

        db = client["HMS"]



        transaction_col = db["hospital_receiptandpayment"]

        account_col     = db["hospital_Receiptpayment"]



        # ✅ FETCH DATA

        transactions = list(transaction_col.find({

            "voucher_date": {"$gte": start, "$lt": end},

            "hospital_code": hospital_code,

            "branch_code": branch_code,

            "outlet_code": outlet_code

        }).sort("voucher_no", -1))



        account_heads = list(account_col.find({

            "hospital_code": hospital_code,

            "branch_code": branch_code,

            "outlet_code": outlet_code,

            "is_active": True

        }))



        # ✅ ACCOUNT MAP

        account_map = {

            str(item.get("S.No")): item.get("account_head")

            for item in account_heads

        }



        result = []



        for t in transactions:

            # ✅ CONVERT FULL DOCUMENT

            doc = {}



            for key, value in t.items():



                # ObjectId → string

                if isinstance(value, ObjectId):

                    doc[key] = str(value)



                # Decimal128 → float

                elif isinstance(value, Decimal128):

                    doc[key] = float(value.to_decimal())



                # datetime → ISO format

                elif hasattr(value, "isoformat"):

                    doc[key] = value.isoformat()



                # description JSON string → dict

                elif key == "description" and isinstance(value, str):

                    try:

                        doc[key] = json.loads(value)

                    except:

                        doc[key] = value



                else:

                    doc[key] = value



            # ✅ ADD ENRICHED ACCOUNT HEAD

            acc_no = str(t.get("account_head"))

            doc["account_head_details"] = {

                "no": acc_no,

                "name": account_map.get(acc_no, "Unknown")

            }



            result.append(doc)



        return Response({

            "status": "success",

            "count": len(result),

            "data": result

        })



    except Exception as e:

        return Response({

            "status": "error",

            "message": str(e)

        }, status=500)













from rest_framework.decorators import api_view, permission_classes

from rest_framework.response import Response

from rest_framework import status

from pymongo import MongoClient

from bson.decimal128 import Decimal128

import os



client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

db = client["HMS"]



billing_col = db["hospital_billing"]

invest_col = db["hospital_investbilling"]

discharge_col = db["hospital_dischargebilling"]

patient_col = db["hospital_patient"]



from bson import ObjectId

from bson.decimal128 import Decimal128



def serialize_mongo(doc):

    if isinstance(doc, list):

        return [serialize_mongo(i) for i in doc]



    if isinstance(doc, dict):

        new_doc = {}

        for k, v in doc.items():

            if isinstance(v, ObjectId):

                new_doc[k] = str(v)   # ✅ FIX ObjectId

            elif isinstance(v, Decimal128):

                new_doc[k] = float(v.to_decimal())  # ✅ FIX Decimal128

            elif isinstance(v, (dict, list)):

                new_doc[k] = serialize_mongo(v)

            else:

                new_doc[k] = v

        return new_doc



    return doc

# ==========================================

# ✅ COMMON DECIMAL CONVERTER

# ==========================================

def convert_decimal(value):

    if isinstance(value, Decimal128):

        return float(value.to_decimal())

    try:

        return float(value)

    except:

        return 0.0

    



from datetime import datetime, timedelta



today = datetime.utcnow().date()



start = datetime.combine(today, datetime.min.time())

end = datetime.combine(today + timedelta(days=1), datetime.min.time())





@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def get_mainblock_pendingbills(request):

    try:

        data = request.data



        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")

        branch_code = data.get("auth-branch-code")

        



        final_data = []



        # ============================

        # ✅ CURRENT DATE FILTER

        # ============================

        from datetime import datetime, timedelta



        today = datetime.utcnow().date()

        start = datetime.combine(today, datetime.min.time())

        end = datetime.combine(today + timedelta(days=1), datetime.min.time())



        # =====================================================

        # 1. BILLING (billed_date)

        # =====================================================

        billing_query = {

            "hospital_code": hospital_code,

            "branch_code": branch_code,

            "payment_status": "Pending",

            "billed_date": {

                "$gte": start,

                "$lt": end

            }

        }



        billing_docs = list(billing_col.find(billing_query))



        for bill in billing_docs:

            patient = patient_col.find_one({

                "id": bill.get("patient_id"),

                "hospital_code": hospital_code,

                "branch_code": branch_code

            })



            final_data.append({

                "type": "Billing",

                "bill_no": bill.get("bill_number"),

                "uhid": patient.get("uhid") if patient else None,

                "patient_name": (

                    f"{patient.get('firstName')} {patient.get('lastName')}"

                    if patient else None

                ),

                "amount": convert_decimal(bill.get("total_fees")),

                "status": bill.get("payment_status"),

                "date": bill.get("billed_date"),

                "raw": serialize_mongo(bill)

            })



        # =====================================================

        # 2. INVESTIGATION (investBillDate)

        # =====================================================

        invest_query = {

            "hospital_code": hospital_code,

            "branch_code": branch_code,

            "paymentMethod": "Cash",

            "paymentStatus": "Pending",

            "investBillDate": {

                "$gte": start,

                "$lt": end

            }

        }



        invest_docs = list(invest_col.find(invest_query))



        for inv in invest_docs:

            patient = patient_col.find_one({

                "uhid": inv.get("uhid"),

                "hospital_code": hospital_code,

                "branch_code": branch_code

            })



            final_data.append({

                "type": "Investigation",

                "bill_no": inv.get("investBillNo"),

                "uhid": inv.get("uhid"),

                "patient_name": (

                    f"{patient.get('firstName')} {patient.get('lastName')}"

                    if patient else None

                ),

                "amount": convert_decimal(inv.get("finalPrice")),

                "status": inv.get("paymentStatus"),

                "date": inv.get("investBillDate"),  

                "raw": serialize_mongo(inv)

            })



        # =====================================================

        # 3. DISCHARGE (bill_date)

        # =====================================================

        discharge_query = {

            "hospital_code": hospital_code,

            "branch_code": branch_code,

            "status": "Billed",

            "bill_date": {

                "$gte": start,

                "$lt": end

            }

        }



        discharge_docs = list(discharge_col.find(discharge_query))



        for dis in discharge_docs:

            patient = patient_col.find_one({

                "uhid": dis.get("uhid"),

                "hospital_code": hospital_code,

                "branch_code": branch_code

            })



            final_data.append({

                "type": "Discharge",

                "bill_no": dis.get("bill_no"),

                "uhid": dis.get("uhid"),

                "patient_name": (

                    f"{patient.get('firstName')} {patient.get('lastName')}"

                    if patient else None

                ),

                "amount": convert_decimal(dis.get("net_amount")),

                "status": dis.get("status"),

                "date": dis.get("bill_date"),

                "items": serialize_mongo(dis.get("items", [])),

                "raw": serialize_mongo(dis)

            })



        return Response({

            "status": "success",

            "count": len(final_data),

            "data": final_data

        }, status=status.HTTP_200_OK)



    except Exception as e:

        return Response({

            "status": "error",

            "message": str(e)

        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    







from rest_framework.decorators import api_view, permission_classes

from rest_framework.response import Response

from rest_framework import status

from pymongo import MongoClient

from bson.decimal128 import Decimal128

from datetime import datetime

import os



client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

db = client["HMS"]



billing_col    = db["hospital_billing"]

invest_col     = db["hospital_investbilling"]

discharge_col  = db["hospital_dischargebilling"]





@api_view(["POST"])

@permission_classes([HasRoleAndDataPermission])

def update_mainblock_pendingbills(request):

    """

    Update payment status + insert payment_details for a pending bill.



    Expected body:

    {

        "bill_no":         "BL-20240427-001",   # required

        "type":            "Billing",            # required: "Billing" | "Investigation" | "Discharge"

        "payment_details": {                     # required

            "method":      "cash"|"card"|"cheque"|"Multiple Payment",

            "Paid_amount": 5000,

            "card_no":     "ICICIBANK2102",      # optional

            "cheque_no":   "CHQ001",             # optional

            "breakdown":   [...]                 # optional, for multiple payment

        },

        "shiftno":         "SH-001",             # optional

        "pendingAmount":   0                     # optional — stored when partial payment

    }

    """

    try:

        data            = request.data

        hospital_code   = data.get("auth-hospital-code")

        branch_code     = data.get("auth-branch-code")

        employee_id   = data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID") or request.META.get("HTTP_AUTH_USER_ID")

        CashierID = employee_id

        



        bill_no         = data.get("bill_no")

        payment_details = data.get("payment_details")

        shiftno         = data.get("shiftno", "")

        pending_amount  = data.get("pendingAmount", 0)



        # Accept "type" or "bill_type" from frontend

        bill_type = data.get("type") or data.get("bill_type")



        # Infer type from field names present in the payload

        # e.g. frontend sends "paymentStatus" -> Investigation

        #                     "payment_status" -> Billing

        #                     "status"         -> Discharge

        if not bill_type:

            if data.get("paymentStatus"):

                bill_type = "Investigation"

            elif data.get("payment_status"):

                bill_type = "Billing"

            elif data.get("status"):

                bill_type = "Discharge"



        # Infer type from bill_no prefix as last fallback

        # e.g. "2526/DCH/000005" -> Discharge

        #      "2526/INV/000005" -> Investigation

        #      "2526/BIL/000005" -> Billing

        if not bill_type and bill_no:

            upper = bill_no.upper()

            if "DCH" in upper or "DIS" in upper:

                bill_type = "Discharge"

            elif "INV" in upper:

                bill_type = "Investigation"

            elif "BIL" in upper or "/BL" in upper or upper.startswith("BL"):

                bill_type = "Billing"



        # ── Validation ────────────────────────────────────────────────────────

        if not bill_no:

            return Response({"status": "error", "message": "bill_no is required."},

                            status=status.HTTP_400_BAD_REQUEST)



        if not bill_type:

            return Response({

                "status": "error",

                "message": "Could not determine bill type. Please send 'type': 'Billing' | 'Investigation' | 'Discharge'."

            }, status=status.HTTP_400_BAD_REQUEST)



        if not payment_details or not isinstance(payment_details, dict):

            return Response({"status": "error", "message": "payment_details is required."},

                            status=status.HTTP_400_BAD_REQUEST)



        if bill_type not in ("Billing", "Investigation", "Discharge"):

            return Response(

                {"status": "error",

                 "message": f"Invalid type '{bill_type}'. Must be Billing, Investigation, or Discharge."},

                status=status.HTTP_400_BAD_REQUEST

            )



        paid_amount = float(payment_details.get("Paid_amount", 0))

        if paid_amount <= 0:

            return Response({"status": "error", "message": "Paid_amount must be greater than 0."},

                            status=status.HTTP_400_BAD_REQUEST)



        # ── Enrich payment_details with meta ─────────────────────────────────

        paid_at = datetime.utcnow().isoformat()



        # ── Route by type ─────────────────────────────────────────────────────



        # =====================================================================

        # 1. BILLING  →  hospital_billing

        #    filter : bill_number  |  status field : payment_status

        # =====================================================================

        if bill_type == "Billing":

            query = {

                "hospital_code": hospital_code,

                "branch_code":   branch_code,

                "bill_number":   bill_no,

                "payment_status": "Pending",

            }



            new_status = "Paid" if pending_amount == 0 else "Partial"



            update = {

                "$set": {

                    "payment_status":  new_status,

                    "payment_details": payment_details,

                    "shiftno":         shiftno,

                    "paid_at":         paid_at,

                    "CashierID":       CashierID, 

                    **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),

                }

            }



            result = billing_col.update_one(query, update)



            if result.matched_count == 0:

                return Response(

                    {"status": "error",

                     "message": f"No Pending Billing bill found with bill_no '{bill_no}'."},

                    status=status.HTTP_404_NOT_FOUND

                )



            return Response({

                "status":  "success",

                "message": f"Billing bill '{bill_no}' updated to '{new_status}'.",

                "bill_no": bill_no,

                "type":    "Billing",

                "new_payment_status": new_status,

                "pendingAmount": pending_amount,

                "payment_details": payment_details,

            }, status=status.HTTP_200_OK)



        # =====================================================================

        # 2. INVESTIGATION  →  hospital_investbilling

        #    filter : investBillNo  |  status field : paymentStatus

        # =====================================================================

        elif bill_type == "Investigation":

            query = {

                "hospital_code": hospital_code,

                "branch_code":   branch_code,

                "investBillNo":  bill_no,

                "paymentStatus": "Pending",

            }



            new_status = "Paid" if pending_amount == 0 else "Partial"



            update = {

                "$set": {

                    "paymentStatus":   new_status,

                    "payment_details": payment_details,

                    "shiftno":         shiftno,

                    "paid_at":         paid_at,

                    "CashierID":       CashierID,

                    **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),

                }

            }



            result = invest_col.update_one(query, update)



            if result.matched_count == 0:
                return Response(
                    {"status": "error",
                     "message": f"No Pending Investigation bill found with bill_no '{bill_no}'."},
                    status=status.HTTP_404_NOT_FOUND)
            return Response({
                "status": "success",
                "message": f"Investigation bill '{bill_no}' updated to '{new_status}'.",
                "bill_no": bill_no,
                "type":"Investigation",
                "new_payment_status": new_status,
                "pendingAmount": pending_amount,
                "payment_details": payment_details,
            }, status=status.HTTP_200_OK)

        # =====================================================================
        # 3. DISCHARGE  →  hospital_dischargebilling
        # =====================================================================
        elif bill_type == "Discharge":
            query = {
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "bill_no":       bill_no,
            }
            new_status = "Paid" if pending_amount == 0 else "Partial"
            update = {
                "$set": {
                    "status":                   new_status,
                    "items.$[].payment_status": new_status,
                    "payment_details":          payment_details,
                    "shiftno":                  shiftno,
                    "paid_at":                  paid_at,
                    "CashierID":                CashierID,
                    **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),
                }
            }
            result = discharge_col.update_one(query, update)
            if result.matched_count == 0:
                return Response(
                    {"status": "error",
                     "message": f"No Discharge bill found with bill_no '{bill_no}'."},
                    status=status.HTTP_404_NOT_FOUND
                )
            return Response({
                "status":  "success",
                "message": f"Discharge bill '{bill_no}' status updated to '{new_status}'.",
                "bill_no": bill_no,
                "type":    "Discharge",
                "new_payment_status": new_status,
                "pendingAmount": pending_amount,
                "payment_details": payment_details,
            }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "status":  "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def get_shift_summary_report(request):
    try:
        data = request.data
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = data.get("auth-branch-code")
        queryset = Cashcountershiftdetails.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        )
        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)
        shifts = queryset.order_by("-date", "-StartingTime")
        cashier_ids = list(set([s.CashierID for s in shifts]))
        cashier_name_map = {}
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client['Global']
            profiles = list(db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            client.close()
        except:
            pass
        report_data = []
        for s in shifts:
            res = format_shift_response(s)
            res["User"] = cashier_name_map.get(s.CashierID, s.CashierID)
            # Format times for report display
            res["StartTime"] = s.StartingTime.strftime("%I.%M%p").lower() if s.StartingTime else ""
            res["EndTime"] = s.closingTime.strftime("%I.%M%p").lower() if s.closingTime else ""
            report_data.append(res)
        return Response({
            "success": True,
            "data": report_data
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("❌ get_active_shift ERROR:\n", error_details)
        return Response({"success": False, "message": str(e), "traceback": error_details}, status=500)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_registration_bills(request):
    try:
        # S &  AUTH DATA (Robust header check)
        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = request.data.get("auth-branch-code") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE")) or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE")) or request.META.get("HTTP_BRANCH_CODE")
        # ================================
        # S &  FILTER BILLING DATA
        # ================================
        from ..models import Billing
        filter_query = {
            "payment_status": "Pending"
        }
        if hospital_code is not None:
            filter_query["hospital_code"] = hospital_code
        if branch_code is not None:
            filter_query["branch_code"] = branch_code
        # Using ORM for Registration bills as they are natively in Django
        bills = Billing.objects.select_related('patient').filter(**filter_query).order_by('-billed_date')
        response_data = []
        # ================================
        # S &  BUILD RESPONSE
        # ================================
        for index, bill in enumerate(bills, start=1):
            patient = bill.patient
            billed_date = bill.billed_date
            date_str = billed_date.strftime("%d-%m-%Y") if billed_date else None
            time_str = billed_date.strftime("%H:%M:%S") if billed_date else None

            response_data.append({
                "Sl No": index,
                "Date": date_str,
                "Time": time_str,
                "Bill No": bill.bill_number,
                "Bill Type": "Registration",
                "UHID No": patient.uhid if patient else None,
                "Patient": f"{patient.firstName} {patient.lastName}" if patient else None,
                "Ip Number": getattr(patient, "ip_number", None),
                "total_fees": convert_decimal(bill.total_fees),
                "payment_status": bill.payment_status
            })

        return Response({
            "status": True,
            "count": len(response_data),
            "data": response_data
        }, status=status.HTTP_200_OK)
    except Exception as e:
        import traceback
        return Response({
            "status": False,
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

