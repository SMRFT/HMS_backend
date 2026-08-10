import time
from datetime import datetime
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
company_secretary_collection = _hms_db["hospital_licencemasterdetails"]


# ✅ Thresholds (IMPORTANT: highest → lowest)
THRESHOLDS = [
    (90, "is_90days"),
    (60, "is_60days"),
    (30, "is_30days"),
    (7,  "is_7days"),
    (1,  "is_1day"),
]


# ✅ Get employee email(s) — incharge / respective_person are stored as
# arrays of employeeId now (multi-select), so this takes a list and
# returns a list of emails via a single $in query instead of one lookup
# per id. Also tolerates a lone string for any record that predates the
# multi-select change.
def get_employee_emails(employee_ids):
    if not employee_ids:
        return []
    if isinstance(employee_ids, str):
        employee_ids = [employee_ids]

    profiles = profile_collection.find(
        {"employeeId": {"$in": employee_ids}},
        {"email": 1, "_id": 0},
    )
    return [p["email"] for p in profiles if p.get("email")]


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

                incharge_emails = get_employee_emails(record.get("incharge"))
                respective_person_emails = get_employee_emails(record.get("respective_person"))

                print("Incharge Emails:", incharge_emails)

                if not incharge_emails:
                    skipped.append({
                        "licence": record.get("licence_name"),
                        "reason": "No incharge email",
                        "threshold": days_before
                    })
                    print("❌ Skipped: No email")
                    continue


                try:
                    subject = f"Licence Expiry Reminder - {record.get('licence_name')}"

                    cs_email = getattr(settings, 'HMS_CS_EMAIL', None) or os.getenv('HMS_CS_EMAIL') or getattr(settings, 'EMAIL_HOST_USER', 'najmasmrft@gmail.com')
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
                        body=build_email_body(record, days_before),
                        from_email=cs_email,
                        to=incharge_emails,
                        cc=respective_person_emails,
                        connection=cs_connection,
                    )

                    email.send()

                    print(f"✅ Email sent for {days_before} days")

                    # ✅ Mark as sent
                    updates[flag_field] = True

                    sent.append({
                        "licence": record.get("licence_name"),
                        "threshold": days_before,
                        "days_left": diff_days
                    })

                    break   # ✅ IMPORTANT: stop after first match

                except Exception as e:
                    print("❌ EMAIL ERROR:", str(e))

                    skipped.append({
                        "licence": record.get("licence_name"),
                        "reason": str(e),
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
            help="Run continuously as a daemon"
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=86400,  # 24 hours
            help="Interval in seconds (default: 86400)"
        )

    def handle(self, *args, **options):
        daemon = options.get("daemon")
        interval = options.get("interval")

        if daemon:
            self.stdout.write("🚀 Starting Licence Expiry Daemon...\n")

            while True:
                self.stdout.write(f"\n⏰ Running at {timezone.now()}\n")

                result = run_licence_expiry_check()

                self.stdout.write("\n📊 RESULT")
                self.stdout.write(f"✅ Sent: {result['total_sent']}")
                self.stdout.write(f"❌ Skipped: {result['total_skipped']}")

                self.stdout.write(f"\n⏳ Sleeping for {interval} seconds...\n")
                time.sleep(interval)

        else:
            self.stdout.write("🚀 Running once...\n")

            result = run_licence_expiry_check()

            self.stdout.write("\n📊 FINAL RESULT")
            self.stdout.write(f"✅ Sent: {result['total_sent']}")
            self.stdout.write(f"❌ Skipped: {result['total_skipped']}")