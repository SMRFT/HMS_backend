from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, date
import re
from bson import ObjectId, Decimal128

from .dbcollection import (
    hms_db,
    hospital_tumour_board_collection,
    patient_collection,
    admission_collection,
    get_employee_name_by_id,
    resolve_created_by_name,
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
    "template_name": "Tumour Board Certificate",
    "is_template": True,
    "version": "1.0",
    "description": "Multidisciplinary Tumour Board Clinical Assessment & Certification Template",
    "created_at": "2026-11-02T10:00:00",
    "fields": [
        # Section 1: Clinical Presentation & History
        {
            "key": "clinical_history",
            "label": "1. Clinical History & Presentation",
            "type": "textarea",
            "section": "1. Clinical Presentation & History",
            "placeholder": "Enter chief complaints, history of present illness, clinical course, and physical examination findings...",
            "default_value": "",
            "required": False,
            "grid_cols": 12,
            "rows": 3,
        },
        {
            "key": "ecog_ps",
            "label": "ECOG Performance Status",
            "type": "select",
            "section": "1. Clinical Presentation & History",
            "value_options": [
                "ECOG 0 - Fully active, able to carry on all pre-disease performance without restriction",
                "ECOG 1 - Restricted in strenuous activity; ambulatory and able to carry out light work",
                "ECOG 2 - Ambulatory, capable of all self-care, unable to carry out work; up >50% waking hours",
                "ECOG 3 - Capable of only limited self-care; confined to bed/chair >50% waking hours",
                "ECOG 4 - Completely disabled; cannot carry on any self-care; totally confined to bed/chair",
            ],
            "default_value": "ECOG 1 - Restricted in strenuous activity; ambulatory and able to carry out light work",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "comorbidities",
            "label": "Co-morbidities & Past Medical History",
            "type": "text",
            "section": "1. Clinical Presentation & History",
            "placeholder": "e.g. Hypertension, Type 2 DM, CAD, Bronchial Asthma, None",
            "default_value": "None significant",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "habits_risk_factors",
            "label": "Habits / Risk Factors / Family History",
            "type": "text",
            "section": "1. Clinical Presentation & History",
            "placeholder": "e.g. Non-smoker, Non-alcoholic, Family history of malignancy",
            "default_value": "",
            "required": False,
            "grid_cols": 12,
        },

        # Section 2: Diagnostic & Pathological Workup
        {
            "key": "primary_site",
            "label": "Primary Tumour Site / Organ",
            "type": "text",
            "section": "2. Diagnostic & Pathological Workup",
            "placeholder": "e.g. Right Breast Upper Outer Quadrant, Lung Left Upper Lobe, Rectum, Tongue",
            "default_value": "",
            "required": True,
            "grid_cols": 6,
        },
        {
            "key": "histological_grade",
            "label": "Histological Grade / Differentiation",
            "type": "select",
            "section": "2. Diagnostic & Pathological Workup",
            "value_options": [
                "Grade 1 - Well Differentiated (Low Grade)",
                "Grade 2 - Moderately Differentiated (Intermediate Grade)",
                "Grade 3 - Poorly Differentiated (High Grade)",
                "Grade 4 - Undifferentiated / Anaplastic",
                "Not Applicable / Unspecified",
            ],
            "default_value": "Grade 2 - Moderately Differentiated (Intermediate Grade)",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "histopathology",
            "label": "Biopsy / Histopathology Findings",
            "type": "textarea",
            "section": "2. Diagnostic & Pathological Workup",
            "placeholder": "Histopathology biopsy findings, morphology, lymphovascular invasion, perineural invasion...",
            "default_value": "",
            "required": False,
            "grid_cols": 12,
            "rows": 3,
        },
        {
            "key": "clinical_stage_tnm",
            "label": "TNM Staging (Clinical / Pathological)",
            "type": "text",
            "section": "2. Diagnostic & Pathological Workup",
            "placeholder": "e.g. cT2 N1 M0 or pT3 N2a M0",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "stage_group",
            "label": "Overall Clinical Stage Group",
            "type": "select",
            "section": "2. Diagnostic & Pathological Workup",
            "value_options": [
                "Stage I",
                "Stage IA",
                "Stage IB",
                "Stage II",
                "Stage IIA",
                "Stage IIB",
                "Stage III",
                "Stage IIIA",
                "Stage IIIB",
                "Stage IIIC",
                "Stage IV",
                "Stage IVA",
                "Stage IVB",
                "Recurrent / Metastatic Disease",
            ],
            "default_value": "Stage IIA",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "imaging_findings",
            "label": "Radiology / Imaging Workup (CT / MRI / PET-CT)",
            "type": "textarea",
            "section": "2. Diagnostic & Pathological Workup",
            "placeholder": "Findings of CECT Thorax/Abdomen, Whole Body 18F-FDG PET-CT, Brain MRI...",
            "default_value": "",
            "required": False,
            "grid_cols": 12,
            "rows": 3,
        },
        {
            "key": "biomarkers",
            "label": "Biomarkers & Molecular Pathology",
            "type": "text",
            "section": "2. Diagnostic & Pathological Workup",
            "placeholder": "e.g. ER: Positive (80%), PR: Positive (60%), HER2: Negative (1+), Ki-67: 35%, MSI-H, PD-L1 TPS > 50%",
            "default_value": "",
            "required": False,
            "grid_cols": 12,
        },

        # Section 3: Multidisciplinary Board Discussion
        {
            "key": "discussion_summary",
            "label": "3. Multidisciplinary Discussion Summary",
            "type": "textarea",
            "section": "3. Multidisciplinary Board Discussion",
            "placeholder": "Summary of case discussion points, review of discordant findings, multi-specialty inputs...",
            "default_value": "",
            "required": False,
            "grid_cols": 12,
            "rows": 3,
        },
        {
            "key": "treatment_intent",
            "label": "Treatment Intent",
            "type": "select",
            "section": "3. Multidisciplinary Board Discussion",
            "value_options": [
                "Curative Intent",
                "Definitive Chemoradiation",
                "Neoadjuvant (Pre-operative) Therapy",
                "Adjuvant (Post-operative) Therapy",
                "Palliative / Supportive Care",
                "Metastasectomy / Oligometastatic Directed Therapy",
                "Active Surveillance / Observation",
            ],
            "default_value": "Curative Intent",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "meeting_date",
            "label": "Tumour Board Meeting Date",
            "type": "date",
            "section": "3. Multidisciplinary Board Discussion",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },

        # Section 4: Specific Recommendations / Board Remarks (EXACT MATCH TO ATTACHED IMAGE)
        {
            "key": "board_remarks",
            "label": "4. SPECIFIC RECOMMENDATIONS / BOARD REMARKS",
            "type": "textarea",
            "section": "4. Specific Recommendations / Board Remarks",
            "placeholder": "Enter overall multidisciplinary tumour board recommendations, proposed sequencing of therapies, surgical approaches, chemotherapeutic regimens, radiation planning, supportive care...",
            "default_value": "",
            "required": True,
            "grid_cols": 12,
            "rows": 5,
        },
        {
            "key": "systemic_therapy",
            "label": "Systemic Medical Oncology Regimen",
            "type": "text",
            "section": "4. Specific Recommendations / Board Remarks",
            "placeholder": "e.g. Neoadjuvant Chemotherapy: 4 cycles AC followed by 4 cycles Paclitaxel q2w",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "radiation_therapy",
            "label": "Radiation Oncology Plan",
            "type": "text",
            "section": "4. Specific Recommendations / Board Remarks",
            "placeholder": "e.g. Adjuvant Radiation Therapy to chest wall and supraclavicular fossa (50 Gy in 25 fractions)",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "surgical_plan",
            "label": "Surgical Oncology Plan",
            "type": "text",
            "section": "4. Specific Recommendations / Board Remarks",
            "placeholder": "e.g. Modified Radical Mastectomy (MRM) / Breast Conservation Surgery (BCS) post NACT",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },
        {
            "key": "palliative_followup",
            "label": "Follow-up & Supportive Care",
            "type": "text",
            "section": "4. Specific Recommendations / Board Remarks",
            "placeholder": "e.g. Review in OPD with repeat imaging post 3rd cycle; cardiac evaluation (ECHO)",
            "default_value": "",
            "required": False,
            "grid_cols": 6,
        },

        # Section 5: Board Signatures & Certification (EXACT MATCH TO ATTACHED IMAGE)
        {
            "key": "certification_statement",
            "label": "Board Certification Statement",
            "type": "declaration",
            "section": "5. Board Certification & Signatures",
            "default_value": "We hereby certify that the case details of the aforementioned patient have been reviewed thoroughly by the Multidisciplinary Tumour Board, and the recommended treatment modalities conform to established oncology guidelines for standard patient care.",
            "required": True,
            "grid_cols": 12,
        },
        {
            "key": "medical_oncologist_name",
            "label": "Medical Oncologist Name",
            "type": "text",
            "section": "5. Board Certification & Signatures",
            "placeholder": "Dr. Name",
            "default_value": "",
            "required": False,
            "grid_cols": 4,
        },
        {
            "key": "medical_oncologist_reg",
            "label": "Medical Oncologist Reg. No",
            "type": "text",
            "section": "5. Board Certification & Signatures",
            "placeholder": "Reg. No",
            "default_value": "",
            "required": False,
            "grid_cols": 2,
        },
        {
            "key": "radiation_oncologist_name",
            "label": "Radiation Oncologist Name",
            "type": "text",
            "section": "5. Board Certification & Signatures",
            "placeholder": "Dr. Name",
            "default_value": "",
            "required": False,
            "grid_cols": 4,
        },
        {
            "key": "radiation_oncologist_reg",
            "label": "Radiation Oncologist Reg. No",
            "type": "text",
            "section": "5. Board Certification & Signatures",
            "placeholder": "Reg. No",
            "default_value": "",
            "required": False,
            "grid_cols": 2,
        },
        {
            "key": "surgical_oncologist_name",
            "label": "Surgical Oncologist Name",
            "type": "text",
            "section": "5. Board Certification & Signatures",
            "placeholder": "Dr. Name",
            "default_value": "",
            "required": False,
            "grid_cols": 4,
        },
        {
            "key": "surgical_oncologist_reg",
            "label": "Surgical Oncologist Reg. No",
            "type": "text",
            "section": "5. Board Certification & Signatures",
            "placeholder": "Reg. No",
            "default_value": "",
            "required": False,
            "grid_cols": 2,
        },
        {
            "key": "medical_superintendent_name",
            "label": "Medical Superintendent / Director Name",
            "type": "text",
            "section": "5. Board Certification & Signatures",
            "placeholder": "Medical Superintendent / Director",
            "default_value": "Medical Superintendent / Director",
            "required": False,
            "grid_cols": 6,
        },
    ],
}


