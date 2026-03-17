from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from django.utils.timezone import now
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from bson import ObjectId
import os
import datetime
import json as _json

from ..models import DischargeBilling, Patient, Admission
from ..serializers import DischargeBillingSerializer


# ─────────────────────────────────────────────
# MongoDB connection
# ─────────────────────────────────────────────
def get_mongo_db():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
    return client["HMS"]


# ─────────────────────────────────────────────
# Financial Year  e.g. 2526
# ─────────────────────────────────────────────
def _financial_year():
    today = datetime.date.today()
    y = today.year
    if today.month >= 4:
        return f"{str(y)[2:]}{str(y+1)[2:]}"
    return f"{str(y-1)[2:]}{str(y)[2:]}"


# ─────────────────────────────────────────────
# Estimate Number Generator  EST/YYMM/000001
# ─────────────────────────────────────────────
def generate_estimate_number():
    today = datetime.date.today()
    prefix = f"EST/{str(today.year)[2:]}{str(today.month).zfill(2)}/"
    last = (
        DischargeBilling.objects
        .filter(estimate_number__startswith=prefix)
        .order_by("estimate_number")
        .last()
    )
    seq = 1
    if last and last.estimate_number:
        try:
            seq = int(last.estimate_number.split("/")[-1]) + 1
        except Exception:
            seq = 1
    return f"{prefix}{str(seq).zfill(6)}"


# ─────────────────────────────────────────────
# Bill Number Generator  FY/DCH/000001
# ─────────────────────────────────────────────
def generate_bill_number():
    prefix = f"{_financial_year()}/DCH/"
    last = (
        DischargeBilling.objects
        .filter(bill_no__startswith=prefix)
        .order_by("bill_no")
        .last()
    )
    seq = 1
    if last and last.bill_no:
        try:
            seq = int(last.bill_no.split("/")[-1]) + 1
        except Exception:
            seq = 1
    return f"{prefix}{str(seq).zfill(6)}"


# ─────────────────────────────────────────────
# Patient + Admission helper
# ─────────────────────────────────────────────
def _build_patient_info(patient, admission=None):
    info = {
        "patient_name": f"{patient.firstName} {patient.lastName}".strip(),
        "uhid":         patient.uhid,
        "age":          patient.age,
        "gender":       patient.gender,
        "mobile":       patient.mobilePhone,
        "patient_type": patient.customer_type,
        "company":      getattr(patient, "company_code", "") or "",
        "doctor":       patient.doctorName or "",
        "ip_number":    "",
        "room_no":      "",
        "total_days":   0,
        "admission_date": "",
    }
    if admission:
        info["ip_number"] = admission.ipNumber or ""
        info["room_no"]   = (
            f"{admission.roomNo}/{admission.bedNo}"
            if admission.bedNo
            else admission.roomNo or ""
        )
        info["doctor"] = admission.admittingDoctor or patient.doctorName or ""
        if admission.admissionDateTime:
            info["admission_date"] = admission.admissionDateTime.strftime("%d-%m-%Y")
            delta = (datetime.date.today() - admission.admissionDateTime.date()).days
            info["total_days"] = delta
    return info


