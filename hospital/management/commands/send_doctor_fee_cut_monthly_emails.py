from django.core.management.base import BaseCommand
from django.utils import timezone
import datetime
import datetime as dt
import os
import time
import traceback
import pytz
from pymongo import MongoClient
from django.core.mail import EmailMultiAlternatives, get_connection
from django.conf import settings
from hospital.models import CommunicationLog


def to_float(val):
    if val is None:
        return 0.0
    if isinstance(val, dict):
        if '$numberDecimal' in val:
            val = val['$numberDecimal']
        elif 'amount' in val:
            val = val['amount']
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return 0.0


class Command(BaseCommand):
    help = "Autosend monthly Doctor Fee Cut statement emails to individual doctors. Runs once or in daemon mode."

    def add_arguments(self, parser):
        parser.add_argument('--month', type=int, help='Month number (1-12)')
        parser.add_argument('--year', type=int, help='Year (e.g. 2026)')
        parser.add_argument('--daemon', action='store_true', help='Run in daemon mode checking daily on 1st of the month')
        parser.add_argument('--now', action='store_true', help='Run the report once immediately and exit')
        parser.add_argument('--force', action='store_true', help='Bypass duplicate check and force send emails')

    def send_report(self, req_month=None, req_year=None, force=False):
        today = timezone.now().date()

        # Calculate exact previous month date range (handles 28, 29, 30, 31 day months)
        if req_month and req_year:
            m = int(req_month)
            y = int(req_year)
            first_date = datetime.date(y, m, 1)
            if m == 12:
                next_first = datetime.date(y + 1, 1, 1)
            else:
                next_first = datetime.date(y, m + 1, 1)
            last_date = next_first - datetime.timedelta(days=1)
        else:
            first_date_current_month = today.replace(day=1)
            last_date = first_date_current_month - datetime.timedelta(days=1)
            first_date = last_date.replace(day=1)

        month_name = last_date.strftime("%B %Y")
        self.stdout.write(self.style.SUCCESS(f"Processing Doctor Fee Cut Email Statements for: {month_name}"))

        from_dt = datetime.datetime.combine(first_date, datetime.time.min)
        to_dt = datetime.datetime.combine(last_date, datetime.time.max)

        mongo_host = os.getenv('GLOBAL_DB_HOST') or 'mongodb://localhost:27017/'
        global_db_name = os.getenv('GLOBAL_DB_NAME') or 'Global'
        client = MongoClient(mongo_host)
        db = client['HMS']
        global_db = client[global_db_name]

        # 1. Query Approved fee cuts
        fee_cuts = list(db['hospital_doctorfeecuts'].find({"status": "Approved", "is_active": {"$ne": False}}))

        filtered_fee_cuts = []
        emp_ids = set()

        for f in fee_cuts:
            rec_date_raw = f.get('date') or f.get('approved_date') or f.get('created_date')
            rec_dt = None
            if isinstance(rec_date_raw, (datetime.datetime, datetime.date)):
                rec_dt = rec_date_raw
            elif rec_date_raw:
                try:
                    rec_dt = datetime.datetime.fromisoformat(str(rec_date_raw).replace("Z", "+00:00"))
                except Exception:
                    pass

            if rec_dt and (from_dt <= rec_dt.replace(tzinfo=None) <= to_dt):
                filtered_fee_cuts.append((f, rec_dt))
                for bd in f.get('doctor_breakdown', []):
                    if bd.get('doctor_id'):
                        emp_ids.add(str(bd.get('doctor_id')).strip())

        if not filtered_fee_cuts:
            self.stdout.write(self.style.WARNING(f"No approved fee cut records found for {month_name}."))
            return

        # 2. Fetch employee profile emails
        clean_ids = list(emp_ids)
        cursor = global_db['backend_diagnostics_profile'].find(
            {"employeeId": {"$in": clean_ids}},
            {"employeeId": 1, "employeeName": 1, "email": 1, "officialEmail": 1, "personalEmail": 1, "_id": 0}
        )
        emp_profiles = {}
        for doc in cursor:
            e_id = doc.get("employeeId")
            if e_id:
                name = doc.get("employeeName", "")
                email = doc.get("email") or doc.get("officialEmail") or doc.get("personalEmail") or ""
                emp_profiles[e_id] = {"name": name, "email": email}

        # 3. Group by Doctor ID
        doctor_statements = {}
        billing_docs = list(db['hospital_dischargebilling'].find({"is_cancelled": {"$ne": True}}))
        billing_by_ip = {b.get('ip_number'): b for b in billing_docs if b.get('ip_number')}
        admissions = list(db['hospital_admission'].find({"is_cancelled": {"$ne": True}}))
        adm_by_ip = {a.get('ipNumber'): a for a in admissions if a.get('ipNumber')}

        for claim, rec_dt in filtered_fee_cuts:
            ip = claim.get('ip_number')
            uhid = claim.get('uhid', 'N/A')
            date_str = rec_dt.strftime("%Y-%m-%d")

            bill = billing_by_ip.get(ip, {})
            adm = adm_by_ip.get(ip, {})

            patient_name = adm.get('patientName') or adm.get('patient_name') or bill.get('patient_name') or ""
            if not patient_name and uhid and uhid != 'N/A':
                p_obj = db['hospital_patient'].find_one({"uhid": uhid})
                if p_obj:
                    patient_name = f"{p_obj.get('firstName', '')} {p_obj.get('lastName', '')}".strip()
            if not patient_name:
                patient_name = "N/A"

            for bd in claim.get('doctor_breakdown', []):
                doc_id = str(bd.get('doctor_id', '')).strip()
                if not doc_id:
                    continue

                profile = emp_profiles.get(doc_id, {})
                doc_name = profile.get('name') or f"Doctor #{doc_id}"
                doc_email = profile.get('email', '').strip()

                req_amt = to_float(bd.get('requested_amount', 0.0))
                app_amt = to_float(bd.get('approved_amount', 0.0))
                role = str(bd.get('role', 'Doctor'))

                if doc_id not in doctor_statements:
                    doctor_statements[doc_id] = {
                        "doctor_id": doc_id,
                        "doctor_name": doc_name,
                        "email": doc_email,
                        "rows": [],
                        "total_requested": 0.0,
                        "total_approved": 0.0
                    }

                doctor_statements[doc_id]["rows"].append({
                    "date": date_str,
                    "patient_name": patient_name,
                    "uhid": uhid,
                    "ip_number": ip,
                    "role": role,
                    "requested_amount": req_amt,
                    "approved_amount": app_amt
                })
                doctor_statements[doc_id]["total_requested"] += req_amt
                doctor_statements[doc_id]["total_approved"] += app_amt

        # 4. Send Emails with Duplicate Check using CommunicationLog
        sent_count = 0
        skipped_count = 0

        acc_email = getattr(settings, 'HMS_ACC_EMAIL', None) or os.getenv('HMS_ACC_EMAIL', 'najmasmrft@gmail.com')
        acc_password = getattr(settings, 'HMS_ACC_EMAIL_PASSWORD', None) or os.getenv('HMS_ACC_EMAIL_PASSWORD')

        email_connection = get_connection(
            backend=getattr(settings, 'EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend'),
            host=getattr(settings, 'EMAIL_HOST', os.getenv('EMAIL_HOST', 'smtp.gmail.com')),
            port=int(getattr(settings, 'EMAIL_PORT', os.getenv('EMAIL_PORT', 587))),
            username=acc_email,
            password=acc_password,
            use_tls=getattr(settings, 'EMAIL_USE_TLS', True),
        )
        from_email = acc_email

        for doc_id, stmt in doctor_statements.items():
            doc_name = stmt["doctor_name"]
            to_email = stmt["email"]
            rows = stmt["rows"]
            tot_req = stmt["total_requested"]
            tot_app = stmt["total_approved"]

            if not to_email:
                self.stdout.write(self.style.WARNING(f"Skipping Dr. {doc_name} (ID: {doc_id}) - No email address found in profile."))
                continue

            # Duplicate check using CommunicationLog
            if not force:
                already_sent = CommunicationLog.objects.filter(
                    template_name="doctor_fee_cut_monthly_statement",
                    patient_id=str(doc_id),
                    status="Success",
                    details__icontains=month_name
                ).exists()

                if already_sent:
                    self.stdout.write(self.style.WARNING(f"Statement email for {month_name} already sent to Dr. {doc_name} (ID: {doc_id}). Skipping to prevent duplicates."))
                    skipped_count += 1
                    continue

            subject = f"Doctor Fee Cut Statement - {month_name} ({doc_name})"

            table_rows_html = ""
            for idx, r in enumerate(rows, 1):
                table_rows_html += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: center;">{idx}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1;">{r['date']}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1;">
                        <strong>{r['patient_name']}</strong><br>
                        <span style="color: #64748b; font-size: 11px;">IP: {r['ip_number']} | UHID: {r['uhid']}</span>
                    </td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1;">{r['role']}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: right;">₹ {r['requested_amount']:,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: right; font-weight: bold; color: #0284c7;">₹ {r['approved_amount']:,.2f}</td>
                </tr>
                """

            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #334155; line-height: 1.6; background-color: #f8fafc; margin: 0; padding: 20px; }}
                    .card {{ max-width: 700px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); overflow: hidden; border: 1px solid #e2e8f0; }}
                    .header {{ background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%); color: #ffffff; padding: 20px 25px; text-align: center; }}
                    .header h2 {{ margin: 0; font-size: 20px; font-weight: 600; }}
                    .header p {{ margin: 5px 0 0 0; opacity: 0.9; font-size: 13px; }}
                    .body {{ padding: 25px; }}
                    table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px; }}
                    th {{ background-color: #f1f5f9; color: #1e293b; text-align: left; padding: 10px; border: 1px solid #cbd5e1; font-weight: 600; }}
                    .total-row {{ background-color: #f8fafc; font-weight: bold; font-size: 14px; }}
                    .footer {{ background-color: #f1f5f9; padding: 15px 25px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="header">
                        <h2>Shanmuga Hospital - Doctor Fee Cut Statement</h2>
                        <p>Approved Statement for <strong>{month_name}</strong></p>
                    </div>
                    <div class="body">
                        <p>Dear Dr. <strong>{doc_name}</strong>,</p>
                        <p>Please find below your approved Doctor Fee Cut summary for the month of <strong>{month_name}</strong>:</p>
                        
                        <table>
                            <thead>
                                <tr>
                                    <th style="width: 40px; text-align: center;">S.No</th>
                                    <th>Date</th>
                                    <th>Patient Details</th>
                                    <th>Role</th>
                                    <th style="text-align: right;">Requested Amount</th>
                                    <th style="text-align: right;">Approved Amount</th>
                                </tr>
                            </thead>
                            <tbody>
                                {table_rows_html}
                                <tr class="total-row">
                                    <td colspan="4" style="padding: 10px; border: 1px solid #cbd5e1; text-align: right;"><strong>Subtotal (Total Approved Income):</strong></td>
                                    <td style="padding: 10px; border: 1px solid #cbd5e1; text-align: right;">₹ {tot_req:,.2f}</td>
                                    <td style="padding: 10px; border: 1px solid #cbd5e1; text-align: right; color: #0284c7;"><strong>₹ {tot_app:,.2f}</strong></td>
                                </tr>
                            </tbody>
                        </table>

                        <p style="margin-top: 25px; font-size: 13px; color: #475569;">
                            If you have any questions or require further clarification regarding this statement, please contact the Shanmuga Hospital Accounts / Administration department.
                        </p>
                        <p style="font-size: 13px; color: #334155;">
                            Best regards,<br>
                            <strong>Shanmuga Hospital Administration</strong>
                        </p>
                    </div>
                    <div class="footer">
                        <p>This is an automated monthly statement. Please do not reply directly to this email.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            try:
                msg = EmailMultiAlternatives(subject, f"Dear Dr. {doc_name},\nYour approved doctor fee cut total for {month_name} is Rs. {tot_app:.2f}.", from_email, [to_email], connection=email_connection)
                msg.attach_alternative(html_content, "text/html")
                msg.send(fail_silently=False)
                sent_count += 1
                self.stdout.write(self.style.SUCCESS(f"Successfully sent statement email to Dr. {doc_name} ({to_email})"))

                # Log Success in CommunicationLog
                try:
                    CommunicationLog.objects.create(
                        patient_id=str(doc_id),
                        patient_name=f"Dr. {doc_name}",
                        type="Email",
                        sender=from_email,
                        recipient=to_email,
                        status="Success",
                        details=f"Doctor Fee Cut Statement for {month_name}. Total Approved: ₹{tot_app:,.2f}, Patients: {len(rows)}",
                        template_name="doctor_fee_cut_monthly_statement",
                        created_by="system",
                        hospital_code="SH001",
                        branch_code="SHB001"
                    )
                except Exception as log_err:
                    self.stdout.write(self.style.WARNING(f"CommunicationLog error: {log_err}"))

            except Exception as mail_err:
                self.stdout.write(self.style.ERROR(f"Failed to send email to Dr. {doc_name} ({to_email}): {mail_err}"))

                # Log Failure in CommunicationLog
                try:
                    CommunicationLog.objects.create(
                        patient_id=str(doc_id),
                        patient_name=f"Dr. {doc_name}",
                        type="Email",
                        sender=from_email,
                        recipient=to_email,
                        status="Failed",
                        details=f"Failed to send email: {str(mail_err)}",
                        template_name="doctor_fee_cut_monthly_statement",
                        created_by="system",
                        hospital_code="SH001",
                        branch_code="SHB001"
                    )
                except Exception as log_err:
                    self.stdout.write(self.style.WARNING(f"CommunicationLog error: {log_err}"))

        self.stdout.write(self.style.SUCCESS(f"Finished. Total emails sent for {month_name}: {sent_count} (Skipped: {skipped_count})"))

    def handle(self, *args, **options):
        req_month = options.get('month')
        req_year = options.get('year')
        force = options.get('force', False)

        if options.get('now') or not options.get('daemon'):
            self.stdout.write(self.style.SUCCESS('Triggering Doctor Fee Cut emails once (run-once mode)...'))
            try:
                self.send_report(req_month=req_month, req_year=req_year, force=force)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error sending emails: {e}'))
            return

        self.stdout.write(self.style.SUCCESS('Starting Doctor Fee Cut Monthly Email Daemon (IST)...'))
        ist = pytz.timezone("Asia/Kolkata")

        while True:
            now_ist = datetime.datetime.now(ist)
            # Check if 1st day of month and hour is 8:00 AM IST
            if now_ist.day == 1 and now_ist.hour == 8:
                self.stdout.write(f'[{now_ist}] 1st of month 08:00 AM IST detected. Triggering monthly doctor emails...')
                try:
                    self.send_report(req_month=req_month, req_year=req_year, force=force)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error in daemon email send: {e}'))

                self.stdout.write('Sleeping for 1 hour...')
                time.sleep(3600)
            else:
                time.sleep(300)
