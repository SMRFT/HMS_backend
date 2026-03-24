from django.http import JsonResponse
from pymongo import MongoClient
import os

from bson import ObjectId
from ..models import Patient,PharmacyStock
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db import DatabaseError

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission

# MongoDB Configuration
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_oppharmacystock"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
collection = mongo_db[COLLECTION_NAME]

from bson.decimal128 import Decimal128

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal128):
        return float(obj.to_decimal())
    return obj

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_oppharmacy_stock(request):
    try:

        pipeline = [

    {
        "$match": {
            "department_code": "OP001"
        }
    },

    {
        "$lookup": {
            "from": "hospital_pharmacyitem",
            "localField": "item_id",
            "foreignField": "item_id",
            "as": "item_details"
        }
    },
    {
        "$unwind": {
            "path": "$item_details",
            "preserveNullAndEmptyArrays": False
        }
    },

    {
        "$match": {
            "item_details.is_blocked": False,
            "item_details.is_active": True
        }
    },

    {
        "$addFields": {
            "available_stock": {
                "$add": [
                    {
                        "$subtract": [
                            {
                                "$subtract": [
                                    {
                                        "$subtract": [
                                            {
                                                "$subtract": [
                                                    "$total_stock",
                                                    {"$ifNull": ["$sold_quantity", 0]}
                                                ]
                                            },
                                            {"$ifNull": ["$transferred_out_quantity", 0]}
                                        ]
                                    },
                                    {"$ifNull": ["$grn_return_quantity", 0]}
                                ]
                            },
                            {"$ifNull": ["$blocked_quantity", 0]}
                        ]
                    },
                    {"$ifNull": ["$sales_return_quantity", 0]}
                ]
            }
        }
    },

    {
        "$project": {
            "_id": 0,
            "org_id": 1,
            "branch_code": 1,
            "department_code": 1,
            "item_id": 1,
            "batch_number": 1,
            "expiry_date": 1,
            "total_stock": 1,
            "mrp": 1,
            "grn_number": 1,
            "sold_quantity": 1,
            "transferred_out_quantity": 1,
            "sales_return_quantity": 1,
            "available_stock": 1,

            "item_name": "$item_details.item_name",
            "item_last_name": "$item_details.item_last_name",
            "category": "$item_details.category",
            "reorder_level": "$item_details.reorder_level",
            "hsn_code": "$item_details.hsn",

            "CGST_Percentage": 1,
            "SGST_Percentage": 1,
            "CGST_Amt": 1,
            "SGST_Amt": 1
        }
    }
]

        data = list(mongo_db["hospital_pharmacystock"].aggregate(pipeline))

        data = convert_decimals(data)   # ✅ convert Decimal128 → float

        return JsonResponse(data, safe=False)

    except Exception as e:
        print("Error:", str(e))
        return JsonResponse({"error": str(e)}, status=500)



from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
import pytz

from ..models import OPPharmacyBill



def sanitize_medicines(medicines):

    clean = []

    for med in medicines:

        if not med:
            continue

        price = med.get("price") or med.get("Price") or 0

        clean.append({
            "item_id": int(med.get("item_id")),
            "item_name": str(med.get("item_name", "")),
            "batch_number": str(med.get("batch_number")),
            "expiry_date": str(med.get("expiry_date", "")),
            "qty": int(med.get("qty", 0)),
            "price": float(price)
        })

    return clean
# ----------------------------------------------------------
# STOCK BLOCK UPDATE
# ----------------------------------------------------------

def adjust_blocked_stock(old_meds, new_meds, department_code="OP001"):

    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    stock_collection = db["hospital_pharmacystock"]

    old_map = {(m["item_id"], m["batch_number"]): m for m in old_meds}
    new_map = {(m["item_id"], m["batch_number"]): m for m in new_meds}

    keys = set(old_map.keys()).union(set(new_map.keys()))

    for key in keys:

        old_qty = float(old_map.get(key, {}).get("qty", 0))
        new_qty = float(new_map.get(key, {}).get("qty", 0))

        diff = new_qty - old_qty

        if diff == 0:
            continue

        item_id, batch_number = key

        stock_collection.update_one(
            {
                "department_code": department_code,
                "item_id": int(item_id),
                "batch_number": str(batch_number)
            },
            {
                "$inc": {"blocked_quantity": diff}
            }
        )


