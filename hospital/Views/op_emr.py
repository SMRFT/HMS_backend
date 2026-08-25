from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
import os
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_hms_db = _client["HMS"]
_global_db = _client["Global"]

_op_emr_collection = _hms_db["op_emr_consultations"]
_rx_templates_collection = _hms_db["op_rx_templates"]
_pharmacy_stock_collection = _hms_db["pharmacy_items"]


@api_view(['GET'])
def get_op_doctor_queue(request):
    """
    Returns OP patient queue for doctor for a specified date (default today).
    """
    try:
        doctor_id = request.GET.get('doctor_id', '')
        date_str = request.GET.get('date', '')

        if not date_str:
            target_date = timezone.now().strftime('%Y-%m-%d')
        else:
            target_date = date_str

        # Fetch from MongoDB op_emr_consultations or OP Patient visits
        query = {
            "visit_date": {"$regex": f"^{target_date}"}
        }
        if doctor_id:
            query["$or"] = [
                {"doctor_id": doctor_id},
                {"doctor_name": {"$regex": doctor_id, "$options": "i"}}
            ]

        cursor = _op_emr_collection.find(query, {"_id": 0}).sort("token_no", 1)
        queue = list(cursor)

        # Fallback dummy sample queue if empty for demonstration/testing
        if not queue:
            sample_patients = [
                {
                    "op_number": f"OP-{target_date.replace('-', '')}-001",
                    "uhid": "SH-10024",
                    "token_no": 1,
                    "patient_name": "M. Parthiban",
                    "age": 34,
                    "gender": "Male",
                    "mobile": "9876543210",
                    "doctor_id": doctor_id or "DOC-101",
                    "doctor_name": "Dr. S. Ramesh MD",
                    "visit_date": f"{target_date}T09:30:00Z",
                    "visit_type": "New Visit",
                    "status": "In-Consultation",
                    "vitals": {
                        "bp": "120/80",
                        "pulse": 76,
                        "temp": 98.6,
                        "spo2": 99,
                        "weight_kg": 68,
                        "height_cm": 172,
                        "bmi": 22.98
                    },
                    "allergies": ["Penicillin", "Dust"],
                    "chief_complaints": [
                        {"symptom": "Fever", "duration": "3 Days", "severity": "Moderate"},
                        {"symptom": "Dry Cough", "duration": "2 Days", "severity": "Mild"}
                    ],
                    "examination": {
                        "cvs": "S1 S2 Heard, Normal",
                        "rs": "Bilateral Clear",
                        "pa": "Soft, Non-tender",
                        "cns": "Conscious, Oriented",
                        "notes": "Mild throat congestion present"
                    },
                    "diagnosis": [
                        {"code": "1B10", "name": "Acute Upper Respiratory Infection", "type": "Primary"}
                    ],
                    "prescriptions": [
                        {
                            "medicine_name": "Tab Paracetamol 650mg",
                            "dosage": "1-0-1",
                            "timing": "After Food",
                            "duration_days": 5,
                            "total_qty": 10,
                            "instructions": "Take for fever > 100 F"
                        },
                        {
                            "medicine_name": "Tab Cetirizine 10mg",
                            "dosage": "0-0-1",
                            "timing": "After Food",
                            "duration_days": 5,
                            "total_qty": 5,
                            "instructions": "Take at bedtime"
                        }
                    ],
                    "investigation_orders": [
                        {"type": "Lab", "test_name": "Complete Blood Count (CBC)"},
                        {"type": "Radiology", "test_name": "Chest X-Ray PA View"}
                    ],
                    "advice": "Drink warm water, Steam inhalation twice daily, Avoid cold beverages.",
                    "follow_up_date": f"{target_date}"
                },
                {
                    "op_number": f"OP-{target_date.replace('-', '')}-002",
                    "uhid": "SH-10029",
                    "token_no": 2,
                    "patient_name": "S. Anitha",
                    "age": 28,
                    "gender": "Female",
                    "mobile": "9842123456",
                    "doctor_id": doctor_id or "DOC-101",
                    "doctor_name": "Dr. S. Ramesh MD",
                    "visit_date": f"{target_date}T10:15:00Z",
                    "visit_type": "Review Visit",
                    "status": "Waiting",
                    "vitals": {
                        "bp": "110/70",
                        "pulse": 82,
                        "temp": 98.4,
                        "spo2": 98,
                        "weight_kg": 54,
                        "height_cm": 160,
                        "bmi": 21.09
                    },
                    "allergies": [],
                    "chief_complaints": [
                        {"symptom": "Headache", "duration": "1 Week", "severity": "Mild"}
                    ],
                    "examination": {"notes": "Stress-induced headache symptoms"},
                    "diagnosis": [{"code": "8A80", "name": "Migraine / Tension Headache", "type": "Primary"}],
                    "prescriptions": [],
                    "investigation_orders": [],
                    "advice": "Adequate hydration and 8 hours sleep",
                    "follow_up_date": ""
                }
            ]
            return Response({"success": True, "queue": sample_patients}, status=200)

        return Response({"success": True, "queue": queue}, status=200)

    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['GET'])
