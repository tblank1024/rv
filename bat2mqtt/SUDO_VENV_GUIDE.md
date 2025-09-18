# How to Use Sudo with Virtual Environment and Correct Directory

The problem: `sudo` resets the working directory and environment variables, causing:
1. Loss of virtual environment activation
2. Python switches from venv to system Python
3. Working directory may change

## Three Solutions:

### 1. Full bash -c approach (most reliable):
```bash
sudo bash -c "cd /home/tblank/code/tblank1024/rv/bat2mqtt && source venv/bin/activate && DEBUG_LEVEL=1 python bat2mqtt_direct.py"
```

### 2. Using the wrapper script:
```bash
sudo ./run_with_sudo.sh bash -c "DEBUG_LEVEL=1 python bat2mqtt_direct.py"
```

### 3. Source the helper function:
```bash
source sudo_venv_helper.sh
sudo_with_venv "DEBUG_LEVEL=1 python bat2mqtt_direct.py"
```

## Why the environment matters:
- Virtual environment has specific package versions (pygatt, paho-mqtt, etc.)
- System Python may not have these packages installed
- Directory context ensures scripts can find local files

## Testing command:
```bash
# This shows the problem:
sudo python --version  # Uses system Python

# This is correct:
sudo bash -c "cd /home/tblank/code/tblank1024/rv/bat2mqtt && source venv/bin/activate && python --version"
```
