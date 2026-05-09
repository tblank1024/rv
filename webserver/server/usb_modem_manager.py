#!/usr/bin/env python3
"""
USB Modem Management for Docker Container
Handles cellular modem MTP conflicts, USB rescanning, and network interface detection
"""

import os
import time
import subprocess
import logging
from typing import List, Dict, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class USBModemManager:
    """Manages USB cellular modem setup and MTP conflict resolution."""
    
    def __init__(self):
        self.cellular_vendor_ids = ["12d1", "19d2", "1e0e"]  # Common cellular modem vendor IDs
        self.mtp_processes = ["gvfs-mtp-volume-monitor", "mtp-probe", "libmtp"]
        
    def kill_mtp_processes(self) -> bool:
        """Kill MTP-related processes that might interfere with modem detection."""
        logger.info("Stopping MTP processes that might interfere with cellular modem...")
        killed_any = False
        
        for process_name in self.mtp_processes:
            try:
                # Kill processes by name
                result = subprocess.run(
                    ["pkill", "-f", process_name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    logger.info(f"Killed MTP process: {process_name}")
                    killed_any = True
                else:
                    logger.debug(f"No {process_name} processes found")
                    
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout killing {process_name} processes")
            except Exception as e:
                logger.warning(f"Error killing {process_name}: {e}")
        
        # Try to stop systemd user services
        try:
            subprocess.run(
                ["systemctl", "--user", "stop", "gvfs-mtp-volume-monitor"],
                capture_output=True,
                timeout=5
            )
            logger.info("Stopped gvfs-mtp-volume-monitor user service")
            killed_any = True
        except Exception as e:
            logger.debug(f"Could not stop gvfs-mtp-volume-monitor service: {e}")
        
        if killed_any:
            time.sleep(2)  # Allow processes to fully terminate
            
        return killed_any
    
    def usb_rescan(self, usb_path: str = "1-1") -> bool:
        """Perform USB device rescan to force re-enumeration."""
        logger.info(f"Performing USB rescan for device path: {usb_path}")
        
        try:
            # Unbind the USB device
            unbind_path = f"/sys/bus/usb/drivers/usb/{usb_path}"
            if os.path.exists(unbind_path):
                with open("/sys/bus/usb/drivers/usb/unbind", "w") as f:
                    f.write(usb_path)
                logger.info(f"Unbound USB device: {usb_path}")
                time.sleep(1)
            
            # Rebind the USB device
            with open("/sys/bus/usb/drivers/usb/bind", "w") as f:
                f.write(usb_path)
            logger.info(f"Rebound USB device: {usb_path}")
            time.sleep(2)
            
            return True
            
        except PermissionError as e:
            logger.error(f"Permission denied for USB rescan: {e}")
            return False
        except FileNotFoundError as e:
            logger.warning(f"USB device path not found: {e}")
            return False
        except Exception as e:
            logger.error(f"USB rescan failed: {e}")
            return False
    
    def detect_cellular_modems(self) -> List[Dict]:
        """Detect cellular modems connected via USB."""
        modems = []
        
        try:
            # Use lsusb to detect cellular modems
            result = subprocess.run(
                ["lsusb"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    # Look for known cellular modem vendor IDs
                    for vendor_id in self.cellular_vendor_ids:
                        if vendor_id.lower() in line.lower():
                            parts = line.split()
                            if len(parts) >= 6:
                                bus = parts[1]
                                device = parts[3].rstrip(':')
                                modem_info = {
                                    'bus': bus,
                                    'device': device,
                                    'vendor_id': vendor_id,
                                    'description': ' '.join(parts[6:])
                                }
                                modems.append(modem_info)
                                logger.info(f"Found cellular modem: {modem_info}")
            
        except Exception as e:
            logger.error(f"Error detecting cellular modems: {e}")
        
        return modems
    
    def wait_for_network_interface(self, interface_patterns: List[str] = None, timeout: int = 30) -> Optional[str]:
        """Wait for cellular network interface to appear."""
        if interface_patterns is None:
            interface_patterns = ["wwan", "ppp", "usb", "eth2"]  # Added eth2 for your cellular modem
        
        logger.info(f"Waiting for network interface matching: {interface_patterns}")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Check for network interfaces
                with open("/proc/net/dev", "r") as f:
                    interfaces = f.read()
                
                for line in interfaces.split('\n'):
                    if ':' in line:
                        interface_name = line.split(':')[0].strip()
                        for pattern in interface_patterns:
                            if pattern in interface_name.lower():
                                logger.info(f"Found cellular network interface: {interface_name}")
                                return interface_name
                
                time.sleep(1)
                
            except Exception as e:
                logger.warning(f"Error checking network interfaces: {e}")
                time.sleep(1)
        
        logger.warning(f"Timeout waiting for network interface after {timeout} seconds")
        return None
    
    def check_modem_manager_status(self) -> bool:
        """Check if ModemManager is detecting the cellular modem."""
        try:
            # Check if mmcli is available and can list modems
            result = subprocess.run(
                ["mmcli", "-L"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if "modem" in output.lower() and "found" not in output.lower():
                    logger.info("ModemManager detected cellular modem")
                    return True
                else:
                    logger.info("ModemManager: No modems found")
                    return False
            else:
                logger.warning(f"ModemManager error: {result.stderr}")
                return False
                
        except FileNotFoundError:
            logger.info("ModemManager (mmcli) not available")
            return False
        except Exception as e:
            logger.warning(f"Error checking ModemManager: {e}")
            return False
    
    def prepare_cellular_modem(self, usb_path: str = "1-1") -> Tuple[bool, str]:
        """
        Complete cellular modem preparation sequence.
        Returns (success, message).
        """
        logger.info("Starting cellular modem preparation sequence...")
        
        # Step 1: Kill MTP processes
        mtp_killed = self.kill_mtp_processes()
        message_parts = []
        
        if mtp_killed:
            message_parts.append("MTP processes stopped")
        
        # Step 2: USB rescan
        rescan_success = self.usb_rescan(usb_path)
        if rescan_success:
            message_parts.append("USB rescan completed")
        else:
            message_parts.append("USB rescan failed")
        
        # Step 3: Detect modems
        modems = self.detect_cellular_modems()
        if modems:
            message_parts.append(f"Found {len(modems)} cellular modem(s)")
        else:
            message_parts.append("No cellular modems detected")
        
        # Step 4: Wait for network interface
        interface = self.wait_for_network_interface(timeout=15)
        if interface:
            message_parts.append(f"Network interface '{interface}' available")
        else:
            message_parts.append("No cellular network interface found")
        
        # Step 5: Check ModemManager
        mm_status = self.check_modem_manager_status()
        if mm_status:
            message_parts.append("ModemManager detected modem")
        else:
            message_parts.append("ModemManager status unknown")
        
        success = rescan_success and (modems or interface)
        message = ", ".join(message_parts)
        
        logger.info(f"Cellular modem preparation {'succeeded' if success else 'failed'}: {message}")
        return success, message
    
    def cleanup_mtp_handlers(self) -> bool:
        """Re-enable MTP handlers after cellular connection is established."""
        logger.info("Re-enabling MTP handlers...")
        
        try:
            # Try to restart the MTP volume monitor
            subprocess.run(
                ["systemctl", "--user", "start", "gvfs-mtp-volume-monitor"],
                capture_output=True,
                timeout=5
            )
            logger.info("Re-started gvfs-mtp-volume-monitor user service")
            return True
            
        except Exception as e:
            logger.debug(f"Could not restart gvfs-mtp-volume-monitor service: {e}")
            return False


# Singleton instance for use throughout the application
usb_modem_manager = USBModemManager()
