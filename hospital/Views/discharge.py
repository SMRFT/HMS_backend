from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128, ObjectId
from datetime import datetime, timezone
from django.shortcuts import get_object_or_404
import traceback
import logging
import json
import os
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission

from ..models import DischargeBilling, Patient
from ..serializers import DischargeBillingSerializer

import datetime


# ─────────────────────────────────────────────
# Financial Year
# ─────────────────────────────────────────────
def _financial_year():
    today = datetime.date.today()
    y = today.year
    if today.month >= 4:
        return f"{str(y)[2:]}{str(y+1)[2:]}"
    return f"{str(y-1)[2:]}{str(y)[2:]}"


# ─────────────────────────────────────────────
# Estimate Number Generator
# EST/YYMM/000001
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
        except:
            seq = 1

    return f"{prefix}{str(seq).zfill(6)}"


# ─────────────────────────────────────────────
# Bill Number Generator
# FY/DCH/000001
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
        except:
            seq = 1

    return f"{prefix}{str(seq).zfill(6)}"


# ─────────────────────────────────────────────
# Get Patient Details
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Get Patient Details
# ─────────────────────────────────────────────
def get_patient_details(uhid=None):

    if not uhid:
        return {}

    try:
        p = Patient.objects.get(uhid=uhid)

        return {
            "patient_name": f"{p.firstName} {p.lastName}".strip(),
            "age": p.age,
            "gender": p.gender,
            "mobile": p.mobilePhone
        }

    except Patient.DoesNotExist:
        return {}

# ═════════════════════════════════════════════
# LIST + CREATE BILLING
# ═════════════════════════════════════════════

