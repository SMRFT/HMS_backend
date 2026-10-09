from django.core.management.base import BaseCommand
import time
import datetime
from hospital.Views.pharmacy import process_expired_estimate_bills


class Command(BaseCommand):
    help = "Delete expired estimate bills (>24 hours from billing time), release blocked stock, and log deletion"

    def add_arguments(self, parser):
        parser.add_argument('--daemon', action='store_true', help='Run continuously in background checking every 5 minutes')
        parser.add_argument('--interval', type=int, default=300, help='Check interval in seconds for daemon mode (default: 300s / 5 mins)')

    def handle(self, *args, **options):
        is_daemon = options.get('daemon', False)
        interval = options.get('interval', 300)

        if not is_daemon:
            self.stdout.write("[START] Running 24-hour estimate auto-delete check...")
            deleted_count = process_expired_estimate_bills()
            self.stdout.write(
                self.style.SUCCESS(f"[COMPLETED] {deleted_count} expired estimate bill(s) deleted, stock restored, and logged.")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"[DAEMON MODE] Starting 24-hour Estimate Auto-Delete service (checks every {interval}s)...")
        )

        while True:
            try:
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                deleted = process_expired_estimate_bills()
                if deleted > 0:
                    self.stdout.write(
                        self.style.SUCCESS(f"[{now_str}] Deleted {deleted} expired estimate(s), restored stock, and created deletion logs.")
                    )
                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Stopping Estimate Auto-Delete daemon."))
                break
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error in estimate auto-delete daemon: {e}"))
                time.sleep(interval)