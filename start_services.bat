@echo off
echo Starting HMS Services...

echo Starting Django Server on port 2609...
start "Django Server" cmd /k "venv\Scripts\python manage.py runserver 0.0.0.0:2609"

echo Starting Automation Worker (Daemon)...
start "Automation Worker" cmd /k "venv\Scripts\python manage.py send_pending_payments_report --daemon"

echo Send licence expiry emails (Daemon)...
start "Automation Worker" cmd /k "venv\Scripts\python manage.py send_licence_expiry_emails --daemon --interval 86400"

echo Send doctor fee cut monthly emails (Daemon)...
start "Automation Worker" cmd /k "venv\Scripts\python manage.py send_doctor_fee_cut_monthly_emails --daemon"

echo Starting Vaccination Reminders Worker (Daemon)...
start "Vaccination Reminders Worker" cmd /k "venv\Scripts\python manage.py send_vaccination_reminders --daemon"

echo Starting MHC Reminders Worker (Daemon)...
start "MHC Reminders Worker" cmd /k "venv\Scripts\python manage.py send_mhc_reminders --daemon"

echo Starting Discharge Visit Reminders Worker (Daemon)...
start "Discharge Visit Reminders Worker" cmd /k "venv\Scripts\python manage.py send_discharge_visit_reminders --daemon"

echo Services started. You can close this window.
pause

