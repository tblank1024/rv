# The Kasa Smart Plug Power Strip HS300 provides 6 individually controllable outlets.
# This module provides control of the power strip and its outlets.
# Note: This code has not been tested with the HS300, but is based on the HS110 code and
# the HS300 protocol documentation. 
# Ideally, the power for each outlet should also be reported like the phone app does.

import json
import socket
import struct
from typing import Dict, List, Optional, Union


class KasaProtocolError(Exception):
    """Exception raised for Kasa protocol communication errors."""
    pass


class KasaPowerStrip:
    """Controller for Kasa HS300 Smart Power Strip with 6 individually controllable outlets."""
    
    def __init__(self, host: str, port: int = 9999, timeout: int = 5):
        """
        Initialize the Kasa Power Strip controller.
        
        Args:
            host: IP address of the power strip
            port: Port number (default: 9999)
            timeout: Connection timeout in seconds (default: 5)
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.num_outlets = 6
    
    def _encrypt(self, data: str) -> bytes:
        """Encrypt data using Kasa's XOR encryption."""
        key = 171
        result = struct.pack('>I', len(data))
        for char in data:
            key = key ^ ord(char)
            result += struct.pack('B', key)
        return result
    
    def _decrypt(self, data: bytes) -> str:
        """Decrypt data using Kasa's XOR decryption."""
        key = 171
        result = ""
        for byte in data[4:]:  # Skip the first 4 bytes (length)
            key = key ^ byte
            result += chr(key)
        return result
    
    def _send_command(self, command: Dict) -> Dict:
        """
        Send a command to the power strip and return the response.
        
        Args:
            command: Command dictionary to send
            
        Returns:
            Response dictionary from the device
            
        Raises:
            KasaProtocolError: If communication fails
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))
                
                # Send encrypted command
                json_str = json.dumps(command)
                encrypted = self._encrypt(json_str)
                sock.send(encrypted)
                
                # Receive response
                length_bytes = sock.recv(4)
                if len(length_bytes) < 4:
                    raise KasaProtocolError("Failed to receive response length")
                
                response_length = struct.unpack('>I', length_bytes)[0]
                response_data = length_bytes + sock.recv(response_length)
                
                # Decrypt and parse response
                decrypted = self._decrypt(response_data)
                return json.loads(decrypted)
                
        except (socket.error, json.JSONDecodeError, struct.error) as e:
            raise KasaProtocolError(f"Communication error: {e}")
    
    def get_system_info(self) -> Dict:
        """Get system information from the power strip."""
        command = {"system": {"get_sysinfo": {}}}
        return self._send_command(command)
    
    def turn_on_outlet(self, outlet_id: int) -> Dict:
        """
        Turn on a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Response from the device
        """
        if not 0 <= outlet_id < self.num_outlets:
            raise ValueError(f"Outlet ID must be between 0 and {self.num_outlets - 1}")
        
        command = {
            "context": {"child_ids": [f"plug_{outlet_id:02d}"]},
            "system": {"set_relay_state": {"state": 1}}
        }
        return self._send_command(command)
    
    def turn_off_outlet(self, outlet_id: int) -> Dict:
        """
        Turn off a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Response from the device
        """
        if not 0 <= outlet_id < self.num_outlets:
            raise ValueError(f"Outlet ID must be between 0 and {self.num_outlets - 1}")
        
        command = {
            "context": {"child_ids": [f"plug_{outlet_id:02d}"]},
            "system": {"set_relay_state": {"state": 0}}
        }
        return self._send_command(command)
    
    def toggle_outlet(self, outlet_id: int) -> Dict:
        """
        Toggle the state of a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Response from the device
        """
        status = self.get_outlet_status(outlet_id)
        current_state = status.get("relay_state", 0)
        
        if current_state:
            return self.turn_off_outlet(outlet_id)
        else:
            return self.turn_on_outlet(outlet_id)
    
    def get_outlet_status(self, outlet_id: int) -> Dict:
        """
        Get the status of a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Outlet status information
        """
        if not 0 <= outlet_id < self.num_outlets:
            raise ValueError(f"Outlet ID must be between 0 and {self.num_outlets - 1}")
        
        system_info = self.get_system_info()
        children = system_info.get("system", {}).get("get_sysinfo", {}).get("children", [])
        
        for child in children:
            if child.get("id") == f"plug_{outlet_id:02d}":
                return child
        
        raise KasaProtocolError(f"Outlet {outlet_id} not found in system info")
    
    def get_all_outlet_status(self) -> List[Dict]:
        """Get the status of all outlets."""
        system_info = self.get_system_info()
        return system_info.get("system", {}).get("get_sysinfo", {}).get("children", [])
    
    def turn_on_all_outlets(self) -> List[Dict]:
        """Turn on all outlets."""
        results = []
        for outlet_id in range(self.num_outlets):
            try:
                result = self.turn_on_outlet(outlet_id)
                results.append({"outlet_id": outlet_id, "result": result, "success": True})
            except Exception as e:
                results.append({"outlet_id": outlet_id, "error": str(e), "success": False})
        return results
    
    def turn_off_all_outlets(self) -> List[Dict]:
        """Turn off all outlets."""
        results = []
        for outlet_id in range(self.num_outlets):
            try:
                result = self.turn_off_outlet(outlet_id)
                results.append({"outlet_id": outlet_id, "result": result, "success": True})
            except Exception as e:
                results.append({"outlet_id": outlet_id, "error": str(e), "success": False})
        return results
    
    def get_power_consumption(self, outlet_id: int) -> Dict:
        """
        Get power consumption data for a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Power consumption data
        """
        if not 0 <= outlet_id < self.num_outlets:
            raise ValueError(f"Outlet ID must be between 0 and {self.num_outlets - 1}")
        
        command = {
            "context": {"child_ids": [f"plug_{outlet_id:02d}"]},
            "emeter": {"get_realtime": {}}
        }
        return self._send_command(command)


def main():
    """Example usage of the KasaPowerStrip class."""
    # Example usage - replace with your power strip's IP address
    power_strip = KasaPowerStrip("192.168.1.100")
    
    try:
        # Get system information
        print("System Info:")
        system_info = power_strip.get_system_info()
        print(json.dumps(system_info, indent=2))
        
        # Get status of all outlets
        print("\nAll Outlet Status:")
        all_status = power_strip.get_all_outlet_status()
        for i, status in enumerate(all_status):
            print(f"Outlet {i}: {status.get('alias', 'Unknown')} - {'ON' if status.get('state') else 'OFF'}")
        
        # Turn on outlet 0
        print("\nTurning on outlet 0...")
        power_strip.turn_on_outlet(0)
        
        # Turn off outlet 0
        print("Turning off outlet 0...")
        power_strip.turn_off_outlet(0)
        
    except KasaProtocolError as e:
        print(f"Protocol error: {e}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()