# ----------------------------------------------------------
# MAIN SAVE API
# ----------------------------------------------------------

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_oppharmacy_bill(request):

    data = request.data

    medicines = sanitize_medicines(data.get("medicine_particulars", []))

    status = data.get("status")  # Estimate / Billed
    estimate_no = data.get("estimate_no")

    employee_id = data.get("auth-user-id")

    total_amount = float(data.get("total_amount", 0))
    net_amount = float(data.get("net_amount", 0))

    discount_type = data.get("overall_discount_type")
    discount_value = float(data.get("overall_discount_value", 0))
    discount_amount = float(data.get("overall_discount_amount", 0))

    bill_type = data.get("bill_type")
    bill_name = data.get("bill_name")
    doctor_id = data.get("doctor_id")
    room_no = data.get("room_no")

    patient_name = data.get("patient_name")
    uhid = data.get("uhid")
    inpatient_number = data.get("inpatient_number")

    department_code = "OP001"

    # ======================================================
    # 1️⃣ DIRECT BILL
    # ======================================================

    if status == "Billed" and not estimate_no:

        bill_no = get_last_oppharmacy_billno(get_financial_year())

        OPPharmacyBill.objects.create(

            bill_no=bill_no,
            estimate_no=None,

            patient_name=patient_name,
            uhid=uhid,
            inpatient_number=inpatient_number,

            bill_type=bill_type,
            bill_name=bill_name,

            doctor_id=doctor_id,
            room_no=room_no,

            medicine_particulars=medicines,

            total_amount=total_amount,
            overall_discount_type=discount_type,
            overall_discount_value=discount_value,
            overall_discount_amount=discount_amount,
            net_amount=net_amount,

            billing_status="Billed",
            billing_mode="DIRECT",

            cashier_id=employee_id
        )

        # block stock
        adjust_blocked_stock([], medicines, department_code)

        return Response({
            "success": True,
            "bill_no": bill_no
        })

    # ======================================================
    # 5️⃣ CONVERT BILL → ESTIMATE
    # ======================================================

    if status == "Estimate" and data.get("bill_no"):

        bill = OPPharmacyBill.objects.filter(
            bill_no=data.get("bill_no")
        ).first()

        if not bill:
            return Response({
                "success": False,
                "error": "Bill not found"
            })

        old_medicines = bill.medicine_particulars or []

        # adjust stock
        adjust_blocked_stock(old_medicines, medicines, department_code)

        # Capture history
        history_snapshot = {
            "type": "Bill to Estimate Conversion",
            "medicine_particulars": old_medicines,
            "total_amount": bill.total_amount,
            "overall_discount_type": bill.overall_discount_type,
            "overall_discount_value": bill.overall_discount_value,
            "overall_discount_amount": bill.overall_discount_amount,
            "net_amount": bill.net_amount,
            "billing_status": bill.billing_status,
            "modified_by": employee_id,
            "modified_at": timezone.now().astimezone(pytz.timezone("Asia/Kolkata")).isoformat()
        }

        if bill.edit_history is None:
            bill.edit_history = []
        
        bill.edit_history.append(history_snapshot)

        # Update to Estimate
        bill.billing_status = "Estimated"
        bill.billing_mode = "ESTIMATE"
        
        if not bill.estimate_no:
            bill.estimate_no = generate_estimate_no()

        bill.patient_name = patient_name
        bill.uhid = uhid
        bill.inpatient_number = inpatient_number

        bill.bill_type = bill_type
        bill.bill_name = bill_name

        bill.doctor_id = doctor_id
        bill.room_no = room_no

        bill.medicine_particulars = medicines

        bill.total_amount = total_amount
        bill.overall_discount_type = discount_type
        bill.overall_discount_value = discount_value
        bill.overall_discount_amount = discount_amount
        bill.net_amount = net_amount

        bill.save()

        return Response({
            "success": True,
            "estimate_no": bill.estimate_no
        })

    # ======================================================
    # 2️⃣ CREATE ESTIMATE
    # ======================================================

    if status == "Estimate" and not estimate_no:

        estimate_no = generate_estimate_no()

        OPPharmacyBill.objects.create(

            bill_no="",
            estimate_no=estimate_no,

            patient_name=patient_name,
            uhid=uhid,
            inpatient_number=inpatient_number,

            bill_type=bill_type,
            bill_name=bill_name,

            doctor_id=doctor_id,
            room_no=room_no,

            medicine_particulars=medicines,

            total_amount=total_amount,
            overall_discount_type=discount_type,
            overall_discount_value=discount_value,
            overall_discount_amount=discount_amount,
            net_amount=net_amount,

            billing_status="Estimated",
            billing_mode="ESTIMATE",

            cashier_id=employee_id
        )

        # block stock
        adjust_blocked_stock([], medicines, department_code)

        return Response({
            "success": True,
            "estimate_no": estimate_no
        })

    # ======================================================
    # 3️⃣ EDIT ESTIMATE
    # ======================================================

    if status == "Estimate" and estimate_no:

        estimate = OPPharmacyBill.objects.filter(
            estimate_no=estimate_no
        ).first()

        if not estimate:
            return Response({
                "success": False,
                "error": "Estimate not found"
            })

        old_medicines = estimate.medicine_particulars or []

        # adjust blocked qty
        adjust_blocked_stock(old_medicines, medicines, department_code)

        # Capture current state for history before updating
        history_snapshot = {
            "medicine_particulars": old_medicines,
            "total_amount": estimate.total_amount,
            "overall_discount_type": estimate.overall_discount_type,
            "overall_discount_value": estimate.overall_discount_value,
            "overall_discount_amount": estimate.overall_discount_amount,
            "net_amount": estimate.net_amount,
            "modified_by": employee_id,
            "modified_at": timezone.now().astimezone(pytz.timezone("Asia/Kolkata")).isoformat()
        }

        if estimate.edit_history is None:
            estimate.edit_history = []
        
        estimate.edit_history.append(history_snapshot)



        estimate.patient_name = patient_name
        estimate.uhid = uhid
        estimate.inpatient_number = inpatient_number

        estimate.bill_type = bill_type
        estimate.bill_name = bill_name

        estimate.doctor_id = doctor_id
        estimate.room_no = room_no

        estimate.medicine_particulars = medicines

        estimate.total_amount = total_amount
        estimate.overall_discount_type = discount_type
        estimate.overall_discount_value = discount_value
        estimate.overall_discount_amount = discount_amount
        estimate.net_amount = net_amount

        estimate.save()


        return Response({
            "success": True,
            "estimate_no": estimate.estimate_no
        })

    # ======================================================
    # 4️⃣ CONVERT ESTIMATE → BILL
    # ======================================================

    if status == "Billed" and estimate_no:

        estimate = OPPharmacyBill.objects.filter(
            estimate_no=estimate_no
        ).first()

        if not estimate:

            return Response({
                "success": False,
                "error": "Estimate not found"
            })

        old_medicines = estimate.medicine_particulars or []

        bill_no = get_last_oppharmacy_billno(get_financial_year())

        # adjust stock ONLY IF modified
        adjust_blocked_stock(old_medicines, medicines, department_code)

        estimate.bill_no = bill_no
        estimate.billing_status = "Billed"
        estimate.billing_mode = "ESTIMATE"

        estimate.patient_name = patient_name
        estimate.uhid = uhid
        estimate.inpatient_number = inpatient_number

        estimate.bill_type = bill_type
        estimate.bill_name = bill_name

        estimate.doctor_id = doctor_id
        estimate.room_no = room_no

        estimate.medicine_particulars = medicines

        estimate.total_amount = total_amount
        estimate.overall_discount_type = discount_type
        estimate.overall_discount_value = discount_value
        estimate.overall_discount_amount = discount_amount
        estimate.net_amount = net_amount

        estimate.save()

        return Response({
            "success": True,
            "bill_no": bill_no
        })

    return Response({
        "success": False,
        "error": "Invalid request"
    })



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_BillType(request):
    client = MongoClient(MONGO_URI)
    db = client["HMS"]

    stock_collection = db["hospital_billtype"]

    cursor = stock_collection.find(
        {
            "billing_outlet": "PHARMACY",
            "is_active": True
        }
    )

    billtypes = list(cursor)

    # Convert ObjectId to string (important)
    for bill in billtypes:
        bill["_id"] = str(bill["_id"])

    return Response({
        "status": True,
        "data": billtypes
    })

