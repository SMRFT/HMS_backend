from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from hospital.models import Internship, CommunicationLog
from bson import Decimal128
from decimal import Decimal
import json
import time
import pytz
from datetime import datetime
import os


def clean_smart_quotes(v):
    if v is None:
        return 0.0
    if isinstance(v, Decimal128):
        try:
            return float(v.to_decimal())
        except Exception:
            return 0.0
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = (
            v.replace("\u201c", "")
             .replace("\u201d", "")
             .replace("\u2018", "")
             .replace("\u2019", "")
             .replace('"',      "")
             .replace("'",      "")
             .strip()
        )
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0
    return 0.0

def get_payments_list(details):
    if not details:
        return []
    if isinstance(details, str):
        try:
            return json.loads(details)
        except Exception:
            return []
    return details

class Command(BaseCommand):
    help = "Daily email report of pending internship payments to najmayasu@gmail.com. Runs once by default, or continuously in --daemon mode."

    def add_arguments(self, parser):
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run in daemon mode checking for 10:00 AM IST daily',
        )
        parser.add_argument(
            '--now',
            action='store_true',
            help='Run the report once immediately and exit (alias for default)',
        )

    def send_report(self):
        interns = Internship.objects.filter(is_active__in=[True])
        pending_list = []
        
        for item in interns:
            payments = get_payments_list(item.payment_details)
            amount_paid = sum(clean_smart_quotes(p.get('amount', 0)) for p in payments)
            total_fee = clean_smart_quotes(item.total_fee)
            pending_amount = total_fee - amount_paid
            
            if pending_amount > 0:
                pending_list.append({
                    "id": item.intern_id,
                    "name": item.student_name,
                    "college": item.college,
                    "mobile": item.mobile_number or "N/A",
                    "total_fee": total_fee,
                    "amount_paid": amount_paid,
                    "pending_amount": pending_amount,
                    "end_date": item.end_date.strftime('%d/%m/%Y') if item.end_date else "N/A"
                })
        
        # Build HTML Table
        if pending_list:
            rows = ""
            for idx, p in enumerate(pending_list, 1):
                rows += f"""
                <tr style="background-color: { '#ffffff' if idx % 2 == 0 else '#f8fafc' };">
                    <td style="border: 1px solid #cbd5e1; padding: 10px; text-align: center; font-weight: bold;">{p['id']}</td>
                    <td style="border: 1px solid #cbd5e1; padding: 10px; font-weight: bold; color: #1e293b;">{p['name']}</td>
                    <td style="border: 1px solid #cbd5e1; padding: 10px;">{p['college']}</td>
                    <td style="border: 1px solid #cbd5e1; padding: 10px; text-align: center;">{p['mobile']}</td>
                    <td style="border: 1px solid #cbd5e1; padding: 10px; text-align: right; font-weight: 600;">₹{p['total_fee']:,.2f}</td>
                    <td style="border: 1px solid #cbd5e1; padding: 10px; text-align: right; font-weight: 600; color: #166534;">₹{p['amount_paid']:,.2f}</td>
                    <td style="border: 1px solid #cbd5e1; padding: 10px; text-align: right; font-weight: 600; color: #b91c1c;">₹{p['pending_amount']:,.2f}</td>
                    <td style="border: 1px solid #cbd5e1; padding: 10px; text-align: center; font-weight: 600; color: #4f46e5;">{p['end_date']}</td>
                </tr>
                """
            
            html_message = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        line-height: 1.6;
                        color: #334155;
                        margin: 0;
                        padding: 20px;
                        background-color: #f8fafc;
                    }}
                    .container {{
                        max-width: 900px;
                        margin: 0 auto;
                        background-color: #ffffff;
                        border-radius: 12px;
                        overflow: hidden;
                        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                        padding: 30px;
                        border-top: 5px solid #ef4444;
                    }}
                    .header {{
                        margin-bottom: 24px;
                        border-bottom: 2px solid #e2e8f0;
                        padding-bottom: 16px;
                    }}
                    .header h2 {{
                        color: #0f172a;
                        margin: 0;
                        font-size: 22px;
                    }}
                    .header p {{
                        color: #64748b;
                        margin: 4px 0 0 0;
                        font-size: 14px;
                    }}
                    table {{
                        width: 100%;
                        border-collapse: collapse;
                        font-size: 13px;
                        margin-top: 15px;
                    }}
                    th {{
                        background-color: #f1f5f9;
                        color: #0f172a;
                        font-weight: 600;
                        border: 1px solid #cbd5e1;
                        padding: 10px;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Internship - Pending Payment Alert</h2>
                        <p>The following list contains interns with outstanding fees as of today.</p>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Student Name</th>
                                <th>College</th>
                                <th>Mobile Number</th>
                                <th>Total Fee</th>
                                <th>Paid Amount</th>
                                <th>Outstanding</th>
                                <th>End Date</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                </div>
            </body>
            </html>
            """
        else:
            html_message = """
            <!DOCTYPE html>
            <html>
            <body style="font-family: sans-serif; padding: 20px; color: #334155;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border-top: 5px solid #10b981; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); border-radius: 8px;">
                    <h3 style="color: #0f172a;">Internship - Pending Payment Alert</h3>
                    <p style="color: #64748b;">There are no interns with outstanding payments as of today.</p>
                </div>
            </body>
            </html>
            """

        try:
            hr_email = os.getenv('HMS_HR_EMAIL', 'najmasmrft@gmail.com')
            hr_password = os.getenv('HMS_HR_EMAIL_PASSWORD', 'zpid kdqk tekw ixjk')
            from django.core.mail import get_connection
            connection = get_connection(
                host=os.getenv('EMAIL_HOST', 'smtp.gmail.com'),
                port=int(os.getenv('EMAIL_PORT', 587)),
                username=hr_email,
                password=hr_password,
                use_tls=os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes'),
            )

            email = EmailMessage(
                subject="Internship-Pending payment alert",
                body=html_message,
                from_email=hr_email,
                to=["avphr@smrft.org", "hr@smrft.org"],
                connection=connection,
            )
            email.content_subtype = "html"
            email.send()
            
            # Log success to CommunicationLog
            CommunicationLog.objects.create(
                patient_id="system_pending_payment",
                patient_name="System Admin",
                type="Email",
                recipient="avphr@smrft.org, hr@smrft.org",
                status="Success",
                details=f"Email sent successfully. Pending list count: {len(pending_list)}",
                template_name="intern_pending_payment",
                created_by="system",
                branch_code="system",
                hospital_code="system"
            )
            self.stdout.write(self.style.SUCCESS(f"Email sent successfully. Count: {len(pending_list)}"))
        except Exception as e:
            # Log failure to CommunicationLog
            CommunicationLog.objects.create(
                patient_id="system_pending_payment",
                patient_name="System Admin",
                type="Email",
                recipient="avphr@smrft.org, hr@smrft.org",
                status="Failed",
                details=str(e),
                template_name="intern_pending_payment",
                created_by="system",
                branch_code="system",
                hospital_code="system"
            )
            raise e

    def handle(self, *args, **options):
        if options.get('now') or not options.get('daemon'):
            self.stdout.write(self.style.SUCCESS('Triggering email report once (run-once mode)...'))
            try:
                self.send_report()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error sending email: {e}'))
            return

        self.stdout.write(self.style.SUCCESS('Starting Internship Daily Payment Report Daemon (IST)...'))
        
        ist = pytz.timezone("Asia/Kolkata")
        
        while True:
            # Get current time in IST
            now_ist = datetime.now(ist)
            
            # Check if it is 10:00 AM (10:xx:xx) in India
            if now_ist.hour == 10:
                self.stdout.write(f'[{now_ist}] 10:00 AM (IST) detected. Triggering email report...')
                try:
                    self.send_report()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error sending email: {e}'))
                
                # Sleep for an hour to avoid multiple triggers within the same 10:00 AM hour
                self.stdout.write('Sleeping for 1 hour...')
                time.sleep(3600)
            else:
                # Check every minute
                time.sleep(60)
