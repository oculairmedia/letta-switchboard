FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements-standalone.txt .
RUN pip install --no-cache-dir -r requirements-standalone.txt

# Copy application code
COPY standalone_app.py .
COPY models.py .
COPY scheduler.py .
COPY letta_executor.py .
COPY crypto_utils.py .
COPY dashboard.html .

# Create data directory
RUN mkdir -p /data

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "standalone_app:app", "--host", "0.0.0.0", "--port", "8000"]