def ensure_templates_seeded():
    """Ensure template_id: 1 exists in hospital_tumourBoard collection."""
    try:
        col = hospital_tumour_board_collection
        existing = col.find_one({"template_id": 1, "is_template": True})
        if not existing:
            col.insert_one(DEFAULT_TUMOUR_BOARD_TEMPLATE.copy())
    except Exception as e:
        print("Warning: could not seed tumour board template:", e)


# ── Templates API ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def get_tumour_board_templates(request):
    """
    Return all available Tumour Board templates from hospital_tumourBoard collection.
    Seeds template_id: 1 if collection has no templates.
    """
    try:
        ensure_templates_seeded()
        col = hospital_tumour_board_collection
        templates = list(col.find({"is_template": True}, {"_id": 0}))
        if not templates:
            templates = [DEFAULT_TUMOUR_BOARD_TEMPLATE]
        return Response({"success": True, "data": serialize_doc(templates)}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Patient Search & Details API ──────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
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
@permission_classes([AllowAny])
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


# ── Certificate CRUD & Approval APIs ──────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def list_tumour_board_certificates(request):
    """
    List stored Tumour Board patient certificates from hospital_tumourBoard collection.
    Supports filtering by from_date, to_date, uhid, patient_name, status.
    """
    try:
        col = hospital_tumour_board_collection
        from_date = request.GET.get("from_date", "").strip()
        to_date = request.GET.get("to_date", "").strip()
        search_uhid = request.GET.get("uhid", "").strip()
        search_patient = request.GET.get("patient_name", "").strip()
        search_status = request.GET.get("status", "").strip()

        query = {"is_template": {"$ne": True}, "is_deleted": {"$ne": True}}

        if search_uhid:
            query["uhid"] = {"$regex": re.escape(search_uhid), "$options": "i"}

        if search_patient:
            query["patient_name"] = {"$regex": re.escape(search_patient), "$options": "i"}

        if search_status:
            if search_status.lower() == "approved":
                query["is_approved"] = True
            elif search_status.lower() in ["draft", "pending"]:
                query["is_approved"] = {"$ne": True}

        if from_date and to_date:
            query["certificate_date"] = {"$gte": from_date, "$lte": to_date}
        elif from_date:
            query["certificate_date"] = {"$gte": from_date}
        elif to_date:
            query["certificate_date"] = {"$lte": to_date}

        docs = list(col.find(query).sort("created_at", -1))

        # Format and enrich each certificate with resolved created_by name
        results = []
        for d in docs:
            d_id = str(d.get("_id"))
            created_by = d.get("created_by") or ""
            created_by_name = d.get("created_by_name") or ""
            if not created_by_name and created_by:
                created_by_name = resolve_created_by_name(created_by) or str(created_by)

            approved_by = d.get("approved_by") or ""
            approved_by_name = d.get("approved_by_name") or ""
            if not approved_by_name and approved_by:
                approved_by_name = resolve_created_by_name(approved_by) or str(approved_by)

            results.append({
                "id": d_id,
                "certificate_id": d.get("certificate_id", f"TBC-{d_id[-6:]}"),
                "uhid": d.get("uhid", ""),
                "ip_op_number": d.get("ip_op_number", ""),
                "patient_name": d.get("patient_name", ""),
                "age": d.get("age", ""),
                "gender": d.get("gender", ""),
                "phone": d.get("phone", ""),
                "address": d.get("address", ""),
                "attending_doctor": d.get("attending_doctor", ""),
                "certificate_date": d.get("certificate_date", ""),
                "template_id": d.get("template_id", 1),
                "template_name": d.get("template_name", "Tumour Board Certificate"),
                "primary_site": d.get("primary_site", "") or d.get("field_values", {}).get("primary_site", ""),
                "stage": d.get("stage", "") or d.get("field_values", {}).get("stage_group", "") or d.get("field_values", {}).get("clinical_stage_tnm", ""),
                "board_remarks": d.get("board_remarks", "") or d.get("field_values", {}).get("board_remarks", ""),
                "field_values": d.get("field_values", {}),
                "is_approved": bool(d.get("is_approved", False)),
                "status": "Approved" if d.get("is_approved") else "Draft",
                "approved_by": approved_by,
                "approved_by_name": approved_by_name,
                "approved_date": d.get("approved_date", ""),
                "created_by": created_by,
                "created_by_name": created_by_name,
                "created_at": d.get("created_at", ""),
                "updated_at": d.get("updated_at", ""),
            })

        return Response({"success": True, "data": serialize_doc(results)}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([AllowAny])
def save_tumour_board_certificate(request):
    """
    Create or update a Tumour Board certificate.
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
        primary_site = field_values.get("primary_site") or payload.get("primary_site", "")
        stage = field_values.get("stage_group") or field_values.get("clinical_stage_tnm") or payload.get("stage", "")
        board_remarks = field_values.get("board_remarks") or payload.get("board_remarks", "")

        user_id = request.headers.get("X-Employee-Id") or payload.get("created_by") or "HMS-STAFF"
        user_name = resolve_created_by_name(user_id) or str(user_id)

        now_str = datetime.now().isoformat()
        today_date = date.today().strftime("%Y-%m-%d")

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

            update_data = {
                "uhid": uhid,
                "ip_op_number": payload.get("ip_op_number", ""),
                "patient_name": patient_name,
                "age": payload.get("age", ""),
                "gender": payload.get("gender", ""),
                "phone": payload.get("phone", ""),
                "address": payload.get("address", ""),
                "attending_doctor": payload.get("attending_doctor", ""),
                "certificate_date": payload.get("certificate_date") or existing.get("certificate_date", today_date),
                "template_id": payload.get("template_id", existing.get("template_id", 1)),
                "template_name": payload.get("template_name", existing.get("template_name", "Tumour Board Certificate")),
                "primary_site": primary_site,
                "stage": stage,
                "board_remarks": board_remarks,
                "field_values": field_values,
                "updated_at": now_str,
                "updated_by": user_id,
            }

            col.update_one({"_id": existing["_id"]}, {"$set": update_data})
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
            "address": payload.get("address", ""),
            "attending_doctor": payload.get("attending_doctor", ""),
            "certificate_date": payload.get("certificate_date") or today_date,
            "template_id": payload.get("template_id", 1),
            "template_name": payload.get("template_name", "Tumour Board Certificate"),
            "primary_site": primary_site,
            "stage": stage,
            "board_remarks": board_remarks,
            "field_values": field_values,
            "is_approved": False,
            "status": "Draft",
            "created_by": user_id,
            "created_by_name": user_name,
            "created_at": now_str,
            "updated_at": now_str,
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
@permission_classes([AllowAny])
def delete_tumour_board_certificate(request, cert_id):
    """
    Delete a certificate before approval.
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

        col.delete_one({"_id": existing["_id"]})
        return Response({"success": True, "message": "Certificate deleted successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["PATCH", "POST"])
@permission_classes([AllowAny])
def approve_tumour_board_certificate(request, cert_id):
    """
    Approve a Tumour Board certificate.
    Sets is_approved: True, locks certificate, and stamps approval metadata.
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

        user_id = request.headers.get("X-Employee-Id") or request.data.get("approved_by") or "HMS-APPROVER"
        user_name = resolve_created_by_name(user_id) or str(user_id)
        now_str = datetime.now().isoformat()

        update_fields = {
            "is_approved": True,
            "status": "Approved",
            "approved_by": user_id,
            "approved_by_name": user_name,
            "approved_date": now_str,
            "updated_at": now_str,
        }

        col.update_one({"_id": existing["_id"]}, {"$set": update_fields})
        return Response(
            {
                "success": True,
                "message": "Certificate approved successfully. Certificate printing is now enabled.",
                "approved_date": now_str,
                "approved_by_name": user_name,
            },
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
