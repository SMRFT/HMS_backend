from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from pyauth.auth import HasRoleAndDataPermission
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, date
import re
from bson import ObjectId, Decimal128

from .dbcollection import (
    hms_db,
    hospital_tumour_board_collection,
    hospital_tumour_template_collection,
    patient_collection,
    admission_collection,
    get_employee_name_by_id,
    resolve_created_by_name,
    extract_aud_employee_id,
)

# ── Serialization Helper ───────────────────────────────────────────────────────

def serialize_doc(doc):
    if doc is None:
        return None
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    elif isinstance(doc, Decimal128):
        return float(doc.to_decimal())
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, (datetime, date)):
        return doc.isoformat()
    return doc


# ── Default Template Definition ───────────────────────────────────────────────

DEFAULT_TUMOUR_BOARD_TEMPLATE = {
    "template_id": 1,
    "template_name": "TUMOUR BOARD CERTIFICATE",
    "is_template": True,
    "version": "1.0",
    "description": "Multidisciplinary Tumour Board Clinical Assessment & Certification for AB-PMJAY / CMCHIS / CGHS / State Health Schemes",
    "created_date": "2026-11-02T10:00:00",
    "header_fields": [
        {
            "key": "meeting_date",
            "label": "Date of Board Meeting",
            "type": "date",
            "required": True,
            "grid_cols": 3,
        },
        {
            "key": "tms_case_ref_no",
            "label": "TMS Case/Ref. No",
            "type": "text",
            "placeholder": "Enter TMS Case/Ref No",
            "required": False,
            "grid_cols": 3,
        },
        {
            "key": "patient_name",
            "label": "Patient Name",
            "type": "text",
            "placeholder": "Patient Full Name",
            "required": True,
            "grid_cols": 4,
        },
        {
            "key": "age",
            "label": "Age",
            "type": "text",
            "placeholder": "Age",
            "required": True,
            "grid_cols": 1,
        },
        {
            "key": "gender",
            "label": "Gender",
            "type": "select",
            "value_options": ["Male", "Female", "Other"],
            "required": True,
            "grid_cols": 1,
        },
        {
            "key": "scheme_name",
            "label": "Scheme Name",
            "type": "select",
            "value_options": ["CMCHIS", "PM-JAY", "CGHS", "Other Scheme"],
            "default_value": "CMCHIS",
            "required": True,
            "grid_cols": 3,
        },
        {
            "key": "ip_op_number",
            "label": "IPD / Registration No",
            "type": "text",
            "placeholder": "Enter IPD / Reg No",
            "required": False,
            "grid_cols": 3,
        },
        {
            "key": "uhid",
            "label": "UHID No",
            "type": "text",
            "placeholder": "Enter UHID",
            "required": True,
            "grid_cols": 3,
        },
        {
            "key": "phone",
            "label": "Contact Phone",
            "type": "text",
            "placeholder": "Mobile Number",
            "required": False,
            "grid_cols": 3,
        },
        {
            "key": "scheme_card_id",
            "label": "Patient Scheme Card ID / URN / Beneficiary ID",
            "type": "text",
            "placeholder": "Scheme Card ID / URN / Beneficiary ID",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "primary_referral_dept",
            "label": "Primary Referral Department",
            "type": "text",
            "placeholder": "e.g. Surgical Oncology / Medical Oncology",
            "required": False,
            "grid_cols": 3,
        },
        {
            "key": "treating_consultant",
            "label": "Treating Consultant",
            "type": "text",
            "placeholder": "Treating Consultant Doctor",
            "required": False,
            "grid_cols": 3,
        },
    ],
    "fields": [
        # Section 1: CLINICAL DIAGNOSIS & STAGING
        {
            "key": "site_of_malignancy",
            "label": "Site of Malignancy",
            "type": "text",
            "section": "1. CLINICAL DIAGNOSIS & STAGING",
            "placeholder": "Enter primary site of malignancy (e.g. Right Breast Upper Outer Quadrant, Rectum, Tongue)",
            "default_value": "",
            "required": True,
            "grid_cols": 12,
        },
        {
            "key": "histopathology_ihc_details",
            "label": "Histopathology (HPE) / IHC Report Details",
            "type": "textarea",
            "section": "1. CLINICAL DIAGNOSIS & STAGING",
            "placeholder": "Enter biopsy findings, morphology, IHC markers (ER, PR, HER2, Ki-67, etc.)...",
            "default_value": "",
            "required": False,
            "grid_cols": 12,
            "rows": 3,
        },
        {
            "key": "tnm_staging",
            "label": "TNM Staging: TNM [          ]",
            "type": "text",
            "section": "1. CLINICAL DIAGNOSIS & STAGING",
            "placeholder": "e.g. cT2 N1 M0 / pT3 N2a M0",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "stage",
            "label": "Stage: [ I / II / III / IV ]",
            "type": "select",
            "section": "1. CLINICAL DIAGNOSIS & STAGING",
            "value_options": [
                "Stage I",
                "Stage II",
                "Stage III",
                "Stage IV",
            ],
            "default_value": "Stage II",
            "required": True,
            "grid_cols": 6,
        },

        # Section 2: PROPOSED ONCOLOGY PACKAGE DETAILS
        {
            "key": "package_code",
            "label": "PM-JAY Package Code",
            "type": "text",
            "section": "2. PROPOSED ONCOLOGY PACKAGE DETAILS",
            "placeholder": "Enter PM-JAY / CMCHIS Package Code",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "procedure_regimen_name",
            "label": "Name of Procedure / Regimen",
            "type": "text",
            "section": "2. PROPOSED ONCOLOGY PACKAGE DETAILS",
            "placeholder": "Enter procedure name or chemotherapy regimen",
            "default_value": "",
            "required": True,
            "grid_cols": 6,
        },

        # Section 3: MULTI-MODAL MANAGEMENT PLAN APPROVED BY THE BOARD
        {
            "key": "surgical_oncology",
            "label": "Surgical Oncology Plan",
            "type": "checkbox_text",
            "section": "3. MULTI-MODAL MANAGEMENT PLAN APPROVED BY THE BOARD",
            "check_label": "Surgical Oncology",
            "placeholder": "Details of surgical procedure, margins...",
            "default_value": "",
            "checked_default": False,
            "required": False,
            "grid_cols": 12,
        },
        {
            "key": "medical_oncology",
            "label": "Medical Oncology Plan",
            "type": "checkbox_text",
            "section": "3. MULTI-MODAL MANAGEMENT PLAN APPROVED BY THE BOARD",
            "check_label": "Medical Oncology",
            "placeholder": "Details of chemotherapy regimen, cycles, dosage...",
            "default_value": "",
            "checked_default": False,
            "required": False,
            "grid_cols": 12,
        },
        {
            "key": "radiation_oncology",
            "label": "Radiation Oncology Plan",
            "type": "checkbox_text",
            "section": "3. MULTI-MODAL MANAGEMENT PLAN APPROVED BY THE BOARD",
            "check_label": "Radiation Oncology",
            "placeholder": "Details of radiotherapy dose, fractions, technique (IMRT/VMAT/SRS)...",
            "default_value": "",
            "checked_default": False,
            "required": False,
            "grid_cols": 12,
        },
        {
            "key": "palliative_care",
            "label": "Palliative Care Plan",
            "type": "checkbox_text",
            "section": "3. MULTI-MODAL MANAGEMENT PLAN APPROVED BY THE BOARD",
            "check_label": "Palliative Care",
            "placeholder": "Details of symptom control, pain management, supportive care...",
            "default_value": "",
            "checked_default": False,
            "required": False,
            "grid_cols": 12,
        },

        # Section 4: SPECIFIC RECOMMENDATIONS / BOARD REMARKS
        {
            "key": "board_remarks",
            "label": "4. SPECIFIC RECOMMENDATIONS / BOARD REMARKS",
            "type": "textarea",
            "section": "4. SPECIFIC RECOMMENDATIONS / BOARD REMARKS",
            "placeholder": "Enter detailed multidisciplinary tumour board recommendations, sequencing of therapies, review dates...",
            "default_value": "",
            "required": True,
            "grid_cols": 12,
            "rows": 5,
        },

        # Section 5: BOARD CERTIFICATION & SIGNATURES
        {
            "key": "certification_statement",
            "label": "Board Certification Statement",
            "type": "declaration",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "default_value": "We hereby certify that the case details of the aforementioned patient have been reviewed thoroughly by the Multidisciplinary Tumour Board, and the recommended treatment modalities conform to established oncology guidelines for standard patient care.",
            "required": True,
            "grid_cols": 12,
        },
        {
            "key": "medical_oncologist_name",
            "label": "Medical Oncologist Name",
            "type": "text",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "placeholder": "Dr. Name",
            "default_value": "",
            "required": False,
            "grid_cols": 4,
        },
        {
            "key": "medical_oncologist_reg",
            "label": "Medical Oncologist Reg. No",
            "type": "text",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "placeholder": "Reg. No",
            "default_value": "",
            "required": False,
            "grid_cols": 2,
        },
        {
            "key": "radiation_oncologist_name",
            "label": "Radiation Oncologist Name",
            "type": "text",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "placeholder": "Dr. Name",
            "default_value": "",
            "required": False,
            "grid_cols": 4,
        },
        {
            "key": "radiation_oncologist_reg",
            "label": "Radiation Oncologist Reg. No",
            "type": "text",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "placeholder": "Reg. No",
            "default_value": "",
            "required": False,
            "grid_cols": 2,
        },
        {
            "key": "surgical_oncologist_name",
            "label": "Surgical Oncologist Name",
            "type": "text",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "placeholder": "Dr. Name",
            "default_value": "",
            "required": False,
            "grid_cols": 4,
        },
        {
            "key": "surgical_oncologist_reg",
            "label": "Surgical Oncologist Reg. No",
            "type": "text",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "placeholder": "Reg. No",
            "default_value": "",
            "required": False,
            "grid_cols": 2,
        },
        {
            "key": "medical_superintendent_name",
            "label": "Medical Superintendent / Director Name",
            "type": "text",
            "section": "5. BOARD CERTIFICATION & SIGNATURES",
            "placeholder": "Medical Superintendent / Director",
            "default_value": "Medical Superintendent / Director",
            "required": False,
            "grid_cols": 6,
        },
    ],
}