from datetime import date

def get_financial_year():
    today = date.today()
    year = today.year

    if today.month >= 4:  # April onwards
        start = year % 100
        end = (year + 1) % 100
    else:
        start = (year - 1) % 100
        end = year % 100

    return f"{start:02d}{end:02d}"


# @api_view(["GET"])
# @permission_classes([HasRolePermission])
# def generate_oppharmacy_billno(request):
#     fy = get_financial_year()
#     bill_no = get_last_oppharmacy_billno(fy)

#     return Response({
#         "bill_no": bill_no,
#         "financial_year": fy
#     })



from ..models import OPPharmacyBill

def get_last_oppharmacy_billno(fy):
    last_bill = (
        OPPharmacyBill.objects
        .filter(bill_no__startswith=f"{fy}/")
        .order_by("-bill_no")
        .first()
    )

    if not last_bill:
        return f"{fy}/000001"

    last_no = int(last_bill.bill_no.split("/")[-1])
    next_no = last_no + 1

    return f"{fy}/{next_no:06d}"



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_last_billed_uhid(request):

    # 1️⃣ Get latest bill
    last_bill = (
        OPPharmacyBill.objects
        .order_by("-bill_date")
        .first()
    )

    if not last_bill:
        return Response({
            "success": False,
            "message": "No records found"
        })

    # 2️⃣ Get patient using UHID
    patient = Patient.objects.filter(uhid=last_bill.uhid).first()

    if not patient:
        return Response({
            "success": False,
            "message": "Patient not found"
        })

    # 3️⃣ Prepare full response
    full_name = f"{patient.salutation or ''} {patient.firstName or ''} {patient.lastName or ''}".strip()

    return Response({
        "success": True,
        "data": {
            # 🔹 Patient Details
            "uhid": patient.uhid,
            "patient_name": full_name,
            "inpatient_number": patient.ip_number,
            "age": patient.age,
            "gender": patient.gender,
            "mobile": patient.mobilePhone,
            "city": patient.city,
            "blood_group": patient.blood_group,

            # 🔹 Bill Details
            "doctor_id": last_bill.doctor_id,
            "room_no": last_bill.room_no,
            "bill_type": last_bill.bill_type,
            "bill_name": last_bill.bill_name,
            "bill_no": last_bill.bill_no,
            "bill_date": last_bill.bill_date,
        }
    })


