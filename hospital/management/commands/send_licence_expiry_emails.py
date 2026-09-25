import time
from datetime import datetime, timedelta
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand
from django.utils import timezone

import os
from pymongo import MongoClient

mongo_url = os.getenv("GLOBAL_DB_HOST")
_client = MongoClient(mongo_url)
_global_db = _client["Global"]
_hms_db = _client["HMS"]

profile_collection = _global_db["backend_diagnostics_profile"]
department_collection = _global_db["backend_diagnostics_Departments"]
company_secretary_collection = _hms_db["hospital_licencemasterdetails"]
licence_email_logs_collection = _hms_db["hospital_licence_email_logs"]



# ✅ Thresholds (IMPORTANT: highest → lowest)
THRESHOLDS = [
    (90, "is_90days"),
    (60, "is_60days"),
    (30, "is_30days"),
    (7,  "is_7days"),
    (1,  "is_1day"),
]


# ✅ Get employee email(s) & department code(s) — incharge / respective_person
def get_employee_emails_and_departments(employee_ids):
    if not employee_ids:
        return [], []
    if isinstance(employee_ids, str):
        employee_ids = [employee_ids]

    profiles = profile_collection.find(
        {"employeeId": {"$in": employee_ids}},
        {"email": 1, "department": 1, "_id": 0},
    )
    emails = []
    dept_codes = []
    for p in profiles:
        if p.get("email"):
            emails.append(p["email"].strip())
        if p.get("department"):
            dept_codes.append(str(p["department"]).strip())
    return emails, dept_codes


# ✅ Get department email(s) from backend_diagnostics_Departments
def get_department_emails(department_codes):
    if not department_codes:
        return []

    departments = department_collection.find(
        {"department_code": {"$in": department_codes}},
        {"email": 1, "_id": 0},
    )
    dept_emails = []
    for d in departments:
        email = d.get("email")
        if email and isinstance(email, str) and email.strip():
            dept_emails.append(email.strip())
    return dept_emails



