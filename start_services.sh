#!/bin/bash

# This script is for Linux servers

cleanup() {
    echo "Stopping services..."
    kill $(jobs -p) 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM

echo "Starting Django Server on port 2609..."
# Using nohup to keep it running in the background
export SECURITY_DISABLED=false && python3 manage.py runserver 0.0.0.0:2609

echo "Starting Automation Worker (Daemon)..."
python3 manage.py send_pending_payments_report --daemon > worker.log 2>&1 &

python3 manage.py send_licence_expiry_emails --daemon --interval 86400 > licence_worker.log 2>&1 &

python3 manage.py send_doctor_fee_cut_monthly_emails --daemon > doctor_fee_cut_worker.log 2>&1 &

echo "Services started with nohup. Logs: server.log, worker.log, doctor_fee_cut_worker.log"