from django.db.models import Max
@permission_classes([HasRoleAndDataPermission])
def generate_estimate_no():
    last = OPPharmacyBill.objects.aggregate(
        Max("estimate_no")
    )["estimate_no__max"]

    if last:
        next_no = int(last) + 1
    else:
        next_no = 1

    return f"{next_no:06d}" 


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_oppharmacy_estimate(request):

    data = request.data.copy()

    # ✅ Get employee id from auth payload
    employee_id = data.get("auth-user-id")

    # ✅ Indian Timezone (IST)
    india_tz = pytz.timezone("Asia/Kolkata")
    now_ist = timezone.now().astimezone(india_tz)

    # ✅ Add audit fields
    data["created_by"] = employee_id
    data["created_date"] = now_ist   # timezone-aware datetime
    data["is_active"] = True

    serializer = OPPharmacyEstimatebillSerializer(data=data)

    if serializer.is_valid():
        estimate = serializer.save(
            estimate_no=generate_estimate_no()  # ✅ AUTO estimate no
        )

        return Response(
            {
                "success": True,
                "estimate_no": estimate.estimate_no
            },
            status=201
        )

    return Response(serializer.errors, status=400)



from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_active_estimates(request):
  
    estimates = OPPharmacyEstimatebill.objects.all()
    active_estimates = [obj for obj in estimates if obj.is_active == True]
    serializer = OPPharmacyEstimatebillSerializer(active_estimates, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)



from ..models import PharmacyItem
import json