def get_patient_emr_history(request):
    """
    Retrieves full past OP consultation records for a patient by UHID.
    """
    try:
        uhid = request.GET.get('uhid')
        if not uhid:
            return Response({"success": False, "error": "UHID is required"}, status=400)

        records = list(_op_emr_collection.find({"uhid": uhid}, {"_id": 0}).sort("visit_date", -1))
        return Response({"success": True, "history": records}, status=200)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['POST'])
def save_op_consultation(request):
    """
    Saves or updates an OP EMR consultation record.
    """
    try:
        data = request.data
        op_number = data.get('op_number')
        uhid = data.get('uhid')

        if not op_number or not uhid:
            return Response({"success": False, "error": "op_number and uhid are required"}, status=400)

        data['updated_at'] = datetime.utcnow().isoformat()

        _op_emr_collection.update_one(
            {"op_number": op_number},
            {"$set": data},
            upsert=True
        )

        return Response({"success": True, "message": "OP EMR Consultation saved successfully", "op_number": op_number}, status=200)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['GET', 'POST'])
def rx_templates_api(request):
    """
    Fetch or save prescription templates.
    """
    try:
        if request.method == 'GET':
            doctor_id = request.GET.get('doctor_id', 'general')
            templates = list(_rx_templates_collection.find(
                {"$or": [{"doctor_id": doctor_id}, {"doctor_id": "general"}]},
                {"_id": 0}
            ))

            if not templates:
                # Default templates fallback
                templates = [
                    {
                        "template_name": "Fever & Cold Protocol",
                        "doctor_id": "general",
                        "prescriptions": [
                            {"medicine_name": "Tab Paracetamol 650mg", "dosage": "1-0-1", "timing": "After Food", "duration_days": 5, "total_qty": 10},
                            {"medicine_name": "Tab Cetirizine 10mg", "dosage": "0-0-1", "timing": "After Food", "duration_days": 5, "total_qty": 5}
                        ]
                    },
                    {
                        "template_name": "Diabetology Routine",
                        "doctor_id": "general",
                        "prescriptions": [
                            {"medicine_name": "Tab Metformin 500mg", "dosage": "1-0-1", "timing": "After Food", "duration_days": 30, "total_qty": 60},
                            {"medicine_name": "Tab Glimepiride 1mg", "dosage": "1-0-0", "timing": "Before Food", "duration_days": 30, "total_qty": 30}
                        ]
                    }
                ]
            return Response({"success": True, "templates": templates}, status=200)

        elif request.method == 'POST':
            data = request.data
            template_name = data.get('template_name')
            if not template_name:
                return Response({"success": False, "error": "template_name is required"}, status=400)

            _rx_templates_collection.update_one(
                {"template_name": template_name},
                {"$set": data},
                upsert=True
            )
            return Response({"success": True, "message": "Prescription template saved successfully"}, status=200)

    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)
