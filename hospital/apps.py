import os
import threading
import time
from django.apps import AppConfig


class HospitalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hospital'

    def ready(self):
        # Run background thread in main worker process (guard against double execution in runserver reload)
        if os.environ.get('RUN_MAIN') == 'true' or not os.environ.get('DJANGO_SETTINGS_MODULE'):
            def _estimate_cleaner_worker():
                time.sleep(10)  # Wait for Django server startup
                while True:
                    try:
                        from hospital.Views.pharmacy import process_expired_estimate_bills
                        process_expired_estimate_bills()
                    except Exception as err:
                        pass
                    time.sleep(300)  # Check every 5 minutes

            t = threading.Thread(target=_estimate_cleaner_worker, daemon=True, name="EstimateAutoDeleteWorker")
            t.start()

            def _cashcounter_rollover_worker():
                time.sleep(15)  # Wait for Django server startup
                while True:
                    try:
                        from hospital.Views.AccountsReport.cashcounter_rollover_service import trigger_rollover_check
                        trigger_rollover_check()
                    except Exception:
                        pass
                    time.sleep(25)  # Check every 25 seconds for exact 23:59 / 00:00 IST

            t_rollover = threading.Thread(target=_cashcounter_rollover_worker, daemon=True, name="CashCounterAutoRolloverWorker")
            t_rollover.start()
