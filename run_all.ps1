Write-Host "------------------------------------" -ForegroundColor Cyan
Write-Host "     Starting HMS Services          " -ForegroundColor Cyan
Write-Host "------------------------------------" -ForegroundColor Cyan

# Start Django Server in a new window using venv
Write-Host "Starting Django Server on port 2609..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", ".\venv\Scripts\python.exe manage.py runserver 0.0.0.0:2609"

# Start Automation Worker in daemon mode in a new window using venv
Write-Host "Starting Automation Worker (Daemon)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", ".\venv\Scripts\python.exe manage.py send_pending_payments_report --daemon"

Write-Host "Done! Services are running in separate windows." -ForegroundColor Green
Write-Host "You can close this main window."
pause

