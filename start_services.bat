@echo off
echo Starting HMS Services...

echo Starting Django Server on port 2609...
start "Django Server" cmd /k "venv\Scripts\python manage.py runserver 0.0.0.0:2609"

echo Starting Automation Worker (Daemon)...
start "Automation Worker" cmd /k "venv\Scripts\python manage.py send_pending_payments_report --daemon"

echo Services started. You can close this window.
pause
