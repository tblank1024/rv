FROM python:3.11-slim-bookworm

# Install system dependencies for Bluetooth (simplified - only what we need)
RUN apt-get update && apt-get install -y \
    bluez \
    bluez-tools \
    bluetooth \
    rfkill \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/bat2mqtt
WORKDIR /app/bat2mqtt

# Copy the simplified script and minimal dependencies
COPY bat2mqtt.py .
COPY requirements.txt .

# Install Python dependencies (simplified - only paho-mqtt needed)
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install paho-mqtt

# Make the script executable so it can be run directly
RUN chmod +x bat2mqtt.py

# Set environment variables for consistent behavior
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# Run the simplified implementation - no threads, no subprocesses
CMD ["python3", "bat2mqtt.py"]

# To build: docker build -f Dockerfile.pygatt -t bat2mqtt:pygatt .
