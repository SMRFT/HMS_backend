import time
import zoneinfo
from datetime import datetime
from django.core.management.base import BaseCommand
from hospital.Views.AccountsReport.cashcounter_rollover_service import (
    auto_close_active_shifts,
    auto_open_closed_shifts,
    trigger_rollover_check,
    get_current_ist_datetime,
)


class Command(BaseCommand):
    help = "Auto-close active cash counter shifts at 11:59 PM IST and auto-open new shifts at 12:00 AM IST"

    def add_arguments(self, parser):
        parser.add_argument(
            "--action",
            type=str,
            choices=["close", "open", "rollover", "check"],
            default="check",
            help="Action to run: 'close' (23:59), 'open' (00:00), 'rollover' (both for testing), or 'check' (time-based)",
        )
        parser.add_argument(
            "--daemon",
            action="store_true",
            help="Run continuously in background checking every 20 seconds",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=20,
            help="Check interval in seconds for daemon mode (default: 20s)",
        )

    def handle(self, *args, **options):
        action = options.get("action", "check")
        is_daemon = options.get("daemon", False)
        interval = options.get("interval", 20)

        now_ist = get_current_ist_datetime()
        self.stdout.write(f"Current IST time: {now_ist.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        if not is_daemon:
            if action == "close":
                self.stdout.write("[START] Closing all active cash counter shifts...")
                res = auto_close_active_shifts()
                self.stdout.write(self.style.SUCCESS(f"[SUCCESS] Auto-closed {res['count']} shift(s)."))
            elif action == "open":
                self.stdout.write("[START] Auto-opening shifts for auto-closed counters...")
                res = auto_open_closed_shifts()
                self.stdout.write(self.style.SUCCESS(f"[SUCCESS] Auto-opened {res['count']} shift(s)."))
            elif action == "rollover":
                self.stdout.write("[START] Running full test rollover (close active shifts -> open next day shifts)...")
                close_res = auto_close_active_shifts()
                self.stdout.write(self.style.SUCCESS(f"[CLOSED] {close_res['count']} shift(s)."))
                open_res = auto_open_closed_shifts()
                self.stdout.write(self.style.SUCCESS(f"[OPENED] {open_res['count']} shift(s)."))
            else:
                res = trigger_rollover_check()
                if res:
                    self.stdout.write(self.style.SUCCESS(f"[TRIGGERED] {res}"))
                else:
                    self.stdout.write("[NOOP] Neither 23:59 nor 00:00 IST right now.")
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"[DAEMON] Starting Cash Counter Auto-Rollover daemon (interval: {interval}s)..."
            )
        )
        while True:
            try:
                res = trigger_rollover_check()
                if res:
                    self.stdout.write(self.style.SUCCESS(f"[{get_current_ist_datetime()}] Triggered: {res}"))
                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Stopping Cash Counter Auto-Rollover daemon."))
                break
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error in daemon: {e}"))
                time.sleep(interval)

