@echo off
cd /d "%~dp0"
venv\Scripts\python manage.py send_pending_payments_report --now