@api_view(["GET"])
def get_estimate_bills(request):
    try:

        bills = OPPharmacyBill.objects.filter(billing_status="Estimated")
        data = []

        for bill in bills:

            meds = bill.medicine_particulars

            # ✅ Handle both string and list
            if isinstance(meds, str):
                meds = json.loads(meds)

            particulars = []

            for med in meds:
                item_id = med.get("item_id")
                batch_no = med.get("batch_number")

                item = PharmacyItem.objects.filter(item_id=item_id).first()

                particulars.append({
                    "item_id": item_id,
                    "item_name": item.item_name if item else "",
                    "batch_number": batch_no,
                    "qty": med.get("qty"),
                    "Price": med.get("Price"),
                })

            data.append({
                "created_date": bill.created_date,
                "lastmodified_date": bill.lastmodified_date,
                "created_by": bill.created_by,
                "lastmodified_by": bill.lastmodified_by,
                "patient_name": bill.patient_name,
                "bill_no": bill.bill_no,
                "estimate_no": bill.estimate_no,
                "bill_date": bill.bill_date,
                "uhid": bill.uhid,
                "inpatient_number": bill.inpatient_number,
                "bill_type": bill.bill_type,
                "bill_name": bill.bill_name,
                "doctor_id": bill.doctor_id,
                "room_no": bill.room_no,
                "medicine_particulars": particulars,
                "total_amount": bill.total_amount,
                "overall_discount_type": bill.overall_discount_type,
                "overall_discount_value": bill.overall_discount_value,
                "overall_discount_amount": bill.overall_discount_amount,
                "net_amount": bill.net_amount,
                "billing_status": bill.billing_status,
                "billing_mode": bill.billing_mode,
                "payment_details": bill.payment_details,
                "cashier_id": bill.cashier_id,
            })

        return Response(data)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
import pytz

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def convert_estimate_to_bill(request, estimate_no):

    estimate = OPPharmacyEstimatebill.objects.get(
        estimate_no=estimate_no,
        is_active=True
    )

    medicines = json.loads(estimate.medicine_particulars)

    converted_items = []

    for m in medicines:
        converted_items.append({
            "item_id": m.get("item_id"),
            "batch_number": m.get("batch"),
            "qty": m.get("quantity"),
            "Price": m.get("mrp")
        })

    data = {
        "patient_name": estimate.patient_name,
        "uhid": estimate.uhid,
        "inpatient_number": estimate.inpatient_number,
        "doctor_id": estimate.doctor_id,
        "room_no": estimate.room_no,
        "bill_type": estimate.bill_type,
        "bill_name": estimate.bill_name,
        "medicine_particulars": converted_items,
        "net_amount": estimate.net_amount
    }

    # deactivate estimate
    estimate.is_active = False
    estimate.save()

    return Response({
        "success": True,
        "data": data
    })




from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import OPPharmacyBill
from ..serializers import OPPharmacyBillSerializer

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def OPPharmacy_pending_bills(request):
    bills = OPPharmacyBill.objects.filter(billing_status="Billed")
    serializer = OPPharmacyBillSerializer(bills, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)



from decimal import Decimal, InvalidOperation
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def collect_oppharmacy_payment(request):
    bill_no = request.data.get("bill_no")
    bill_type = request.data.get("bill_type")
    payments = request.data.get("payments", {})

    # ✅ Cashier from token
    cashier_id = request.data.get("auth-user-id")

    if not bill_no or not bill_type:
        return Response(
            {"error": "bill_no and bill_type are required"},
            status=400
        )

    bill = OPPharmacyBill.objects.filter(
        bill_no=bill_no,
        bill_type=bill_type,
        billing_status="Billed"
    ).order_by("-bill_date").first()

    if not bill:
        return Response(
            {"error": "Bill not found or already paid"},
            status=400
        )

    payment_amount_fields = ["cash", "cheque", "card"]
    total_paid = Decimal("0.00")

    for field in payment_amount_fields:
        try:
            total_paid += Decimal(str(payments.get(field, 0) or 0))
        except InvalidOperation:
            return Response(
                {"error": f"Invalid amount for {field}"},
                status=400
            )

    if total_paid != bill.net_amount:
        return Response(
            {"error": "Payment amount mismatch"},
            status=400
        )

    # ✅ UPDATE CORRECT FIELDS
    bill.billing_status = "Paid"
    bill.payment_details = payments
    bill.cashier_id = cashier_id
    bill.lastmodified_by = cashier_id
    bill.lastmodified_date = timezone.now()

    bill.save(update_fields=[
        "billing_status",
        "payment_details",
        "cashier_id",
        "lastmodified_by",
        "lastmodified_date"
    ])

    return Response({
        "success": True,
        "message": "Payment completed successfully",
        "bill_no": bill.bill_no,
        "bill_type": bill.bill_type,
        "cashier_id": cashier_id
    })



