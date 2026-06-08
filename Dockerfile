# path: Dockerfile

# Use the official Python 3.11 slim image as base
# 'slim' means it's a smaller image — faster to build and push
FROM python:3.11-slim

# Set working directory inside the container
WORKDIR /app

# Copy requirements first — Docker caches this layer
# If requirements.txt hasn't changed, pip install is skipped on rebuild
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

RUN python -c "import cmdstanpy; cmdstanpy.install_cmdstan()"
# Copy the rest of the application code
COPY . .

# Expose port 8000
EXPOSE 8000

# Default command — can be overridden in docker-compose.yml
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]