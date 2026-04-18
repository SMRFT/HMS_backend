@echo off

echo Starting Estimate Auto Delete...

cd /d "D:\HMS (1)\HMS_backend"

call venv\Scripts\activate

python manage.py estimate_auto_delete >> "D:\HMS (1)\HMS_backend\log.txt" 2>&1

echo Completed
pause