# ─────────────────────────────────────────────
# Search Discharge Patient
# GET /search-discharge-patient/
# Query params: uhid=  OR  ipNumber=
#
# Logic:
#  1. Resolve Patient from UHID (or via Admission if ipNumber given)
#  2. Find active Admission (is_admissionActive=True, is_discharged=False)
#  3. Fetch Credit+Pending investigation items from hospital_investbilling
#     filtered by the resolved ip_number
# ─────────────────────────────────────────────
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from bson import ObjectId
import json as _json

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
import json as _json

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
import json as _json

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def search_discharge_patient(request):

    uhid = request.GET.get("uhid", "").strip()
    ip_number = request.GET.get("ipNumber", "").strip()

    if not uhid and not ip_number:
        return Response(
            {"error": "Provide uhid or ipNumber"},
            status=status.HTTP_400_BAD_REQUEST
        )

    db = get_mongo_db()
    invest_collection = db["hospital_investbilling"]

    # ─────────────────────────────────────
    # 1. Resolve Patient
    # ─────────────────────────────────────
    patient = None

    try:
        if uhid:
            patient = Patient.objects.filter(uhid=uhid).first()

        elif ip_number:
            admission_ref = Admission.objects.filter(ipNumber=ip_number).first()

            if not admission_ref:
                return Response(
                    {"error": "Admission not found for given IP number"},
                    status=status.HTTP_404_NOT_FOUND
                )

            patient = Patient.objects.filter(uhid=admission_ref.uhid).first()

        if not patient:
            return Response(
                {"error": "Patient not found"},
                status=status.HTTP_404_NOT_FOUND
            )

    except Exception as e:
        return Response(
            {"error": f"Patient lookup failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # ─────────────────────────────────────
    # 2. Get Admission (latest admission)
    # ─────────────────────────────────────
    admission = None

    try:
        if ip_number:
            admission = Admission.objects.filter(
                ipNumber=ip_number
            ).first()

        else:
            admission = (
                Admission.objects
                .filter(uhid=patient.uhid)
                .order_by("-admissionDateTime")
                .first()
            )

    except Exception:
        admission = None


    # ─────────────────────────────────────
    # 3. Build Patient Info
    # ─────────────────────────────────────
    patient_info = {
        "uhid": patient.uhid,
        "patient_name": f"{getattr(patient,'firstName','')} {getattr(patient,'lastName','')}".strip(),
        "age": getattr(patient, "age", ""),
        "gender": getattr(patient, "gender", ""),
        "mobile": getattr(patient, "mobilePhone", ""),
        "ipNumber": admission.ipNumber if admission else None,
    }


    # ─────────────────────────────────────
    # 4. Fetch Pending Credit Bills (MongoDB)
    # ─────────────────────────────────────
    effective_ip = ip_number or (admission.ipNumber if admission else None)

    if effective_ip:
        query = {
            "ipNumber": effective_ip,
            "paymentMethod": "Credit",
            "paymentStatus": "Pending",
            "is_active": True
        }
    else:
        query = {
            "uhid": patient.uhid,
            "paymentMethod": "Credit",
            "paymentStatus": "Pending",
            "is_active": True
        }

    raw_bills = list(invest_collection.find(query))


    # ─────────────────────────────────────
    # 5. Flatten Bill Items
    # ─────────────────────────────────────
    invest_items = []

    for bill in raw_bills:

        bill_no = bill.get("investBillNo", "")
        doctor = bill.get("doctor", "")
        raw_items = bill.get("item", [])

        if isinstance(raw_items, str):
            try:
                raw_items = _json.loads(raw_items)
            except Exception:
                raw_items = []

        for it in raw_items:

            invest_items.append({
                "invest_bill_no": bill_no,
                "bill_object_id": str(bill.get("_id")),
                "itemName": it.get("itemName", ""),
                "price": float(it.get("price", 0) or 0),
                "quantity": int(it.get("quantity", 1) or 1),
                "billTypeNo": it.get("billTypeNo", ""),
                "test_id": it.get("test_id"),
                "doctor": doctor,
                "payment_status": bill.get("paymentStatus", ""),
                "package_name": it.get("packageName", "") or bill.get("packageName", ""),
            })


    # ─────────────────────────────────────
    # 6. Final Response
    # ─────────────────────────────────────
    return Response({
        "patient": patient_info,
        "invest_items": invest_items
    })


# ═════════════════════════════════════════════
# LIST + CREATE  BILLING
# ═════════════════════════════════════════════
@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_list_create(request):

    # ───────────────── GET
    if request.method == "GET":
        qs = DischargeBilling.objects.filter(is_active=True)

        status_filter = request.GET.get("status")
        uhid          = request.GET.get("uhid")
        ip_number     = request.GET.get("ip_number")

        if status_filter:
            qs = qs.filter(status=status_filter)
        if uhid:
            qs = qs.filter(uhid=uhid)
        if ip_number:
            qs = qs.filter(ip_number=ip_number)

        data = DischargeBillingSerializer(qs, many=True).data

        # Enrich with patient name
        for row in data:
            try:
                p = Patient.objects.get(uhid=row.get("uhid"))
                row["patient_details"] = {
                    "patient_name": f"{p.firstName} {p.lastName}".strip(),
                    "age":    p.age,
                    "gender": p.gender,
                    "mobile": p.mobilePhone,
                }
            except Patient.DoesNotExist:
                row["patient_details"] = {}

        return Response(data)

    # ───────────────── POST
    if request.method == "POST":
        data           = request.data.copy()
        billing_status = data.get("status")

        if billing_status == "Estimate":
            data["estimate_number"] = generate_estimate_number()
        elif billing_status == "Billed":
            data["bill_no"] = generate_bill_number()

        data["bill_date"] = now().date()

        serializer = DischargeBillingSerializer(data=data)
        if serializer.is_valid():
            obj    = serializer.save()
            result = DischargeBillingSerializer(obj).data
            try:
                p = Patient.objects.get(uhid=obj.uhid)
                result["patient_details"] = {
                    "patient_name": f"{p.firstName} {p.lastName}".strip(),
                    "age":    p.age,
                    "gender": p.gender,
                    "mobile": p.mobilePhone,
                }
            except Patient.DoesNotExist:
                result["patient_details"] = {}
            return Response(result, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ═════════════════════════════════════════════
# RETRIEVE / UPDATE / DELETE
# ═════════════════════════════════════════════
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_detail(request, pk):

    billing = get_object_or_404(DischargeBilling, pk=pk, is_active=True)

    if request.method == "GET":
        data = DischargeBillingSerializer(billing).data
        try:
            p = Patient.objects.get(uhid=billing.uhid)
            data["patient_details"] = {
                "patient_name": f"{p.firstName} {p.lastName}".strip(),
                "age": p.age, "gender": p.gender, "mobile": p.mobilePhone,
            }
        except Patient.DoesNotExist:
            data["patient_details"] = {}
        return Response(data)

    if request.method in ["PUT", "PATCH"]:
        if billing.status == "Billed":
            return Response(
                {"error": "Final bill cannot be edited"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        partial    = request.method == "PATCH"
        serializer = DischargeBillingSerializer(billing, data=request.data, partial=partial)
        if serializer.is_valid():
            updated = serializer.save()
            data    = DischargeBillingSerializer(updated).data
            try:
                p = Patient.objects.get(uhid=updated.uhid)
                data["patient_details"] = {
                    "patient_name": f"{p.firstName} {p.lastName}".strip(),
                    "age": p.age, "gender": p.gender, "mobile": p.mobilePhone,
                }
            except Patient.DoesNotExist:
                data["patient_details"] = {}
            return Response(data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "DELETE":
        billing.is_active = False
        billing.save(update_fields=["is_active"])
        return Response({"message": "Record deleted"})


# ═════════════════════════════════════════════
# CONVERT ESTIMATE → BILL
# ═════════════════════════════════════════════
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def convert_estimate_to_bill(request, pk):

    estimate = get_object_or_404(DischargeBilling, pk=pk, is_active=True)

    if estimate.status != "Estimate":
        return Response(
            {"error": "Only Estimate can be converted"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    bill = DischargeBilling.objects.create(
        status            = "Billed",
        bill_no           = generate_bill_number(),
        bill_date         = now().date(),
        uhid              = estimate.uhid,
        ip_number         = estimate.ip_number,
        items             = estimate.items,
        total_amount      = estimate.total_amount,
        advance_amount    = estimate.advance_amount,
        sales_return      = estimate.sales_return,
        medicines_amount  = estimate.medicines_amount,
        taxable_amount    = estimate.taxable_amount,
        non_tax_amount    = estimate.non_tax_amount,
        gst_amount        = estimate.gst_amount,
        room_tax          = estimate.room_tax,
        discount_percent  = estimate.discount_percent,
        discount_amount   = estimate.discount_amount,
        disc_reason       = estimate.disc_reason,
        item_disc         = estimate.item_disc,
        total_disc        = estimate.total_disc,
        net_amount        = estimate.net_amount,
        remarks           = estimate.remarks,
        converted_from_id = estimate.pk,
        is_active         = True,
    )

    data = DischargeBillingSerializer(bill).data
    try:
        p = Patient.objects.get(uhid=bill.uhid)
        data["patient_details"] = {
            "patient_name": f"{p.firstName} {p.lastName}".strip(),
            "age": p.age, "gender": p.gender, "mobile": p.mobilePhone,
        }
    except Patient.DoesNotExist:
        data["patient_details"] = {}

    return Response(data, status=status.HTTP_201_CREATED)