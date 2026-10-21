# Dockerfile — Production-ready non-root container for Janus (ElderSync)
FROM python:3.12-slim

# Prevent Python from writing bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JANUS_HOST=0.0.0.0 \
    JANUS_PORT=8000 \
    JANUS_DB_PATH=/app/data/janus.db

# Install curl for container healthchecks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user and application directory
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

WORKDIR /app

# Copy dependency specifications first to leverage Docker layer caching
COPY pyproject.toml requirements.txt /app/

# Install dependencies in system environment before switching user
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code and default data directory
COPY src/ /app/src/
COPY data/ /app/data/

# Install package in editable/console-script mode
RUN pip install --no-cache-dir -e .

# Create persistent data directory and assign ownership to appuser
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose Streamable HTTP port
EXPOSE 8000

# Health check probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch Janus FastMCP server
CMD ["python", "-m", "janus.server"]
