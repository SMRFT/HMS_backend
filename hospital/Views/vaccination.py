from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, date, time, timedelta
from pymongo import MongoClient
import os
import re
import requests
import logging
from pathlib import Path
from dotenv import load_dotenv
from ..models import PatientVaccination, VaccinationMaster, Patient, CommunicationLog

logger = logging.getLogger(__name__)


def get_vaccination_template_name():
    env_path = Path(__file__).resolve().parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
    return (os.getenv("BOTIFY_VACCINATION_TEMPLATE_NAME") or "").strip()


def get_hms_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client, client['HMS']


def format_date_str(val):
    """Convert datetime / date / str object to YYYY-MM-DD string for frontend."""
    if not val:
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime('%Y-%m-%d')
    if isinstance(val, str):
        return val[:10]
    return str(val)


def parse_to_datetime(val):
    """Parse YYYY-MM-DD / ISO string or date into Python datetime for DateTimeField storage."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    try:
        clean_str = str(val).strip()
        if "T" in clean_str:
            return datetime.fromisoformat(clean_str.replace("Z", "+00:00"))
        return datetime.strptime(clean_str[:10], "%Y-%m-%d")
    except Exception:
        return datetime.now()


def serialize_doc(doc, master_map):
    """Serialize hospital_patientVaccination document into frontend format."""
    if not doc:
        return None
    
    uhid = str(doc.get('uhid', ''))
    mother_uhid = str(doc.get('mother_uhid', ''))
    rec_date = doc.get('date')
    details = doc.get('vaccination_details', [])
    created_by = doc.get('created_by')
    created_date = doc.get('created_date')
    lastmodified_by = doc.get('lastmodified_by')
    lastmodified_date = doc.get('lastmodified_date')
    branch_code = doc.get('branch_code')
    hospital_code = doc.get('hospital_code')
    is_active = doc.get('is_active', True)

    formatted_details = []
    for item in details:
        if isinstance(item, dict):
            v_id = item.get("vaccination_id")
            v_name = master_map.get(v_id, f"Vaccine #{v_id}")
            is_vac = bool(item.get("is_vaccination", False))
            vac_date = format_date_str(item.get("vaccination_date"))
            if is_vac:
                vaccinated_date = format_date_str(item.get("vaccinated_date") or item.get("vaccination_date"))
            else:
                vaccinated_date = None

            formatted_details.append({
                "vaccination_id": v_id,
                "vaccination_name": v_name,
                "vaccination_date": vac_date,
                "vaccinated_date": vaccinated_date,
                "is_vaccination": is_vac
            })

    def fmt_dt(dt):
        if isinstance(dt, (datetime, date)):
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        return str(dt) if dt else None

    return {
        "_id": str(doc['_id']) if '_id' in doc else None,
        "uhid": uhid,
        "mother_uhid": mother_uhid,
        "date": format_date_str(rec_date),
        "vaccination_details": formatted_details,
        "created_by": created_by,
        "created_date": fmt_dt(created_date),
        "lastmodified_by": lastmodified_by,
        "lastmodified_date": fmt_dt(lastmodified_date),
        "branch_code": branch_code,
        "hospital_code": hospital_code,
        "is_active": is_active,
    }


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_vaccination_masters(request):
    """
    Fetch all active/all vaccines directly from hospital_vaccinationMaster collection in HMS database.
    Query param include_inactive=true fetches all master vaccines.
    """
    client = None
    try:
        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']

        include_inactive = request.GET.get("include_inactive") == "true"
        query = {} if include_inactive else {"is_active": True}

        masters = list(master_coll.find(query, {"_id": 0}))
        masters.sort(key=lambda x: x.get("vaccination_id", 0))

        return Response({"success": True, "data": masters}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching vaccination masters: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def add_vaccination_master(request):
    """
    Add a new vaccine to hospital_vaccinationMaster. Auto-increments vaccination_id.
    Stores created_by, created_date audit fields.
    """
    client = None
    try:
        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']

        name = str(request.data.get("vaccination_name", "")).strip()
        if not name:
            return Response({"success": False, "error": "Vaccination name is required"}, status=status.HTTP_400_BAD_REQUEST)

        user_id = (
            request.data.get("auth-user-id")
            or request.headers.get("auth-user-id")
            or request.headers.get("Auth-User-Id")
            or request.data.get("created_by")
            or request.data.get("user_id")
            or (str(request.user) if request.user and request.user.is_authenticated else "system")
        )

        all_masters = list(master_coll.find({}, {"vaccination_id": 1}))
        max_id = max([m.get("vaccination_id", 0) for m in all_masters], default=0)
        new_id = max_id + 1

        now_dt = datetime.now()
        new_doc = {
            "vaccination_id": new_id,
            "vaccination_name": name,
            "is_active": True,
            "created_by": user_id,
            "created_date": now_dt,
        }
        master_coll.insert_one(new_doc)

        return Response({
            "success": True,
            "message": f"Vaccine '{name}' added successfully!",
            "data": {"vaccination_id": new_id, "vaccination_name": name, "is_active": True}
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error adding vaccination master: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PUT', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_vaccination_master(request, v_id):
    """
    Update vaccination_name or is_active status for a vaccine in hospital_vaccinationMaster.
    Updates lastmodified_by and lastmodified_date audit fields.
    """
    client = None
    try:
        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']

        doc = master_coll.find_one({"vaccination_id": int(v_id)})
        if not doc:
            return Response({"success": False, "error": "Vaccination master not found"}, status=status.HTTP_404_NOT_FOUND)

        user_id = (
            request.data.get("auth-user-id")
            or request.headers.get("auth-user-id")
            or request.headers.get("Auth-User-Id")
            or request.data.get("lastmodified_by")
            or request.data.get("user_id")
            or (str(request.user) if request.user and request.user.is_authenticated else "system")
        )

        update_fields = {
            "lastmodified_by": user_id,
            "lastmodified_date": datetime.now()
        }
        if "vaccination_name" in request.data:
            name = str(request.data.get("vaccination_name", "")).strip()
            if name:
                update_fields["vaccination_name"] = name
        
        if "is_active" in request.data:
            update_fields["is_active"] = bool(request.data.get("is_active"))

        master_coll.update_one({"vaccination_id": int(v_id)}, {"$set": update_fields})

        return Response({"success": True, "message": "Vaccination master updated successfully!"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error updating vaccination master #{v_id}: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['DELETE', 'PUT', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def delete_vaccination_master(request, v_id):
    """
    Soft delete (set is_active = False or toggle is_active) for a vaccine in hospital_vaccinationMaster.
    Updates lastmodified_by and lastmodified_date audit fields.
    """
    client = None
    try:
        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']

        doc = master_coll.find_one({"vaccination_id": int(v_id)})
        if not doc:
            return Response({"success": False, "error": "Vaccination master not found"}, status=status.HTTP_404_NOT_FOUND)

        user_id = (
            request.data.get("auth-user-id")
            or request.headers.get("auth-user-id")
            or request.headers.get("Auth-User-Id")
            or request.data.get("lastmodified_by")
            or request.data.get("user_id")
            or (str(request.user) if request.user and request.user.is_authenticated else "system")
        )

        new_status = not bool(doc.get("is_active", True)) if "toggle" in request.GET else False

        master_coll.update_one(
            {"vaccination_id": int(v_id)},
            {"$set": {
                "is_active": new_status,
                "lastmodified_by": user_id,
                "lastmodified_date": datetime.now()
            }}
        )

        status_msg = "deactivated" if not new_status else "activated"
        return Response({"success": True, "message": f"Vaccination master {status_msg} successfully!"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error soft deleting vaccination master #{v_id}: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_patient_vaccination(request, uhid):
    """
    Fetch patient vaccination record by UHID from hospital_patientVaccination collection.
    """
    client = None
    try:
        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']
        vacc_coll = db['hospital_patientVaccination']

        masters = list(master_coll.find({}, {"_id": 0}))
        master_map = {m["vaccination_id"]: m.get("vaccination_name", "") for m in masters if "vaccination_id" in m}

        doc = vacc_coll.find_one({"uhid": str(uhid)})

        if doc:
            data = serialize_doc(doc, master_map)
            return Response({"success": True, "exists": True, "data": data}, status=status.HTTP_200_OK)
        else:
            return Response({
                "success": True,
                "exists": False,
                "data": {
                    "uhid": str(uhid),
                    "mother_uhid": "",
                    "date": datetime.today().strftime('%Y-%m-%d'),
                    "vaccination_details": []
                }
            }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error fetching patient vaccination for UHID {uhid}: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_pending_vaccinations(request):
    """
    Fetch patients who have pending vaccinations for a date range (from_date to to_date)
    from hospital_patientVaccination collection.
    """
    client = None
    try:
        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']
        vacc_coll = db['hospital_patientVaccination']
        patient_coll = db['hospital_patient']

        today_str = datetime.today().strftime('%Y-%m-%d')
        from_date_str = request.GET.get('from_date') or request.GET.get('date') or today_str
        to_date_str = request.GET.get('to_date') or from_date_str

        if from_date_str > to_date_str:
            from_date_str, to_date_str = to_date_str, from_date_str

        masters = list(master_coll.find({}, {"_id": 0}))
        master_map = {m["vaccination_id"]: m.get("vaccination_name", "") for m in masters if "vaccination_id" in m}

        records = list(vacc_coll.find({"is_active": True}))

        pending_patients = []
        uhid_list = []

        for r in records:
            details = r.get('vaccination_details', [])
            r_uhid = r.get('uhid')
            r_mother_uhid = r.get('mother_uhid')
            r_date = r.get('date')

            pending_items = []
            
            for item in details:
                if isinstance(item, dict):
                    is_vac = bool(item.get("is_vaccination", False))
                    v_date = format_date_str(item.get("vaccination_date"))
                    
                    if not is_vac and v_date:
                        if from_date_str <= v_date <= to_date_str:
                            v_id = item.get("vaccination_id")
                            v_name = master_map.get(v_id, f"Vaccine #{v_id}")
                            pending_items.append({
                                "vaccination_id": v_id,
                                "vaccination_name": v_name,
                                "vaccination_date": v_date,
                            })
            
            if pending_items:
                uhid_list.append(r_uhid)
                pending_patients.append({
                    "uhid": r_uhid,
                    "mother_uhid": r_mother_uhid or "",
                    "record_date": format_date_str(r_date),
                    "pending_count": len(pending_items),
                    "pending_vaccines": pending_items,
                })

        # Join patient info and calculate per-patient WhatsApp sent count
        template_name = (os.getenv("BOTIFY_VACCINATION_TEMPLATE_NAME")).strip()
        today_date = datetime.now().date()
        start_of_today = datetime.combine(today_date, time.min)
        end_of_today = datetime.combine(today_date, time.max)

        if uhid_list:
            patients = list(patient_coll.find({"uhid": {"$in": uhid_list}}))
            p_map = {p.get("uhid"): p for p in patients}

            for item in pending_patients:
                p_info = p_map.get(item["uhid"], {})
                sal = p_info.get("salutation", "")
                fn = p_info.get("firstName", "")
                ln = p_info.get("lastName", "")
                full_name = f"{sal} {fn} {ln}".strip() if (fn or ln) else item["uhid"]
                
                item["patient_name"] = full_name
                item["gender"] = p_info.get("gender", "")
                item["age"] = p_info.get("age")
                item["mobilePhone"] = p_info.get("mobilePhone", "")
                if not item["mother_uhid"] and p_info.get("mothers_uhid_no"):
                    item["mother_uhid"] = p_info.get("mothers_uhid_no")

                try:
                    p_sent_count = CommunicationLog.objects.filter(
                        patient_id=str(item["uhid"]),
                        type="WhatsApp",
                        status="Success",
                        created_date__gte=start_of_today,
                        created_date__lte=end_of_today
                    ).count()
                except Exception:
                    p_sent_count = 0

                item["whatsapp_sent_count"] = p_sent_count

        # Total WhatsApp reminders sent today across all patients
        try:
            whatsapp_sent_count = CommunicationLog.objects.filter(
                type="WhatsApp",
                status="Success",
                created_date__gte=start_of_today,
                created_date__lte=end_of_today
            ).count()
        except Exception:
            whatsapp_sent_count = 0

        return Response({
            "success": True,
            "from_date": from_date_str,
            "to_date": to_date_str,
            "total_count": len(pending_patients),
            "whatsapp_sent_count": whatsapp_sent_count,
            "data": pending_patients
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error fetching pending vaccinations: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['POST', 'PUT', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def save_patient_vaccination(request):
    """
    Create or update (patch) patient vaccination document directly in hospital_patientVaccination collection.
    Uses update_one({"uhid": uhid}, {"$set": update_doc}) to guarantee existing document is PATCHED in-place!
    """
    client = None
    try:
        client, db = get_hms_db()
        vacc_coll = db['hospital_patientVaccination']
        master_coll = db['hospital_vaccinationMaster']

        payload = request.data
        uhid = str(payload.get("uhid", "")).strip()
        mother_uhid = str(payload.get("mother_uhid") or payload.get("mothers_uhid_no") or "").strip()
        raw_record_date = payload.get("date") or datetime.today().strftime('%Y-%m-%d')
        vaccination_details = payload.get("vaccination_details", [])

        user_id =payload.get("auth-user-id")
        branch_code =payload.get("auth-branch-code")
        hospital_code =payload.get("auth-hospital-code")
        if not uhid:
            return Response({"success": False, "error": "UHID is required"}, status=status.HTTP_400_BAD_REQUEST)

        record_datetime = parse_to_datetime(raw_record_date)

        sanitized_details = []
        for v in vaccination_details:
            try:
                v_id = int(v.get("vaccination_id"))
            except (ValueError, TypeError):
                continue
            
            raw_v_date = v.get("vaccination_date") or raw_record_date
            is_vac = bool(v.get("is_vaccination", False))

            vac_date_dt = parse_to_datetime(raw_v_date)
            
            if is_vac:
                raw_vaccinated_date = v.get("vaccinated_date") or raw_v_date
                vaccinated_date_dt = parse_to_datetime(raw_vaccinated_date)
            else:
                vaccinated_date_dt = None

            sanitized_details.append({
                "vaccination_id": v_id,
                "vaccination_date": vac_date_dt,
                "vaccinated_date": vaccinated_date_dt,
                "is_vaccination": is_vac
            })

        now_dt = datetime.now()

        existing = vacc_coll.find_one({"uhid": uhid})
        if existing:
            update_doc = {
                "mother_uhid": mother_uhid,
                "date": record_datetime,
                "vaccination_details": sanitized_details,
                "lastmodified_by": user_id,
                "lastmodified_date": now_dt,
                "branch_code": branch_code,
                "hospital_code": hospital_code,
                "is_active": True,
            }
            vacc_coll.update_one({"uhid": uhid}, {"$set": update_doc})
            message = "Vaccination record updated successfully."
        else:
            new_doc = {
                "uhid": uhid,
                "mother_uhid": mother_uhid,
                "date": record_datetime,
                "vaccination_details": sanitized_details,
                "created_by": user_id,
                "created_date": now_dt,
                "lastmodified_by": user_id,
                "lastmodified_date": now_dt,
                "branch_code": branch_code,
                "hospital_code": hospital_code,
                "is_active": True,
            }
            vacc_coll.insert_one(new_doc)
            message = "Vaccination record created successfully."

        masters = list(master_coll.find({}, {"_id": 0}))
        master_map = {m["vaccination_id"]: m.get("vaccination_name", "") for m in masters if "vaccination_id" in m}

        doc = vacc_coll.find_one({"uhid": uhid})
        data = serialize_doc(doc, master_map)

        return Response({
            "success": True,
            "message": message,
            "data": data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error saving patient vaccination: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


def send_whatsapp_vaccination_reminder(patient_id, patient_name, phone, vaccine_names_str, scheduled_date_str, force=False):
    """
    Sends WhatsApp vaccination reminder using Botify API template.
    Template variables:
      {{1}} = Patient Name
      {{2}} = Vaccine Name(s)
      {{3}} = Scheduled Date
    Logs outcome in CommunicationLog model.
    """
    clean_phone = re.sub(r'\D', '', str(phone or ''))
    if len(clean_phone) == 10:
        clean_phone = f"91{clean_phone}"

    template_name = get_vaccination_template_name()
    botify_apikey = (os.getenv("BOTIFY_API_KEY") or "").strip()

    if not clean_phone or len(clean_phone) < 10:
        err_msg = f"Invalid mobile phone number: '{phone}' for patient {patient_name} ({patient_id})"
        logger.warning(err_msg)
        try:
            CommunicationLog.objects.create(
                patient_id=str(patient_id or ''),
                patient_name=str(patient_name or patient_id or ''),
                type="WhatsApp",
                sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
                recipient=str(phone or ''),
                status="Failed",
                details=err_msg,
                template_name=template_name,
                created_by="system",
                branch_code="SHB001",
                hospital_code="SH001"
            )
        except Exception as log_ex:
            logger.error(f"Error logging failed CommunicationLog: {str(log_ex)}")
        return {"success": False, "error": err_msg}

    # Duplicate check: check if already sent today for this patient_id, template_name, and status == 'Success'
    if not force:
        today_date = datetime.now().date()
        start_of_today = datetime.combine(today_date, time.min)
        end_of_today = datetime.combine(today_date, time.max)
        try:
            already_sent = CommunicationLog.objects.filter(
                patient_id=str(patient_id),
                template_name=template_name,
                status="Success",
                created_date__gte=start_of_today,
                created_date__lte=end_of_today
            ).exists()
            if already_sent:
                msg = f"Reminder already sent today for patient {patient_name} ({patient_id}) due on {scheduled_date_str}"
                logger.info(msg)
                return {"success": True, "skipped": True, "message": msg}
        except Exception as dup_ex:
            logger.warning(f"Duplicate check warning: {str(dup_ex)}")

    if botify_apikey.startswith("Bearer "):
        clean_api_key = botify_apikey[7:].strip()
        auth_header = botify_apikey
    else:
        clean_api_key = botify_apikey
        auth_header = f"Bearer {botify_apikey}"

    botify_url = "https://login.botify.in/api/whatsapp/external"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }

    # {{1}} = Patient Name, {{2}} = Vaccine Name(s), {{3}} = Vaccination Date
    template_data = [str(patient_name or patient_id), str(vaccine_names_str), str(scheduled_date_str)]

    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "text": str(p)
                } for p in template_data
            ]
        }
    ]

    body_payload = {
        "to": clean_phone,
        "type": "template",
        "templateName": template_name,
        "templateData": template_data,
        "components": components
    }

    try:
        r = requests.post(botify_url, json=body_payload, headers=headers, timeout=20)
        try:
            response_json = r.json()
            is_success = r.status_code in [200, 201] and (
                response_json.get("success") is True or
                response_json.get("status") in [True, "success", "200", 200] or
                response_json.get("result") == "success"
            )
        except ValueError:
            response_json = {}
            is_success = r.status_code in [200, 201]

        # Fallback 1: If 3 params returned parameter count mismatch, try 2 params
        if not is_success and "does not match the expected number of params" in r.text:
            alt_template_data = [str(patient_name or patient_id), str(vaccine_names_str)]
            alt_components = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in alt_template_data]
                }
            ]
            alt_payload = {
                "to": clean_phone,
                "type": "template",
                "templateName": template_name,
                "templateData": alt_template_data,
                "components": alt_components
            }
            r_alt = requests.post(botify_url, json=alt_payload, headers=headers, timeout=20)
            try:
                alt_json = r_alt.json()
                if r_alt.status_code in [200, 201] and (
                    alt_json.get("success") is True or
                    alt_json.get("status") in [True, "success", "200", 200] or
                    alt_json.get("result") == "success"
                ):
                    r = r_alt
                    response_json = alt_json
                    is_success = True
            except Exception:
                pass

        if not is_success and r.status_code in [400, 404, 405]:
            params = {
                "apikey": clean_api_key,
                "contact": clean_phone,
                "template": template_name,
                "params": ",".join([str(p) for p in template_data])
            }
            r_fallback = requests.get(botify_url, params=params, timeout=20)
            try:
                fb_json = r_fallback.json()
                if r_fallback.status_code in [200, 201] and (
                    fb_json.get("success") is True or
                    fb_json.get("status") in [True, "success", "200", 200]
                ):
                    r = r_fallback
                    response_json = fb_json
                    is_success = True
            except Exception:
                pass

        status_str = "Success" if is_success else "Failed"
        details_text = f"Vaccination Reminder for {vaccine_names_str} due on {scheduled_date_str}. Botify Response: {r.text}"

        CommunicationLog.objects.create(
            patient_id=str(patient_id or ''),
            patient_name=str(patient_name or patient_id or ''),
            type="WhatsApp",
            sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
            recipient=clean_phone,
            status=status_str,
            details=details_text,
            template_name=template_name,
            created_by="system",
            branch_code="SHB001",
            hospital_code="SH001"
        )

        return {"success": is_success, "recipient": clean_phone, "response": response_json, "status_code": r.status_code}

    except Exception as e:
        err_text = f"Exception sending vaccination reminder WhatsApp to {clean_phone}: {str(e)}"
        logger.error(err_text)
        try:
            CommunicationLog.objects.create(
                patient_id=str(patient_id or ''),
                patient_name=str(patient_name or patient_id or ''),
                type="WhatsApp",
                sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
                recipient=clean_phone,
                status="Failed",
                details=err_text,
                template_name=template_name,
                created_by="system",
                branch_code="SHB001",
                hospital_code="SH001"
            )
        except Exception:
            pass
        return {"success": False, "error": str(e)}


def process_pending_vaccination_reminders(target_date=None, force=False, target_uhid=None):
    """
    Finds active patient vaccination records where is_vaccination is False and vaccination_date is target_date (default: tomorrow).
    Optional target_uhid parameter allows sending for a single specific patient.
    Sends WhatsApp reminders via Botify API and stores details in CommunicationLog.
    """
    if not target_date:
        target_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    client = None
    results = {
        "target_date": target_date,
        "total_patients_checked": 0,
        "reminders_sent": 0,
        "reminders_skipped": 0,
        "failed_sends": 0,
        "details": []
    }

    try:
        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']
        vacc_coll = db['hospital_patientVaccination']
        patient_coll = db['hospital_patient']

        masters = list(master_coll.find({}, {"_id": 0}))
        master_map = {m["vaccination_id"]: m.get("vaccination_name", "") for m in masters if "vaccination_id" in m}

        query = {"is_active": True}
        if target_uhid:
            query["uhid"] = str(target_uhid)

        records = list(vacc_coll.find(query))

        patients_due = {}

        for r in records:
            details = r.get('vaccination_details', [])
            r_uhid = r.get('uhid')
            if not r_uhid:
                continue

            pending_items = []
            for item in details:
                if isinstance(item, dict):
                    is_vac = bool(item.get("is_vaccination", False))
                    v_date = format_date_str(item.get("vaccination_date"))
                    
                    if not is_vac and v_date == target_date:
                        v_id = item.get("vaccination_id")
                        v_name = master_map.get(v_id, f"Vaccine #{v_id}")
                        pending_items.append(v_name)

            if pending_items:
                patients_due[r_uhid] = pending_items

        results["total_patients_checked"] = len(patients_due)

        if patients_due:
            uhid_list = list(patients_due.keys())
            patients = list(patient_coll.find({"uhid": {"$in": uhid_list}}))
            p_map = {p.get("uhid"): p for p in patients}

            for uhid, vaccine_names in patients_due.items():
                p_info = p_map.get(uhid, {})
                sal = p_info.get("salutation", "")
                fn = p_info.get("firstName", "")
                ln = p_info.get("lastName", "")
                patient_name = f"{sal} {fn} {ln}".strip() if (fn or ln) else uhid

                phone = p_info.get("mobilePhone") or p_info.get("phone") or p_info.get("mothers_mobile_no") or ""
                vaccine_names_str = ", ".join(vaccine_names)

                res = send_whatsapp_vaccination_reminder(
                    patient_id=uhid,
                    patient_name=patient_name,
                    phone=phone,
                    vaccine_names_str=vaccine_names_str,
                    scheduled_date_str=target_date,
                    force=force
                )

                if res.get("skipped"):
                    results["reminders_skipped"] += 1
                elif res.get("success"):
                    results["reminders_sent"] += 1
                else:
                    results["failed_sends"] += 1

                results["details"].append({
                    "uhid": uhid,
                    "patient_name": patient_name,
                    "phone": phone,
                    "vaccines": vaccine_names,
                    "status": "Skipped" if res.get("skipped") else ("Success" if res.get("success") else "Failed"),
                    "result": res
                })

        return results

    except Exception as e:
        logger.error(f"Error processing pending vaccination reminders: {str(e)}")
        results["error"] = str(e)
        return results
    finally:
        if client:
            client.close()


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def preview_vaccination_reminders_view(request):
    """
    API endpoint to preview patients due for vaccination reminders on a given date (default: tomorrow).
    Returns list of patients with:
      - uhid
      - patient_name
      - phone
      - vaccines (list & joined string)
      - scheduled_date
      - already_sent (True/False based on CommunicationLog status="Success")
    """
    try:
        date_param = request.data.get('date') or request.GET.get('date')
        if not date_param:
            date_param = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        client, db = get_hms_db()
        master_coll = db['hospital_vaccinationMaster']
        vacc_coll = db['hospital_patientVaccination']
        patient_coll = db['hospital_patient']

        masters = list(master_coll.find({}, {"_id": 0}))
        master_map = {m["vaccination_id"]: m.get("vaccination_name", "") for m in masters if "vaccination_id" in m}

        records = list(vacc_coll.find({"is_active": True}))
        template_name = get_vaccination_template_name()
        today_date = datetime.now().date()

        preview_list = []
        uhid_list = []
        due_map = {}

        for r in records:
            details = r.get('vaccination_details', [])
            r_uhid = r.get('uhid')
            if not r_uhid:
                continue

            pending_items = []
            for item in details:
                if isinstance(item, dict):
                    is_vac = bool(item.get("is_vaccination", False))
                    v_date = format_date_str(item.get("vaccination_date"))
                    
                    if not is_vac and v_date == date_param:
                        v_id = item.get("vaccination_id")
                        v_name = master_map.get(v_id, f"Vaccine #{v_id}")
                        pending_items.append(v_name)

            if pending_items:
                uhid_list.append(r_uhid)
                due_map[r_uhid] = pending_items

        if uhid_list:
            patients = list(patient_coll.find({"uhid": {"$in": uhid_list}}))
            p_map = {p.get("uhid"): p for p in patients}

            for uhid in uhid_list:
                vaccine_names = due_map.get(uhid, [])
                p_info = p_map.get(uhid, {})
                sal = p_info.get("salutation", "")
                fn = p_info.get("firstName", "")
                ln = p_info.get("lastName", "")
                patient_name = f"{sal} {fn} {ln}".strip() if (fn or ln) else uhid
                phone = p_info.get("mobilePhone") or p_info.get("phone") or p_info.get("mothers_mobile_no") or ""

                # Check if already sent today
                already_sent = False
                try:
                    start_of_today = datetime.combine(today_date, time.min)
                    end_of_today = datetime.combine(today_date, time.max)
                    already_sent = CommunicationLog.objects.filter(
                        patient_id=str(uhid),
                        template_name=template_name,
                        status="Success",
                        created_date__gte=start_of_today,
                        created_date__lte=end_of_today
                    ).exists()
                except Exception:
                    pass

                preview_list.append({
                    "uhid": uhid,
                    "patient_name": patient_name,
                    "phone": phone,
                    "vaccines": vaccine_names,
                    "vaccine_names_str": ", ".join(vaccine_names),
                    "scheduled_date": date_param,
                    "already_sent": already_sent,
                    "status_text": "Already Sent Today" if already_sent else "Ready to Send"
                })

        if client:
            client.close()

        return Response({
            "success": True,
            "target_date": date_param,
            "total_count": len(preview_list),
            "data": preview_list
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error previewing vaccination reminders: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def send_vaccination_reminders_view(request):
    """
    API endpoint for manual sending of WhatsApp vaccination reminders.
    Manual sends from the UI bypass duplicate checks (force=True by default).
    Query / Body params:
      - date: YYYY-MM-DD (default: tomorrow)
      - uhid: Single patient UHID (optional)
      - force: true/false (defaults to True for manual API trigger)
    """
    try:
        date_param = request.data.get('date') or request.GET.get('date')
        uhid_param = request.data.get('uhid') or request.GET.get('uhid')
        raw_force = request.data.get('force') if request.data.get('force') is not None else request.GET.get('force')
        
        # Manual send from UI defaults to force=True (bypasses duplicate check) unless explicitly passed as 'false'
        if raw_force is not None:
            force_param = str(raw_force).lower() == 'true'
        else:
            force_param = True

        results = process_pending_vaccination_reminders(target_date=date_param, force=force_param, target_uhid=uhid_param)
        return Response({"success": True, "data": results}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in send_vaccination_reminders_view: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