# ✅ Format date — strips time portion from datetime or date objects
def format_date(value):
    if not value:
        return "N/A"
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y")
    # Handle string like "2026-06-17 00:00:00"
    try:
        return datetime.strptime(str(value).split(" ")[0], "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return str(value).split(" ")[0]


# ✅ Email body
def build_email_body(record, days_before):
    return f"""Dear Team,

Kindly be informed that the following licence is scheduled to expire within {days_before} day(s) from today. We request you to initiate the necessary renewal process at the earliest to avoid any compliance issues.

Licence Details:
─────────────────────────────────────────
  Licence Name          : {record.get('licence_name')}
  Licence / Case / Ref# : {record.get('license_number')}
  Valid From            : {format_date(record.get('valid_from'))}
  Expiry Date           : {format_date(record.get('expiry_date'))}
─────────────────────────────────────────

Please ensure the renewal is completed well before the expiry date to maintain uninterrupted operations.

For any clarifications, please contact the Company Secretary Department.

Regards,
Shanmuga Hospital Limited
Company Secretary Department
"""


# ✅ MAIN FUNCTION
def run_licence_expiry_check():
    today = timezone.now().date()

    sent = []
    skipped = []

    for record in company_secretary_collection.find({}):

        expiry_date = record.get("expiry_date")
        if not expiry_date:
            continue

        # ✅ Convert datetime → date
        expiry_date_only = (
            expiry_date.date()
            if isinstance(expiry_date, datetime)
            else expiry_date
        )

        diff_days = (expiry_date_only - today).days

        # ❌ Skip expired
        if diff_days < 0:
            continue

        print(f"\n📄 {record.get('licence_name')} → Days left: {diff_days}")

        updates = {}

        # ✅ LOOP THRESHOLDS
        for days_before, flag_field in THRESHOLDS:

            already_sent = bool(record.get(flag_field, False))

            print(f"Checking {days_before} days → already_sent={already_sent}")

            # ✅ YOUR REQUIRED LOGIC
            if diff_days <= days_before and not already_sent:

                print(f"👉 Triggering {days_before}-day email")

                incharge_emails, incharge_depts = get_employee_emails_and_departments(record.get("incharge"))
                respective_person_emails, respective_depts = get_employee_emails_and_departments(record.get("respective_person"))

                incharge_emails = list(dict.fromkeys(incharge_emails))

                all_dept_codes = list(set(incharge_depts + respective_depts))
                dept_emails = get_department_emails(all_dept_codes)

                cc_emails = []
                for mail in respective_person_emails + dept_emails:
                    if mail not in incharge_emails and mail not in cc_emails:
                        cc_emails.append(mail)

                print("Incharge Emails:", incharge_emails)
                print("CC Emails:", cc_emails)

                if not incharge_emails:
                    now_dt = timezone.now()
                    skip_reason = "No incharge email"
                    skipped.append({
                        "licence": record.get("licence_name"),
                        "reason": skip_reason,
                        "threshold": days_before
                    })
                    print("❌ Skipped: No email")

                    # ✅ Log skipped to DB
                    licence_email_logs_collection.insert_one({
                        "licence_id": str(record.get("_id")),
                        "s_no": record.get("s_no"),
                        "licence_name": record.get("licence_name"),
                        "license_number": record.get("license_number"),
                        "valid_from": format_date(record.get("valid_from")),
                        "expiry_date": format_date(record.get("expiry_date")),
                        "threshold_days": days_before,
                        "threshold_flag": flag_field,
                        "days_left": diff_days,
                        "to_emails": [],
                        "cc_emails": cc_emails,
                        "status": "Skipped",
                        "error_message": skip_reason,
                        "created_date": now_dt,
                    })
                    continue


                try:
                    subject = f"Licence Expiry Reminder - {record.get('licence_name')}"
                    email_body = build_email_body(record, days_before)

                    cs_email = getattr(settings, 'HMS_CS_EMAIL', None) or os.getenv('HMS_CS_EMAIL') or getattr(settings, 'EMAIL_HOST_USER', 'cs@smrft.org')
                    cs_password = getattr(settings, 'HMS_CS_EMAIL_PASSWORD', None) or os.getenv('HMS_CS_EMAIL_PASSWORD') or getattr(settings, 'EMAIL_HOST_PASSWORD', None)

                    # ✅ Authenticate SMTP using HMS_CS_EMAIL credentials
                    # so the mail is truly sent FROM cs@smrft.org (env-specific)
                    cs_connection = get_connection(
                        host=getattr(settings, 'EMAIL_HOST', 'smtp.gmail.com'),
                        port=getattr(settings, 'EMAIL_PORT', 587),
                        username=cs_email,
                        password=cs_password,
                        use_tls=getattr(settings, 'EMAIL_USE_TLS', True),
                    )

                    email = EmailMessage(
                        subject=subject,
                        body=email_body,
                        from_email=cs_email,
                        to=incharge_emails,
                        cc=cc_emails,
                        connection=cs_connection,
                    )

                    email.send()

                    print(f"✅ Email sent for {days_before} days")

                    # ✅ Mark as sent
                    updates[flag_field] = True

                    now_dt = timezone.now()
                    log_doc = {
                        "licence_id": str(record.get("_id")),
                        "s_no": record.get("s_no"),
                        "licence_name": record.get("licence_name"),
                        "license_number": record.get("license_number"),
                        "valid_from": format_date(record.get("valid_from")),
                        "expiry_date": format_date(record.get("expiry_date")),
                        "renewal_date": format_date(record.get("renewal_date")),
                        "threshold_days": days_before,
                        "threshold_flag": flag_field,
                        "days_left": diff_days,
                        "from_email": cs_email,
                        "to_emails": incharge_emails,
                        "cc_emails": cc_emails,
                        "subject": subject,
                        "body": email_body,
                        "status": "Sent",
                        "error_message": None,
                        "sent_at": now_dt,
                        "created_date": now_dt,
                    }

                    # ✅ 1. Insert into dedicated log collection
                    licence_email_logs_collection.insert_one(log_doc)

                    # ✅ 2. Append to licence document history/email_logs
                    company_secretary_collection.update_one(
                        {"_id": record["_id"]},
                        {
                            "$push": {
                                "email_logs": {
                                    "threshold_days": days_before,
                                    "threshold_flag": flag_field,
                                    "days_left": diff_days,
                                    "from_email": cs_email,
                                    "to_emails": incharge_emails,
                                    "cc_emails": cc_emails,
                                    "subject": subject,
                                    "status": "Sent",
                                    "sent_at": now_dt
                                }
                            }
                        }
                    )

                    sent.append({
                        "licence": record.get("licence_name"),
                        "threshold": days_before,
                        "days_left": diff_days
                    })

                    break   # ✅ IMPORTANT: stop after first match

                except Exception as e:
                    print("❌ EMAIL ERROR:", str(e))
                    err_msg = str(e)
                    now_dt = timezone.now()

                    # ✅ Log failure to DB
                    licence_email_logs_collection.insert_one({
                        "licence_id": str(record.get("_id")),
                        "s_no": record.get("s_no"),
                        "licence_name": record.get("licence_name"),
                        "license_number": record.get("license_number"),
                        "valid_from": format_date(record.get("valid_from")),
                        "expiry_date": format_date(record.get("expiry_date")),
                        "threshold_days": days_before,
                        "threshold_flag": flag_field,
                        "days_left": diff_days,
                        "from_email": cs_email if 'cs_email' in locals() else None,
                        "to_emails": incharge_emails,
                        "cc_emails": cc_emails,
                        "subject": subject if 'subject' in locals() else f"Licence Expiry Reminder - {record.get('licence_name')}",
                        "status": "Failed",
                        "error_message": err_msg,
                        "sent_at": now_dt,
                        "created_date": now_dt,
                    })

                    company_secretary_collection.update_one(
                        {"_id": record["_id"]},
                        {
                            "$push": {
                                "email_logs": {
                                    "threshold_days": days_before,
                                    "threshold_flag": flag_field,
                                    "days_left": diff_days,
                                    "status": "Failed",
                                    "error_message": err_msg,
                                    "sent_at": now_dt
                                }
                            }
                        }
                    )

                    skipped.append({
                        "licence": record.get("licence_name"),
                        "reason": err_msg,
                        "threshold": days_before
                    })

        # ✅ Update MongoDB flags
        if updates:
            company_secretary_collection.update_one(
                {"_id": record["_id"]},
                {"$set": updates}
            )

    return {
        "total_sent": len(sent),
        "total_skipped": len(skipped),
        "sent": sent,
        "skipped": skipped
    }


# ✅ DJANGO COMMAND
class Command(BaseCommand):
    help = "Send licence expiry reminder emails"

    def add_arguments(self, parser):
        parser.add_argument(
            "--daemon",
            action="store_true",
            help="Run continuously as a daemon, triggering at --run-hour every day"
        )
        parser.add_argument(
            "--run-hour",
            type=int,
            default=10,  # 10:00 AM
            help="Hour of day (24h format) to send emails daily (default: 10)"
        )
        parser.add_argument(
            "--run-minute",
            type=int,
            default=0,
            help="Minute of hour to send emails daily (default: 0)"
        )

    def handle(self, *args, **options):
        import sys
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
            except Exception:
                pass

        daemon = options.get("daemon")
        run_hour = options.get("run_hour", 10)
        run_minute = options.get("run_minute", 0)

        if daemon:
            self.stdout.write(
                f"[START] Starting Licence Expiry Daemon — will run daily at "
                f"{run_hour:02d}:{run_minute:02d}...\n"
            )

            while True:
                now = datetime.now()

                # ✅ Calculate next run time (today or tomorrow at run_hour:run_minute)
                next_run = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
                if now >= next_run:
                    # Already past today's scheduled time — wait for tomorrow
                    next_run += timedelta(days=1)

                sleep_seconds = (next_run - now).total_seconds()
                self.stdout.write(
                    f"[WAIT] Next run at {next_run.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"(sleeping {int(sleep_seconds // 3600)}h "
                    f"{int((sleep_seconds % 3600) // 60)}m)...\n"
                )
                time.sleep(sleep_seconds)

                self.stdout.write(f"\n[TIME] Running at {timezone.now()}\n")

                result = run_licence_expiry_check()

                self.stdout.write("\n[RESULT]")
                self.stdout.write(f"Sent: {result['total_sent']}")
                self.stdout.write(f"Skipped: {result['total_skipped']}")

        else:
            self.stdout.write("[START] Running once...\n")

            result = run_licence_expiry_check()

            self.stdout.write("\n[FINAL RESULT]")
            self.stdout.write(f"Sent: {result['total_sent']}")
            self.stdout.write(f"Skipped: {result['total_skipped']}")

