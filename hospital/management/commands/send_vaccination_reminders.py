from django.core.management.base import BaseCommand
from django.utils import timezone
import datetime
import time
import traceback
from hospital.Views.vaccination import process_pending_vaccination_reminders


class Command(BaseCommand):
    help = "Auto-sends pending vaccination reminder WhatsApp messages 1 day before vaccination_date (10 AM daily daemon or single run)."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Target vaccination date (YYYY-MM-DD). Default: tomorrow')
        parser.add_argument('--daemon', action='store_true', help='Run in daemon mode checking daily at 10:00 AM')
        parser.add_argument('--now', action='store_true', help='Run reminder processor immediately and exit')
        parser.add_argument('--force', action='store_true', help='Bypass duplicate check and force send reminders')

    def handle(self, *args, **options):
        force = options.get('force', False)
        target_date = options.get('date')

        if options.get('now') or not options.get('daemon'):
            self.stdout.write(self.style.SUCCESS("[START] Processing pending vaccination reminders..."))
            results = process_pending_vaccination_reminders(target_date=target_date, force=force)
            self.stdout.write(self.style.SUCCESS(
                f"[COMPLETED] Target Date: {results.get('target_date')} | Total Checked: {results.get('total_patients_checked')} | "
                f"Sent: {results.get('reminders_sent')} | Skipped: {results.get('reminders_skipped')} | Failed: {results.get('failed_sends')}"
            ))
            return

        self.stdout.write(self.style.SUCCESS("[DAEMON MODE] Starting vaccination reminder scheduler (checks daily at 10:00 AM)..."))

        last_run_date = None

        while True:
            try:
                now = datetime.datetime.now()
                today = now.date()

                # Trigger at or after 10:00 AM once per day
                if now.hour >= 10 and last_run_date != today:
                    self.stdout.write(self.style.SUCCESS(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Triggering 10:00 AM vaccination reminders..."))
                    results = process_pending_vaccination_reminders(force=force)
                    last_run_date = today
                    self.stdout.write(self.style.SUCCESS(
                        f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Done. Sent: {results.get('reminders_sent')}, "
                        f"Skipped: {results.get('reminders_skipped')}, Failed: {results.get('failed_sends')}"
                    ))

                time.sleep(60)

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Stopping vaccination reminder daemon."))
                break
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Daemon Exception: {str(e)}\n{traceback.format_exc()}"))
                time.sleep(60)
