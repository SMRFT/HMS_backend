# Use official Python runtime as base image
FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies required for OCR and PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy backend source code into app directory
COPY . /app/

# Expose port
EXPOSE 2609

# Start Django server
CMD ["python3", "manage.py", "runserver", "0.0.0.0:2609"]
