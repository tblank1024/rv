# Kasa Power Strip HS300 Controller

Modern Python interface for controlling the Kasa Smart Power Strip HS300 with 6 individually controllable outlets. Uses the official python-kasa library with support for KLAP encryption and modern authentication methods.

## Prerequisites

**IMPORTANT**: You must enable "Third Party Compatibility" in your Kasa app device settings. This allows local network control without requiring TP-Link account authentication each time.

## Files

- `kasa_ctrl.py` - Modern controller module using python-kasa library
- `requirements.txt` - Required dependencies
- `README.md` - This documentation

## Installation

```bash
pip install -r requirements.txt
```

## Features

### KasaPowerStrip Class
- **Individual outlet control** (turn on/off/toggle by index 0-5)
- **Real-time power monitoring** per outlet (watts, voltage, current)
- **Energy consumption tracking** (daily, monthly, total)
- **Comprehensive power summaries** for entire strip
- **Test mode** for sequential outlet testing
- **Power usage monitoring** over time with statistics
- **Bulk operations** (turn all outlets on/off)
- **No credentials required** when third party compatibility is enabled

## Quick Start

### Command Line Usage

```bash
# Demo mode - show system info, outlet status, and power data
python kasa_ctrl.py

# Test mode - turn on each outlet for 3 seconds sequentially
python kasa_ctrl.py test 3

# Get detailed power data for outlet 0
python kasa_ctrl.py power 0

# Get comprehensive power summary
python kasa_ctrl.py summary

# Monitor outlet 0 for 60 seconds, sampling every 5 seconds
python kasa_ctrl.py monitor 0 60 5

# Show help
python kasa_ctrl.py help
```

### Python API Usage

```python
from kasa_ctrl import KasaPowerStrip

# Initialize (replace with your power strip's IP)
power_strip = KasaPowerStrip("10.0.0.188")
power_strip.connect()

# Control individual outlets
power_strip.turn_on_outlet(0)     # Turn on outlet 0
power_strip.turn_off_outlet(1)    # Turn off outlet 1
power_strip.toggle_outlet(2)      # Toggle outlet 2

# Get power data
power_data = power_strip.get_detailed_power_data(0)
print(f"Outlet 0: {power_data['current_power_w']}W")

# Get all outlet statuses
statuses = power_strip.get_all_outlet_status()
for status in statuses:
    print(f"Outlet {status['outlet_id']}: {status['alias']} - {'ON' if status['is_on'] else 'OFF'}")

# Monitor power usage over time
readings = power_strip.monitor_power_usage(0, duration_seconds=30, interval_seconds=2)

power_strip.disconnect()
```

## Usage

### Basic Usage of KasaPowerStrip

```python
from kasa_ctrl import KasaPowerStrip, KasaProtocolError

# Initialize the power strip controller
power_strip = KasaPowerStrip("192.168.1.100")  # Replace with your device's IP

try:
    # Get system information
    system_info = power_strip.get_system_info()
    print(f"Device: {system_info}")
    
    # Turn on outlet 0
    power_strip.turn_on_outlet(0)
    
    # Turn off outlet 1
    power_strip.turn_off_outlet(1)
    
    # Toggle outlet 2
    power_strip.toggle_outlet(2)
    
    # Get status of outlet 3
    status = power_strip.get_outlet_status(3)
    print(f"Outlet 3 status: {status}")
    
    # Get all outlet statuses
    all_status = power_strip.get_all_outlet_status()
    for i, outlet in enumerate(all_status):
        print(f"Outlet {i}: {outlet['alias']} - {'ON' if outlet.get('state') else 'OFF'}")
    
    # Get power consumption for outlet 0
    power_data = power_strip.get_power_consumption(0)
    print(f"Power consumption: {power_data}")
    
    # Turn on all outlets
    results = power_strip.turn_on_all_outlets()
    for result in results:
        if result['success']:
            print(f"Outlet {result['outlet_id']}: Success")
        else:
            print(f"Outlet {result['outlet_id']}: Failed - {result['error']}")

except KasaProtocolError as e:
    print(f"Communication error: {e}")
except ValueError as e:
    print(f"Invalid parameter: {e}")
```

## Running Tests

### Simple Test Run
```bash
python run_tests.py
```

### Verbose Test Run
```bash
python run_tests.py --verbose
```

### Test Run with Coverage Report
```bash
python run_tests.py --coverage
```

### Install Dependencies and Run Tests
```bash
python run_tests.py --install --verbose
```

### Run Specific Test
```bash
python run_tests.py --test TestKasaPowerStrip::test_turn_on_outlet_valid_id
```

### Using pytest directly
```bash
# Install dependencies first
pip install -r requirements-test.txt

# Run all tests
pytest test_kasa_ctrl.py -v

# Run with coverage
pytest test_kasa_ctrl.py --cov=kasa_ctrl --cov-report=html

# Run specific test class
pytest test_kasa_ctrl.py::TestKasaPowerStrip -v

# Run specific test method
pytest test_kasa_ctrl.py::TestKasaPowerStrip::test_turn_on_outlet_valid_id -v
```

## Test Structure

### TestKasaPowerStrip
- **Initialization Tests**: Verify proper object creation
- **Encryption/Decryption Tests**: Test the XOR encryption protocol
- **Communication Tests**: Test socket communication with mocks
- **Outlet Control Tests**: Test individual outlet operations
- **Bulk Operation Tests**: Test operations on all outlets
- **Error Handling Tests**: Test invalid inputs and communication errors
- **Power Consumption Tests**: Test power monitoring functionality

### TestKasaProtocolError
- Tests for the custom exception class

### TestIntegration
- End-to-end workflow tests simulating real usage scenarios

## Error Handling

The module includes robust error handling:

- `KasaProtocolError`: Raised for communication issues with the device
- `ValueError`: Raised for invalid outlet IDs or parameters
- Socket exceptions are caught and converted to `KasaProtocolError`

## Test Coverage

The test suite covers:
- ✅ All public methods and properties
- ✅ Error conditions and edge cases
- ✅ Network communication scenarios
- ✅ Data encryption/decryption
- ✅ Invalid input validation
- ✅ Integration workflows

## Notes

- The controller uses Kasa's proprietary XOR encryption protocol
- Outlet IDs range from 0 to 5 (6 outlets total)
- The module is designed to work with the Kasa HS300 but may be compatible with similar models
- Tests use mocks to avoid requiring actual hardware during testing
- All network timeouts and error conditions are properly handled

## Development

To add new features:

1. Implement the feature in `kasa_ctrl.py`
2. Add corresponding tests in `test_kasa_ctrl.py`
3. Run the test suite to ensure everything works
4. Update this README if needed

## Troubleshooting

If tests fail:

1. Ensure all dependencies are installed: `pip install -r requirements-test.txt`
2. Check that you're in the correct directory
3. Run tests with verbose output: `python run_tests.py -v`
4. Check for any network connectivity issues if using real hardware

For actual device communication issues:
1. Verify the device IP address is correct
2. Ensure the device is on the same network
3. Check that the device is powered on and responding
4. Verify firewall settings allow communication on port 9999