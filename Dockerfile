FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose the application port
EXPOSE 8080

# Set Flask environment variables
ENV FLASK_APP=app.main
ENV PYTHONUNBUFFERED=1

# Run the application via gunicorn so SIGTERM is handled gracefully.
# --workers 1 preserves the single-process assumption that the daemon
# threads and in-memory state in app/main.py rely on.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "4", \
     "--graceful-timeout", "10", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.main:app"]
