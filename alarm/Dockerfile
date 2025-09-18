# Updated for Raspberry Pi 5 with libgpiod support
# Build: docker build -t alarm .
# RUN  : sudo docker run -it --device /dev/gpiomem --device /dev/gpiochip0 alarm

FROM python:3.11-slim-bookworm

# Upgrade pip and install system dependencies
RUN python3 -m pip install --upgrade pip
RUN apt-get update && apt-get install -y \
    gcc \
    libgpiod-dev \
    python3-libgpiod \
    gpiod \
    && apt-get clean

# Set working directory
WORKDIR /app/alarm

# Copy application files
COPY . .

# Install Python dependencies
RUN python -m pip install -r requirements.txt

# Set default command
CMD ["python3", "alarm.py"]