@api_view(["GET","POST"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_list_create(request):

    # ───────────────────────── GET
    if request.method == "GET":

        qs = DischargeBilling.objects.filter(is_active=True)

        status_filter = request.GET.get("status")
        uhid = request.GET.get("uhid")
        ip_number = request.GET.get("ip_number")

        if status_filter:
            qs = qs.filter(status=status_filter)

        if uhid:
            qs = qs.filter(uhid=uhid)

        if ip_number:
            qs = qs.filter(ip_number=ip_number)

        data = DischargeBillingSerializer(qs, many=True).data

        for row in data:
            row["patient_details"] = get_patient_details(row.get("uhid"))

        return Response(data)


    # ───────────────────────── POST
    if request.method == "POST":

        data = request.data.copy()

        billing_status = data.get("status")

        if billing_status == "Estimate":
            data["estimate_number"] = generate_estimate_number()

        if billing_status == "Billed":
            data["bill_no"] = generate_bill_number()

        data["bill_date"] = timezone.now().date()

        serializer = DischargeBillingSerializer(data=data)

        if serializer.is_valid():

            obj = serializer.save()

            result = DischargeBillingSerializer(obj).data
            result["patient_details"] = get_patient_details(obj.uhid)

            return Response(result,status=status.HTTP_201_CREATED)

        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)



# ═════════════════════════════════════════════
# RETRIEVE / UPDATE / DELETE
# ═════════════════════════════════════════════

@api_view(["GET","PUT","PATCH","DELETE"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_detail(request,pk):

    billing = get_object_or_404(DischargeBilling,pk=pk,is_active=True)


    # ───────────────────────── GET
    if request.method == "GET":

        data = DischargeBillingSerializer(billing).data
        data["patient_details"] = get_patient_details(billing.uhid)

        return Response(data)


    # ───────────────────────── UPDATE
    if request.method in ["PUT","PATCH"]:

        if billing.status == "Billed":
            return Response(
                {"error":"Final bill cannot be edited"},
                status=status.HTTP_400_BAD_REQUEST
            )

        partial = request.method == "PATCH"

        serializer = DischargeBillingSerializer(
            billing,
            data=request.data,
            partial=partial
        )

        if serializer.is_valid():

            updated = serializer.save()

            data = DischargeBillingSerializer(updated).data
            data["patient_details"] = get_patient_details(updated.uhid)

            return Response(data)

        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)


    # ───────────────────────── DELETE (Soft)
    if request.method == "DELETE":

        billing.is_active = False
        billing.save(update_fields=["is_active"])

        return Response({"message":"Record deleted"})


# ═════════════════════════════════════════════
# CONVERT ESTIMATE → BILL
# ═════════════════════════════════════════════

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def convert_estimate_to_bill(request,pk):

    estimate = get_object_or_404(DischargeBilling,pk=pk,is_active=True)

    if estimate.status != "Estimate":
        return Response(
            {"error":"Only Estimate can be converted"},
            status=status.HTTP_400_BAD_REQUEST
        )


    bill = DischargeBilling.objects.create(

        status = "Billed",
        bill_no = generate_bill_number(),
        bill_date = timezone.now().date(),

        uhid = estimate.uhid,
        ip_number = estimate.ip_number,

        items = estimate.items,

        total_amount = estimate.total_amount,
        advance_amount = estimate.advance_amount,
        sales_return = estimate.sales_return,
        medicines_amount = estimate.medicines_amount,

        taxable_amount = estimate.taxable_amount,
        non_tax_amount = estimate.non_tax_amount,
        gst_amount = estimate.gst_amount,
        room_tax = estimate.room_tax,

        discount_percent = estimate.discount_percent,
        discount_amount = estimate.discount_amount,
        disc_reason = estimate.disc_reason,

        item_disc = estimate.item_disc,
        total_disc = estimate.total_disc,

        net_amount = estimate.net_amount,
        remarks = estimate.remarks,

        converted_from_id = estimate.pk,
        is_active = True
    )

    data = DischargeBillingSerializer(bill).data
    data["patient_details"] = get_patient_details(bill.uhid)

    return Response(data,status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_discharge_patient(request):
    """
    Search for a patient for discharge.
    Supports searching by UHID (OP Number) or IP Number.
    Priority:
    1. Active Admission (by IP or UHID)
    2. Patient Record (by UHID, for OP discharge if no admission found)
    """
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        admission_collection = db.hospital_admission
        patient_collection = db.hospital_patient
        
        uhid = request.GET.get('uhid', '').strip()
        ip_number = request.GET.get('ipNumber', '').strip()
        
        if not uhid and not ip_number:
            return Response({"error": "Please provide a search parameter (UHID or IP Number)"}, status=status.HTTP_400_BAD_REQUEST)

        results = []

        # 1. Search by IP Number (Strictly checks Admission)
        if ip_number:
            admissions = list(admission_collection.find({
                "ipNumber": {"$regex": ip_number, "$options": "i"}
            }))
            for adm in admissions:
                adm['id'] = str(adm['_id'])
                del adm['_id']
            results.extend(admissions)
            
        # 2. Search by UHID (OP Number)
        if uhid:
            # Check Admissions first
            admissions = list(admission_collection.find({
                "uhid": {"$regex": uhid, "$options": "i"}
            }))
            
            for adm in admissions:
                adm['id'] = str(adm['_id'])
                del adm['_id']
                # Avoid duplicates
                if not any(res.get('id') == adm.get('id') for res in results):
                    results.append(adm)
            
            # Check Patients
            patients = list(patient_collection.find({
                "uhid": {"$regex": uhid, "$options": "i"}
            }))
            
            for patient in patients:
                patient['id'] = str(patient['_id'])
                del patient['_id']
                # Check if this patient is already in results (via Admission)
                is_in_results = any(res.get('uhid') == patient.get('uhid') for res in results)
                if not is_in_results:
                    results.append(patient)

        return Response(results, status=status.HTTP_200_OK)
        
    except Exception as e:
        import traceback
        print("Error in search_discharge_patient:", e)
        print(traceback.format_exc())
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def discharge_detail_view(request):
    """
    GET: List all discharge records.
    POST: Create a new discharge record.
    """
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_dischargedetail
        
        if request.method == 'GET':
            discharge_details = list(collection.find().sort("lastmodified_date", -1))
            for detail in discharge_details:
                detail['id'] = str(detail['_id'])
                del detail['_id']
            return Response(discharge_details, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            from datetime import datetime
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['created_date'] = datetime.now()
            data['lastmodified_date'] = datetime.now()
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return Response(data, status=status.HTTP_201_CREATED)
            
    except Exception as e:
        import traceback
        print("Error in discharge_detail_view:", e)
        print(traceback.format_exc())
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

