# Dockerfile for Quant Trading Agent
# Optimized for AWS EC2 (t3.micro/small)

FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install python deps
COPY pyproject.toml .
# Create a dummy README for hatchling
RUN touch README.md
RUN pip install --no-cache-dir .

# Copy source
COPY quant/ quant/
COPY scripts/ scripts/

# Runtime config
ENV PYTHONUNBUFFERED=1
ENV EXECUTION_MODE=paper

# Entrypoint runs the main orchestrator
CMD ["python", "-m", "quant.daemon"]