INSTITUTIONAL_TUMOUR_BOARD_TEMPLATE = {
    "template_id": 2,
    "template_name": "Multidisciplinary Tumour Board Certificate (Institutional)",
    "is_template": True,
    "version": "1.0",
    "description": "Comprehensive Institutional Multidisciplinary Clinical Oncology Assessment & Treatment Plan",
    "created_date": "2026-11-02T10:00:00",
    "header_fields": DEFAULT_TUMOUR_BOARD_TEMPLATE["header_fields"],
    "fields": DEFAULT_TUMOUR_BOARD_TEMPLATE["fields"],
}


def ensure_templates_seeded():
    """Do not automatically seed templates; templates are managed by admin directly in DB."""
    pass


# ── Templates API ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_tumour_board_templates(request):
    """
    Return all available Tumour Board templates from hospital_tumourTemplate collection.
    Does not auto-seed templates if empty.
    """
    try:
        col = hospital_tumour_template_collection
        templates = list(col.find({}))
        return Response({"success": True, "data": serialize_doc(templates)}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Patient Search & Details API ──────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def search_tumour_board_patients(request):
    """
    Search patients by UHID, patient name, or IP number for Tumour Board autocomplete.
    """
    q = (request.GET.get("q") or "").strip()
    if not q or len(q) < 1:
        return Response({"success": True, "data": []}, status=status.HTTP_200_OK)

    try:
        regex_query = {"$regex": re.escape(q), "$options": "i"}
        patients = list(
            patient_collection.find(
                {
                    "$or": [
                        {"uhid": regex_query},
                        {"patient_name": regex_query},
                        {"name": regex_query},
                        {"firstName": regex_query},
                        {"lastName": regex_query},
                        {"mobilePhone": regex_query},
                        {"phone": regex_query},
                    ]
                },
                {
                    "_id": 0,
                    "uhid": 1,
                    "name": 1,
                    "patient_name": 1,
                    "firstName": 1,
                    "lastName": 1,
                    "age": 1,
                    "gender": 1,
                    "mobilePhone": 1,
                    "phone": 1,
                    "address": 1,
                    "permanentAddress": 1,
                },
            ).limit(25)
        )

        results = []
        for p in patients:
            raw_uhid = p.get("uhid") or ""
            p_name = (
                p.get("patient_name")
                or p.get("name")
                or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            )
            
            # Check latest admission for IP number / doctor
            adm = admission_collection.find_one(
                {"uhid": raw_uhid},
                sort=[("admissionDateTime", -1)],
                projection={
                    "_id": 0,
                    "ipNumber": 1,
                    "doctor_name": 1,
                    "consultant_name": 1,
                    "room_no": 1,
                    "bed_no": 1,
                    "ward_name": 1,
                    "is_admitted": 1,
                },
            )

            ip_num = adm.get("ipNumber", "") if adm else ""
            doctor = (
                (adm.get("doctor_name") or adm.get("consultant_name") or "")
                if adm
                else ""
            )

            results.append({
                "uhid": raw_uhid,
                "patient_name": p_name,
                "age": p.get("age", ""),
                "gender": p.get("gender", ""),
                "phone": p.get("mobilePhone") or p.get("phone", ""),
                "address": p.get("address") or p.get("permanentAddress", ""),
                "ipNumber": ip_num,
                "attending_doctor": doctor,
                "is_admitted": bool(adm.get("is_admitted")) if adm else False,
            })

        return Response({"success": True, "data": serialize_doc(results)}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_tumour_board_patient_detail(request):
    """
    Fetch comprehensive patient demographic & admission info for auto-filling by UHID.
    """
    uhid = (request.GET.get("uhid") or "").strip()
    if not uhid:
        return Response({"success": False, "error": "UHID is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        p_doc = patient_collection.find_one({"uhid": {"$regex": f"^{re.escape(uhid)}$", "$options": "i"}})
        if not p_doc:
            return Response({"success": False, "error": f"Patient with UHID {uhid} not found"}, status=status.HTTP_404_NOT_FOUND)

        p_name = (
            p_doc.get("patient_name")
            or p_doc.get("name")
            or f"{p_doc.get('firstName', '')} {p_doc.get('lastName', '')}".strip()
        )

        adm = admission_collection.find_one(
            {"uhid": {"$regex": f"^{re.escape(uhid)}$", "$options": "i"}},
            sort=[("admissionDateTime", -1)],
        )

        ip_num = adm.get("ipNumber", "") if adm else ""
        doctor = (
            (adm.get("doctor_name") or adm.get("consultant_name") or "")
            if adm
            else ""
        )
        bed_room = ""
        if adm:
            parts = [adm.get("room_no"), adm.get("bed_no"), adm.get("ward_name")]
            bed_room = " / ".join([str(x) for x in parts if x])

        data = {
            "uhid": p_doc.get("uhid", uhid),
            "patient_name": p_name,
            "age": p_doc.get("age", ""),
            "gender": p_doc.get("gender", ""),
            "phone": p_doc.get("mobilePhone") or p_doc.get("phone", ""),
            "address": p_doc.get("address") or p_doc.get("permanentAddress", ""),
            "ipNumber": ip_num,
            "attending_doctor": doctor,
            "bed_room": bed_room,
            "admission_date": adm.get("admissionDateTime", "") if adm else "",
        }

        return Response({"success": True, "data": serialize_doc(data)}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Date & Audit Helpers ───────────────────────────────────────────────────────

def _parse_to_datetime(val, default_now=False):
    """
    Parse a value (datetime, date, or date string) into a naive BSON datetime.datetime object.
    Supports formats like 'YYYY-MM-DD', ISO 'YYYY-MM-DDTHH:MM:SS...', 'DD-MM-YYYY', etc.
    """
    if val is None or val == "":
        return datetime.now() if default_now else None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        v = val.strip()
        if not v:
            return datetime.now() if default_now else None
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(v[:10], fmt)
            except Exception:
                pass
    return datetime.now() if default_now else None


def _format_display_date(val):
    """Format datetime or date string to YYYY-MM-DD for JSON responses."""
    if not val:
        return ""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    val_str = str(val).strip()
    return val_str[:10] if len(val_str) >= 10 else val_str


def _format_display_iso(val):
    """Format datetime or date string to ISO format for JSON responses."""
    if not val:
        return ""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val).strip()


def _get_auth_user_info(request, fallback_id="system", fallback_name=None):
    """
    Extract authenticated user credentials from request data, headers, or decoded JWT token.
    Prioritizes auth-user-id / aud from active session.
    """
    data = request.data if isinstance(request.data, dict) else {}

    # 1. Extract employee ID from request token / session / headers
    user_id = extract_aud_employee_id(request)

    # 2. Check explicit auth-user-id or employeeId in data/headers
    if not user_id:
        user_id = (
            data.get("auth-user-id")
        )
    user_id = str(user_id).strip() if user_id else "system"

    # Resolve actual employee display name from backend_diagnostics_profile
    user_name = None
    if user_id and user_id.lower() != "system":
        user_name = resolve_created_by_name(user_id)

    if not user_name or user_name == user_id:
        user_name = (
            data.get("auth-user-name")
        )
    user_name = str(user_name).strip() if user_name else user_id

    return user_id, user_name


# ── Certificate CRUD & Approval APIs ──────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def list_tumour_board_certificates(request):
    """
    List stored Tumour Board patient certificates from hospital_tumourBoard collection.
    Supports filtering by from_date, to_date, uhid, patient_name, status.
    """
    try:
        col = hospital_tumour_board_collection
        from_date = (request.GET.get("from_date") or request.GET.get("fromDate") or "").strip()
        to_date = (request.GET.get("to_date") or request.GET.get("toDate") or "").strip()
        search_uhid = request.GET.get("uhid", "").strip()
        search_patient = (request.GET.get("patient_name") or request.GET.get("patientName") or "").strip()
        search_status = request.GET.get("status", "").strip()

        query = {
            "is_template": {"$ne": True},
            "is_deleted": {"$ne": True},
            "is_active": {"$ne": False},
        }

        if search_uhid:
            query["uhid"] = {"$regex": re.escape(search_uhid), "$options": "i"}

        if search_patient:
            query["patient_name"] = {"$regex": re.escape(search_patient), "$options": "i"}

        if search_status:
            if search_status.lower() == "approved":
                query["is_approved"] = True
            elif search_status.lower() in ["draft", "pending"]:
                query["is_approved"] = {"$ne": True}

        # If no dates and no specific search criteria passed, default to current date
        if not from_date and not to_date and not search_uhid and not search_patient and not search_status:
            today_str = date.today().strftime("%Y-%m-%d")
            from_date = today_str
            to_date = today_str

        if from_date and to_date:
            from_dt = _parse_to_datetime(from_date)
            to_dt = _parse_to_datetime(to_date)
            if to_dt:
                to_dt = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            from_iso_str = f"{from_date}T00:00:00"
            to_iso_str = f"{to_date}T23:59:59.999999"
            query["$or"] = [
                {"certificate_date": {"$gte": from_date, "$lte": to_date}},
                {"certificate_date": {"$gte": from_dt, "$lte": to_dt}},
                {"meeting_date": {"$gte": from_date, "$lte": to_date}},
                {"meeting_date": {"$gte": from_dt, "$lte": to_dt}},
                {"created_date": {"$gte": from_dt, "$lte": to_dt}},
                {"created_date": {"$gte": from_iso_str, "$lte": to_iso_str}},
                {"created_at": {"$gte": from_dt, "$lte": to_dt}},
            ]
        elif from_date:
            from_dt = _parse_to_datetime(from_date)
            query["$or"] = [
                {"certificate_date": {"$gte": from_date}},
                {"certificate_date": {"$gte": from_dt}},
                {"created_date": {"$gte": from_dt}},
                {"created_at": {"$gte": from_dt}},
            ]
        elif to_date:
            to_dt = _parse_to_datetime(to_date)
            if to_dt:
                to_dt = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            query["$or"] = [
                {"certificate_date": {"$lte": to_date}},
                {"certificate_date": {"$lte": to_dt}},
                {"created_date": {"$lte": to_dt}},
                {"created_at": {"$lte": to_dt}},
            ]

        docs = list(col.find(query).sort([("created_date", -1), ("created_at", -1)]))

        # Format and enrich each certificate with dynamically resolved employee name from Global profile
        results = []
        for d in docs:
            d_id = str(d.get("_id"))
            created_by = d.get("created_by") or ""
            created_by_name = (resolve_created_by_name(created_by) or str(created_by)) if created_by else ""

            lastmod_by = d.get("lastmodified_by") or d.get("updated_by") or ""
            lastmod_by_name = (resolve_created_by_name(lastmod_by) or str(lastmod_by)) if lastmod_by else ""

            approved_by = d.get("approved_by") or ""
            approved_by_name = (resolve_created_by_name(approved_by) or str(approved_by)) if approved_by else ""

            deleted_by = d.get("deleted_by") or ""
            deleted_by_name = (resolve_created_by_name(deleted_by) or str(deleted_by)) if deleted_by else ""

            results.append({
                "id": d_id,
                "certificate_id": d.get("certificate_id", f"TBC-{d_id[-6:]}"),
                "uhid": d.get("uhid", ""),
                "ip_op_number": d.get("ip_op_number", ""),
                "patient_name": d.get("patient_name", ""),
                "age": d.get("age", ""),
                "gender": d.get("gender", ""),
                "phone": d.get("phone", ""),
                "certificate_date": _format_display_date(d.get("certificate_date")),
                "meeting_date": _format_display_date(d.get("meeting_date") or d.get("certificate_date")),
                "tms_case_ref_no": d.get("tms_case_ref_no", "") or d.get("field_values", {}).get("tms_case_ref_no", ""),
                "scheme_name": d.get("scheme_name", "") or d.get("field_values", {}).get("scheme_name", "CMCHIS"),
                "scheme_card_id": d.get("scheme_card_id", "") or d.get("field_values", {}).get("scheme_card_id", ""),
                "primary_referral_dept": d.get("primary_referral_dept", "") or d.get("field_values", {}).get("primary_referral_dept", ""),
                "treating_consultant": d.get("treating_consultant", "") or d.get("field_values", {}).get("treating_consultant", ""),
                "template_id": d.get("template_id", 1),
                "template_name": d.get("template_name") or "TUMOUR BOARD CERTIFICATE",
                "primary_site": d.get("primary_site", "") or d.get("field_values", {}).get("site_of_malignancy", "") or d.get("field_values", {}).get("primary_site", ""),
                "stage": d.get("stage", "") or d.get("field_values", {}).get("stage", "") or d.get("field_values", {}).get("stage_group", "") or d.get("field_values", {}).get("clinical_stage_tnm", ""),
                "board_remarks": d.get("board_remarks", "") or d.get("field_values", {}).get("board_remarks", ""),
                "field_values": d.get("field_values", {}),
                "is_approved": bool(d.get("is_approved", False)),
                "status": "Approved" if d.get("is_approved") else "Draft",
                "approved_by": approved_by,
                "approved_by_name": approved_by_name,
                "approved_date": _format_display_iso(d.get("approved_date")),
                "created_by": created_by,
                "created_by_name": created_by_name,
                "created_at": _format_display_iso(d.get("created_at") or d.get("created_date")),
                "created_date": _format_display_iso(d.get("created_date") or d.get("created_at")),
                "updated_at": _format_display_iso(d.get("updated_at") or d.get("lastmodified_date")),
                "lastmodified_by": lastmod_by,
                "lastmodified_by_name": lastmod_by_name,
                "lastmodified_date": _format_display_iso(d.get("lastmodified_date") or d.get("updated_at")),
                "deleted_by": deleted_by,
                "deleted_by_name": deleted_by_name,
                "deleted_date": _format_display_iso(d.get("deleted_date") or d.get("deleted_at")),
            })

        return Response({"success": True, "data": serialize_doc(results)}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_tumour_board_certificate(request):
    """
    Create or update a Tumour Board certificate.
    Stores audit credentials from auth-user-id and all dates in BSON datetime format.
    Disallows edits if certificate has already been approved.
    """
    try:
        col = hospital_tumour_board_collection
        payload = request.data or {}

        cert_id = payload.get("id") or payload.get("certificate_id")
        uhid = (payload.get("uhid") or "").strip()
        patient_name = (payload.get("patient_name") or "").strip()

        if not uhid:
            return Response({"success": False, "error": "UHID is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not patient_name:
            return Response({"success": False, "error": "Patient name is required."}, status=status.HTTP_400_BAD_REQUEST)

        field_values = payload.get("field_values") or {}
        # Also extract top-level primary site / stage / remarks for easy indexing
        primary_site = (
            field_values.get("site_of_malignancy")
            or field_values.get("primary_site")
            or payload.get("primary_site", "")
        )
        stage = (
            field_values.get("stage")
            or field_values.get("stage_group")
            or field_values.get("clinical_stage_tnm")
            or payload.get("stage", "")
        )
        board_remarks = field_values.get("board_remarks") or payload.get("board_remarks", "")

        tms_case_ref_no = payload.get("tms_case_ref_no") or field_values.get("tms_case_ref_no", "")
        scheme_name = payload.get("scheme_name") or field_values.get("scheme_name", "CMCHIS")
        scheme_card_id = payload.get("scheme_card_id") or field_values.get("scheme_card_id", "")
        primary_referral_dept = payload.get("primary_referral_dept") or field_values.get("primary_referral_dept", "")
        treating_consultant = payload.get("treating_consultant") or field_values.get("treating_consultant", "")

        # Extract audit credentials from auth-user-id
        user_id, user_name = _get_auth_user_info(request, fallback_id="system")

        branch_code = (
            request.data.get("auth-branch-code")
            or request.headers.get("Branch-Code")
            or request.headers.get("auth-branch-code")
            or payload.get("branch_code", "")
        )
        outlet_code = (
            request.data.get("auth-outlet-code")
            or request.headers.get("Outlet-Code")
            or request.headers.get("auth-outlet-code")
            or payload.get("outlet_code", "")
        )
        hospital_code = (
            request.data.get("auth-hospital-code")
            or request.headers.get("Hospital-Code")
            or request.headers.get("auth-hospital-code")
            or payload.get("hospital_code", "")
        )

        # Dates stored as BSON datetime objects
        now_dt = datetime.now()
        raw_cert_date = payload.get("certificate_date") or payload.get("meeting_date")
        cert_dt = _parse_to_datetime(raw_cert_date, default_now=True)
        raw_meeting_date = payload.get("meeting_date") or payload.get("certificate_date")
        meeting_dt = _parse_to_datetime(raw_meeting_date, default_now=True)

        # Check existing record
        existing = None
        if cert_id:
            try:
                existing = col.find_one({"_id": ObjectId(cert_id)})
            except Exception:
                existing = col.find_one({"certificate_id": cert_id})

        if existing:
            if existing.get("is_approved"):
                return Response(
                    {"success": False, "error": "This certificate is already approved and locked for modifications."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing_cert_dt = _parse_to_datetime(existing.get("certificate_date"))
            existing_meeting_dt = _parse_to_datetime(existing.get("meeting_date"))

            update_data = {
                "uhid": uhid,
                "ip_op_number": payload.get("ip_op_number", ""),
                "patient_name": patient_name,
                "age": payload.get("age", ""),
                "gender": payload.get("gender", ""),
                "phone": payload.get("phone", ""),
                "certificate_date": cert_dt or existing_cert_dt or now_dt,
                "meeting_date": meeting_dt or existing_meeting_dt or cert_dt or now_dt,
                "tms_case_ref_no": tms_case_ref_no,
                "scheme_name": scheme_name,
                "scheme_card_id": scheme_card_id,
                "primary_referral_dept": primary_referral_dept,
                "treating_consultant": treating_consultant,
                "template_id": payload.get("template_id", existing.get("template_id", 1)),
                "template_name": payload.get("template_name") or existing.get("template_name") or "TUMOUR BOARD CERTIFICATE",
                "primary_site": primary_site,
                "stage": stage,
                "board_remarks": board_remarks,
                "field_values": field_values,
                "lastmodified_by": user_id,
                "lastmodified_date": now_dt,
            }

            col.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": update_data,
                    "$unset": {
                        "created_by_name": "",
                        "lastmodified_by_name": "",
                        "approved_by_name": "",
                        "deleted_by_name": "",
                        "created_at": "",
                        "updated_at": "",
                        "updated_by": "",
                    },
                },
            )
            return Response(
                {
                    "success": True,
                    "message": "Tumour Board Certificate updated successfully.",
                    "certificate_id": existing.get("certificate_id"),
                    "id": str(existing["_id"]),
                },
                status=status.HTTP_200_OK,
            )

        # Generate sequential certificate ID: TBC-YYYYMMDD-XXXX
        today_compact = date.today().strftime("%Y%m%d")
        count_today = col.count_documents({
            "certificate_id": {"$regex": f"^TBC-{today_compact}-"},
            "is_template": {"$ne": True},
        })
        new_cert_id = f"TBC-{today_compact}-{str(count_today + 1).zfill(4)}"

        new_doc = {
            "certificate_id": new_cert_id,
            "uhid": uhid,
            "ip_op_number": payload.get("ip_op_number", ""),
            "patient_name": patient_name,
            "age": payload.get("age", ""),
            "gender": payload.get("gender", ""),
            "phone": payload.get("phone", ""),
            "certificate_date": cert_dt,
            "meeting_date": meeting_dt,
            "tms_case_ref_no": tms_case_ref_no,
            "scheme_name": scheme_name,
            "scheme_card_id": scheme_card_id,
            "primary_referral_dept": primary_referral_dept,
            "treating_consultant": treating_consultant,
            "template_id": payload.get("template_id", 1),
            "template_name": payload.get("template_name") or "TUMOUR BOARD CERTIFICATE",
            "primary_site": primary_site,
            "stage": stage,
            "board_remarks": board_remarks,
            "field_values": field_values,
            "is_approved": False,
            "status": "Draft",
            "created_by": user_id,
            "created_date": now_dt,
            "lastmodified_by": user_id,
            "lastmodified_date": now_dt,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "hospital_code": hospital_code,
            "is_active": True,
            "is_deleted": False,
        }

        insert_res = col.insert_one(new_doc)
        return Response(
            {
                "success": True,
                "message": "Tumour Board Certificate saved as Draft successfully.",
                "certificate_id": new_cert_id,
                "id": str(insert_res.inserted_id),
            },
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@permission_classes([HasRoleAndDataPermission])
def delete_tumour_board_certificate(request, cert_id):
    """
    Delete a certificate before approval (Soft Delete: is_active: False, is_deleted: True).
    Stores audit credentials from auth-user-id and deleted_date as datetime.
    Disallows deleting if approved.
    """
    try:
        col = hospital_tumour_board_collection
        existing = None
        try:
            existing = col.find_one({"_id": ObjectId(cert_id)})
        except Exception:
            existing = col.find_one({"certificate_id": cert_id})

        if not existing:
            return Response({"success": False, "error": "Certificate not found."}, status=status.HTTP_404_NOT_FOUND)

        if existing.get("is_approved"):
            return Response(
                {"success": False, "error": "Approved certificates cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id, user_name = _get_auth_user_info(request, fallback_id="system")
        now_dt = datetime.now()

        # Soft delete: set is_active: False, is_deleted: True with audit timestamps in datetime format
        col.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "is_active": False,
                    "is_deleted": True,
                    "deleted_date": now_dt,
                    "deleted_by": user_id,
                    "lastmodified_by": user_id,
                    "lastmodified_date": now_dt,
                },
                "$unset": {
                    "deleted_by_name": "",
                    "lastmodified_by_name": "",
                    "deleted_at": "",
                    "created_at": "",
                    "updated_at": "",
                },
            },
        )
        return Response({"success": True, "message": "Certificate deleted successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["PATCH", "POST"])
@permission_classes([HasRoleAndDataPermission])
def approve_tumour_board_certificate(request, cert_id):
    """
    Approve a Tumour Board certificate.
    Sets is_approved: True, locks certificate, stamps approval credentials from auth-user-id,
    and stores approved_date in BSON datetime format.
    """
    try:
        col = hospital_tumour_board_collection
        existing = None
        try:
            existing = col.find_one({"_id": ObjectId(cert_id)})
        except Exception:
            existing = col.find_one({"certificate_id": cert_id})

        if not existing:
            return Response({"success": False, "error": "Certificate not found."}, status=status.HTTP_404_NOT_FOUND)

        if existing.get("is_approved"):
            return Response(
                {"success": True, "message": "Certificate is already approved.", "data": serialize_doc(existing)},
                status=status.HTTP_200_OK,
            )

        data = request.data if isinstance(request.data, dict) else {}
        user_id, user_name = _get_auth_user_info(request, fallback_id="system")
        now_dt = datetime.now()

        update_fields = {
            "is_approved": True,
            "status": "Approved",
            "approved_by": user_id,
            "approved_date": now_dt,
            "lastmodified_by": user_id,
            "lastmodified_date": now_dt,
        }

        col.update_one(
            {"_id": existing["_id"]},
            {
                "$set": update_fields,
                "$unset": {
                    "approved_by_name": "",
                    "lastmodified_by_name": "",
                    "created_at": "",
                    "updated_at": "",
                },
            },
        )
        approved_by_name = (resolve_created_by_name(user_id) or str(user_id)) if user_id else ""
        return Response(
            {
                "success": True,
                "message": "Certificate approved successfully. Certificate printing is now enabled.",
                "approved_date": _format_display_iso(now_dt),
                "approved_by": user_id,
                "approved_by_name": approved_by_name,
            },
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
