from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

from ...Views.dbcollection import company_secretary_collection, profile_collection

# (days_before_expiry, flag_field, label_field)
THRESHOLDS = [
    (90, "is_90days", "Intimation_90days_about_expiry"),
    (60, "is_60days", "Intimation_60days_about_expiry"),
    (30, "is_30days", "Intimation_30days_about_expiry"),
    (7, "is_7days", "Intimation_7days_about_expiry"),
    (1, "is_1day", "Intimation_1day_about_expiry"),
]


def get_employee_email(employee_id):
    if not employee_id:
        return None
    profile = profile_collection.find_one({"employeeId": employee_id})
    return profile.get("email") if profile else None


def build_email_body(record, label_text, days_before):
    return (
        f"Dear Team,\n\n"
        f"This is a reminder that the following licence is due to expire "
        f"in {days_before} day(s) ({label_text}).\n\n"
        f"Licence Name: {record.get('licence_name')}\n"
        f"Licence/Case/Ref Number: {record.get('license_number')}\n"
        f"Valid From: {record.get('valid_from')}\n"
        f"Expiry Date: {record.get('expiry_date')}\n\n"
        f"Please take the necessary action before the expiry date.\n\n"
        f"Regards,\n"
        f"Shanmuga Hospital Limited"
    )


def run_licence_expiry_check():
    today = timezone.now().date()

    sent = []
    skipped = []

    for record in company_secretary_collection.find({}):
        expiry_date = record.get("expiry_date")
        if not expiry_date:
            continue

        expiry_date_only = (
            expiry_date.date() if isinstance(expiry_date, datetime) else expiry_date
        )
        diff_days = (expiry_date_only - today).days

        if diff_days < 0:
            continue  # already expired, nothing to notify

        updates = {}

        for days_before, flag_field, label_field in THRESHOLDS:
            already_sent = bool(record.get(flag_field, False))
            if already_sent:
                continue
            if diff_days > days_before:
                continue  # not due for this threshold yet

            incharge_email = get_employee_email(record.get("incharge"))
            respective_person_email = get_employee_email(record.get("respective_person"))

            if not incharge_email:
                skipped.append({
                    "licence_name": record.get("licence_name"),
                    "threshold": days_before,
                    "reason": f"No email found for incharge id {record.get('incharge')}",
                })
                continue

            label_text = record.get(label_field) or f"{days_before} Day(s) Before the Due Date"
            cc_list = [respective_person_email] if respective_person_email else []

            try:
                email = EmailMessage(
                    subject=f"Licence Expiry Reminder ({days_before} days): {record.get('licence_name')}",
                    body=build_email_body(record, label_text, days_before),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[incharge_email],
                    cc=cc_list,
                )
                email.send(fail_silently=False)

                updates[flag_field] = True

                sent.append({
                    "licence_name": record.get("licence_name"),
                    "threshold": days_before,
                    "to": incharge_email,
                    "cc": cc_list,
                })
            except Exception as e:
                skipped.append({
                    "licence_name": record.get("licence_name"),
                    "threshold": days_before,
                    "reason": str(e),
                })

        if updates:
            updates["lastmodified_date"] = timezone.now()
            company_secretary_collection.update_one(
                {"_id": record["_id"]},
                {"$set": updates},
            )

    return {
        "success": True,
        "sent_count": len(sent),
        "sent": sent,
        "skipped": skipped,
    }


class Command(BaseCommand):
    help = "Send licence expiry reminder emails at 90/60/30/7/1 day thresholds (incharge + cc respective person)"

    def handle(self, *args, **options):
        result = run_licence_expiry_check()
        self.stdout.write(self.style.SUCCESS(
            f"Licence expiry check complete. Sent: {result['sent_count']}, "
            f"Skipped: {len(result['skipped'])}"
        ))
        for s in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"Skipped: {s}"))