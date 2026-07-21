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
nohup bash -c 'export SECURITY_DISABLED=false && python3 manage.py runserver 0.0.0.0:2609' &

echo "Starting Automation Worker (Daemon)..."
nohup python3 manage.py send_pending_payments_report --daemon > worker.log 2>&1 &

echo "Services started with nohup. Logs: server.log, worker.log"
