# Raspberry Pi 5 Alarm System Setup

This alarm system has been updated to work with Raspberry Pi 5 using the modern libgpiod GPIO library.

## Hardware Requirements
- Raspberry Pi 5
- GPIO components as defined in alarm.py pin definitions

## Software Setup

### 1. Run Setup Script
```bash
# Install system packages
./setup_rpi5.sh

# Install Python packages
pip3 install -r requirements.txt
```

### 2. GPIO Library Priority
The code uses this priority order for GPIO libraries:
1. **lgpio** (primary for RPi 5) - Modern library with excellent RPi 5 support
2. **RPi.GPIO** (fallback) - Legacy library for compatibility

#### Automatic Fallback Mechanism
The system automatically detects and uses the best available GPIO library using nested try-except blocks:

```python
try:
    # Try lgpio first (preferred for RPi 5)
    from gpiozero.pins.lgpio import LGPIOFactory
    Device.pin_factory = LGPIOFactory()
    print("Using LGPIO pin factory for Raspberry Pi 5")
except ImportError:
    try:
        # Fall back to RPi.GPIO if lgpio unavailable
        from gpiozero.pins.rpigpio import RPiGPIOFactory
        Device.pin_factory = RPiGPIOFactory()
        print("Using RPi.GPIO pin factory (legacy)")
    except ImportError:
        print("No compatible GPIO library found")
```

This approach provides:
- **Automatic detection** - No manual configuration needed
- **Graceful degradation** - Works on different RPi models
- **Runtime decision** - Based on what's actually installed
- **User feedback** - Shows which library is being used

### 3. Test GPIO Functionality
Before running the alarm system, test your GPIO setup:
```bash
python3 test_gpio.py
```

### 4. Run the Alarm System

#### Option A: Direct Python execution
```bash
python3 alarm.py
```

#### Option B: Docker deployment (Production)
```bash
# Build the Docker image
docker build -t alarm .

# Run as a service (recommended for production)
sudo docker run -d --restart=unless-stopped --privileged \
  --device /dev/gpiochip0 --device /dev/gpiochip10 \
  --device /dev/gpiochip11 --device /dev/gpiochip12 \
  --device /dev/gpiochip13 -v /dev:/dev \
  --name rv-alarm alarm
```

## Pin Definitions (BCM GPIO numbering)

### Output Pins
- GPIO22 (Pin 15) - Buzzer
- GPIO27 (Pin 13) - Horn
- GPIO12 (Pin 32) - Red LED
- GPIO19 (Pin 35) - Blue LED  
- GPIO26 (Pin 37) - Bike Out 1
- GPIO21 (Pin 40) - Bike Out 2

### Input Pins
- GPIO5 (Pin 29) - PIR Sensor
- GPIO6 (Pin 31) - Red Button
- GPIO13 (Pin 33) - Blue Button
- GPIO16 (Pin 36) - Bike In 1
- GPIO20 (Pin 38) - Bike In 2

## Key Changes for RPi 5

1. **GPIO Library**: Updated to use lgpio as the primary GPIO interface with automatic fallback
2. **Pin Factory**: Automatic detection and configuration using nested try-except blocks
3. **Error Handling**: Improved error handling for GPIO initialization with graceful degradation
4. **Compatibility**: Maintains backward compatibility with RPi.GPIO for older systems

## Troubleshooting

### GPIO Access Issues
If you get permission errors, ensure your user is in the gpio group:
```bash
sudo usermod -a -G gpio $USER
```
Then log out and back in.

### Library Issues
The system automatically handles GPIO library fallback, but if you see "No compatible GPIO library found":

1. **Install missing packages:**
   ```bash
   # Re-run the setup script
   ./setup_rpi5.sh
   pip3 install -r requirements.txt
   ```

2. **Manual library installation:**
   ```bash
   # For lgpio (preferred)
   pip3 install lgpio
   
   # For RPi.GPIO (fallback)
   pip3 install RPi.GPIO
   ```

3. **Check startup messages** to see which library is being used:
   - `"Using LGPIO pin factory for Raspberry Pi 5"` - Optimal
   - `"Using RPi.GPIO pin factory (legacy)"` - Working fallback
   - `"No compatible GPIO library found"` - Installation issue


### Testing Individual Components
Use the test_gpio.py script to verify individual GPIO components are working correctly.
