FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/spice_proxy.py ./src/
COPY src/setup_totp.py ./src/
COPY src/admin.py ./src/

# Expose HTTP port and ephemeral port range
EXPOSE 80 40000-41000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${PROXY_HTTP_PORT:-80}/health').read()" || exit 1

# Run the application (single entry point)
CMD ["python3", "src/spice_proxy.py"]
