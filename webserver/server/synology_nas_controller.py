#!/usr/bin/env python3
"""
Synology NAS Controller for DS620slim
Provides functionality to wake up and shutdown a Synology NAS using Wake-on-LAN and API calls.
"""

import socket
import struct
import time
import requests
import logging
import os
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SynologyNASController:
    """
    Controller class for Synology DS620slim NAS.
    Supports Wake-on-LAN for power on and API calls for shutdown.
    Configuration loaded from environment variables and config file.
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize the Synology NAS controller.
        
        Args:
            config_file (str, optional): Path to config file. If None, uses default locations.
        
        Configuration priority (highest to lowest):
        1. Environment variables
        2. Config file
        3. Default values
        
        Environment variables:
        - SYNOLOGY_IP: IP address of the NAS
        - SYNOLOGY_MAC: MAC address for Wake-on-LAN
        - SYNOLOGY_USER: Admin username
        - SYNOLOGY_PASSWORD: Admin password
        - SYNOLOGY_PORT: DSM port (default: 5000)
        - SYNOLOGY_ETHERNET_PORT: Ethernet port connected to NAS (default: eth0)
        """
        # Load configuration
        config = self._load_config(config_file)
        
        self.ip_address = config['ip_address']
        self.mac_address = config['mac_address'].replace(':', '').replace('-', '').upper()
        self.admin_user = config['admin_user']
        self.admin_password = config['admin_password']
        self.port = config['port']
        self.ethernet_port = config['ethernet_port']
        self.base_url = f"http://{self.ip_address}:{self.port}"
        self.session_id: Optional[str] = None
        
        # Validate MAC address format
        if len(self.mac_address) != 12:
            raise ValueError("MAC address must be 12 hex characters")
    
    def _load_config(self, config_file: Optional[str] = None) -> Dict[str, Any]:
        """
        Load configuration from environment variables, constants.json, and password file.
        
        Args:
            config_file (str, optional): Path to password file
            
        Returns:
            dict: Configuration dictionary
            
        Raises:
            ValueError: If required configuration is missing
        """
        # Default configuration
        config = {
            'ip_address': None,
            'mac_address': None,
            'admin_user': None,
            'admin_password': None,
            'port': 5000,
            'ethernet_port': 'eth0'
        }
        
        # Load constants from constants.json (contains IP, MAC, etc.)
        constants_data = self._load_constants_file()
        if constants_data:
            config.update({
                'ip_address': constants_data.get('SYNOLOGY_IP'),
                'mac_address': constants_data.get('SYNOLOGY_MAC'),
                'port': constants_data.get('SYNOLOGY_PORT', 5000)
            })
        
        # Load password from password file
        password_file = config_file or 'synology-password.json'
        password_data = self._load_password_file(password_file)
        if password_data:
            config.update(password_data)
        
        # Override with environment variables (highest priority)
        env_mapping = {
            'SYNOLOGY_IP': 'ip_address',
            'SYNOLOGY_MAC': 'mac_address',
            'SYNOLOGY_USER': 'admin_user',
            'SYNOLOGY_PASSWORD': 'admin_password',
            'SYNOLOGY_PORT': 'port',
            'SYNOLOGY_ETHERNET_PORT': 'ethernet_port'
        }
        
        for env_var, config_key in env_mapping.items():
            env_value = os.getenv(env_var)
            if env_value:
                if config_key == 'port':
                    config[config_key] = int(env_value)
                else:
                    config[config_key] = env_value
        
        # Validate required configuration
        required_fields = ['ip_address', 'mac_address', 'admin_user', 'admin_password']
        missing_fields = [field for field in required_fields if not config[field]]
        
        if missing_fields:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing_fields)}. "
                f"Check constants.json and synology-password.json files."
            )
        
        return config
    
    def _load_config_file(self, config_file: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Load configuration from JSON file.
        
        Args:
            config_file (str, optional): Path to config file
            
        Returns:
            dict or None: Configuration data or None if file not found
        """
        # Default config file locations (in order of preference)
        default_locations = [
            'synology_nas_config.json',
            os.path.expanduser('~/.config/rvSecurity/synology_nas_config.json'),
            '/etc/rvSecurity/synology_nas_config.json'
        ]
        
        config_paths = [config_file] if config_file else default_locations
        
        for config_path in config_paths:
            if config_path and os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                    logger.info(f"Loaded configuration from {config_path}")
                    return config_data
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Failed to load config from {config_path}: {e}")
        
        return None
    
    def _load_constants_file(self) -> Optional[Dict[str, Any]]:
        """
        Load constants from constants.json file.
        
        Returns:
            dict or None: Constants data or None if file not found
        """
        constants_file = 'constants.json'
        
        if os.path.exists(constants_file):
            try:
                with open(constants_file, 'r') as f:
                    constants_data = json.load(f)
                logger.info(f"Loaded constants from {constants_file}")
                return constants_data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load constants from {constants_file}: {e}")
        else:
            logger.warning(f"Constants file {constants_file} not found")
        
        return None
    
    def _load_password_file(self, password_file: str) -> dict:
        """
        Load password from file if it exists.
        
        Args:
            password_file: Path to the password file
            
        Returns:
            dict or None: Password data or None if file not found
        """
        if os.path.exists(password_file):
            try:
                with open(password_file, 'r') as f:
                    password_data = json.load(f)
                logger.info(f"Loaded password from {password_file}")
                return password_data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load password from {password_file}: {e}")
        else:
            logger.warning(f"Password file {password_file} not found")
        
        return None
    
    @classmethod
    def create_config_template(cls, config_file: str = 'synology-password.json') -> None:
        """
        Create a template password file.
        
        Args:
            config_file (str): Path for the password file template
        """
        template = {
            "admin_user": "Administrator", 
            "admin_password": "your_secure_password_here",
            "_comment": "This file contains sensitive information. Do not commit to version control!"
        }
        
        try:
            with open(config_file, 'w') as f:
                json.dump(template, f, indent=2)
            
            # Set restrictive permissions (Unix-like systems only)
            try:
                os.chmod(config_file, 0o600)  # Read/write for owner only
            except (AttributeError, OSError):
                pass  # Not Unix-like or permission change failed
            
            logger.info(f"Created password template at {config_file}")
            print(f"Password template created at {config_file}")
            print("Please edit this file with your actual NAS password.")
            print("Configuration values (IP, MAC, etc.) should be set in constants.js")
            print("DO NOT commit this file to version control!")
            
        except IOError as e:
            logger.error(f"Failed to create password template: {e}")
            raise
    
    def _send_magic_packet(self, mac_address: str, broadcast_ip: str = '255.255.255.255', port: int = 9) -> bool:
        """
        Send a Wake-on-LAN magic packet.
        
        Args:
            mac_address (str): MAC address without separators (12 hex chars)
            broadcast_ip (str): Broadcast IP address
            port (int): UDP port for WoL packet
            
        Returns:
            bool: True if packet was sent successfully
        """
        try:
            # Create magic packet: 6 bytes of 0xFF followed by 16 repetitions of MAC address
            mac_bytes = bytes.fromhex(mac_address)
            magic_packet = b'\xFF' * 6 + mac_bytes * 16
            
            # Send the packet
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(magic_packet, (broadcast_ip, port))
            
            logger.info(f"Wake-on-LAN packet sent to {mac_address}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Wake-on-LAN packet: {e}")
            return False
    
    def _authenticate(self) -> bool:
        """
        Authenticate with the Synology DSM API.
        
        Returns:
            bool: True if authentication successful
        """
        try:
            auth_url = f"{self.base_url}/webapi/auth.cgi"
            params = {
                'api': 'SYNO.API.Auth',
                'version': '3',
                'method': 'login',
                'account': self.admin_user,
                'passwd': self.admin_password,
                'session': 'SurveillanceStation',
                'format': 'cookie'
            }
            
            response = requests.get(auth_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get('success'):
                self.session_id = data.get('data', {}).get('sid')
                logger.info("Successfully authenticated with Synology NAS")
                return True
            else:
                logger.error(f"Authentication failed: {data.get('error', {})}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
    
    def _logout(self) -> None:
        """Logout from the Synology DSM API."""
        if not self.session_id:
            return
            
        try:
            logout_url = f"{self.base_url}/webapi/auth.cgi"
            params = {
                'api': 'SYNO.API.Auth',
                'version': '3',
                'method': 'logout',
                'session': 'SurveillanceStation'
            }
            
            requests.get(logout_url, params=params, timeout=5)
            self.session_id = None
            logger.info("Logged out from Synology NAS")
            
        except Exception as e:
            logger.warning(f"Logout error (non-critical): {e}")
    
    def _is_ethernet_port_active(self) -> bool:
        """
        Check if the specified ethernet port is active and has a link.
        
        Returns:
            bool: True if ethernet port is active and has link
        """
        try:
            # Check if interface exists and is up
            with open(f'/sys/class/net/{self.ethernet_port}/operstate', 'r') as f:
                state = f.read().strip()
            
            if state != 'up':
                logger.error(f"Ethernet port {self.ethernet_port} is not up (state: {state})")
                return False
            
            # Check if carrier is detected (cable connected)
            try:
                with open(f'/sys/class/net/{self.ethernet_port}/carrier', 'r') as f:
                    carrier = f.read().strip()
                
                if carrier != '1':
                    logger.error(f"Ethernet port {self.ethernet_port} has no carrier (cable disconnected)")
                    return False
            except IOError:
                # Some interfaces don't support carrier detection
                logger.warning(f"Cannot check carrier status for {self.ethernet_port}")
            
            logger.info(f"Ethernet port {self.ethernet_port} is active and ready")
            return True
            
        except IOError as e:
            logger.error(f"Failed to check ethernet port {self.ethernet_port}: {e}")
            return False
    
    def is_online(self) -> bool:
        """
        Check if the NAS is online by attempting to connect to the DSM interface.
        
        Returns:
            bool: True if NAS is online and responding
        """
        try:
            response = requests.get(f"{self.base_url}/", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def power_on(self) -> bool:
        """
        Power on the NAS using Wake-on-LAN.
        First verifies that the ethernet port is active before sending WoL packet.
        
        Returns:
            bool: True if WoL packet was sent successfully
        """
        logger.info(f"Attempting to power on NAS at {self.ip_address}")
        
        if self.is_online():
            logger.info("NAS is already online")
            return True
        
        # Check if ethernet port is active before attempting WoL
        if not self._is_ethernet_port_active():
            logger.error(f"Cannot send Wake-on-LAN: ethernet port {self.ethernet_port} is not active")
            return False
        
        # Use subnet broadcast with port 7 (approach 4 from troubleshooting)
        # This was found to work better than global broadcast with port 9
        subnet_broadcast = f"{self.ip_address.rsplit('.', 1)[0]}.255"
        return self._send_magic_packet(self.mac_address, broadcast_ip=subnet_broadcast, port=7)
    
    def power_off(self) -> bool:
        """
        Power off the NAS using the DSM API shutdown command.
        
        Returns:
            bool: True if shutdown command was sent successfully
        """
        logger.info(f"Attempting to shutdown NAS at {self.ip_address}")
        
        if not self.is_online():
            logger.info("NAS is already offline")
            return True
        
        if not self._authenticate():
            logger.error("Failed to authenticate for shutdown")
            return False
        
        try:
            shutdown_url = f"{self.base_url}/webapi/entry.cgi"
            params = {
                'api': 'SYNO.Core.System',
                'version': '1',  # Version 1 works according to tests
                'method': 'shutdown',
                '_sid': self.session_id
            }
            
            response = requests.get(shutdown_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get('success'):
                logger.info("Shutdown command sent successfully")
                return True
            else:
                logger.error(f"Shutdown failed: {data.get('error', {})}")
                return False
                
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
            return False
        finally:
            self._logout()
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the NAS.
        
        Returns:
            dict: Status information including online status and system info
        """
        status = {
            'online': self.is_online(),
            'ip_address': self.ip_address,
            'mac_address': self.mac_address,
            'ethernet_port': self.ethernet_port,
            'ethernet_active': self._is_ethernet_port_active(),
            'timestamp': time.time()
        }
        
        if status['online'] and self._authenticate():
            try:
                info_url = f"{self.base_url}/webapi/entry.cgi"
                params = {
                    'api': 'SYNO.Core.System',
                    'version': '3',
                    'method': 'info',
                    '_sid': self.session_id
                }
                
                response = requests.get(info_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        status['system_info'] = data.get('data', {})
                        
            except Exception as e:
                logger.warning(f"Failed to get system info: {e}")
            finally:
                self._logout()
        
        return status


if __name__ == "__main__":
    import sys
    import argparse
    
    def main():
        """Main command-line interface using argparse."""
        parser = argparse.ArgumentParser(
            description='Synology NAS DS620slim Controller',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  python synology_nas_controller.py --status
  python synology_nas_controller.py --power-on
  python synology_nas_controller.py --power-off
  python synology_nas_controller.py --create-config
  python synology_nas_controller.py --config /path/to/password.json --status
  python synology_nas_controller.py --config custom-password.json --power-on
            """
        )
        
        # Configuration file argument
        parser.add_argument('--config', '--password-file',
                           help='Path to password file (default: synology-password.json)')
        
        # Command group - mutually exclusive
        command_group = parser.add_mutually_exclusive_group(required=True)
        command_group.add_argument('--status', action='store_true',
                                  help='Show NAS status and system information')
        command_group.add_argument('--power-on', action='store_true',
                                  help='Power on the NAS using Wake-on-LAN')
        command_group.add_argument('--power-off', action='store_true',
                                  help='Power off the NAS using DSM API')
        command_group.add_argument('--create-config', action='store_true',
                                  help='Create a password file template')
        
        # Additional options
        parser.add_argument('--force', action='store_true',
                           help='Skip confirmation prompt for power-off')
        parser.add_argument('--verbose', '-v', action='store_true',
                           help='Enable verbose logging output')
        
        # Parse arguments
        args = parser.parse_args()
        
        # Configure logging
        log_level = logging.DEBUG if args.verbose else logging.INFO
        logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
        
        try:
            if args.create_config:
                # Create config template
                config_file = args.config or 'synology-password.json'
                SynologyNASController.create_config_template(config_file)
                sys.exit(0)
            
            # For all other commands, create the controller
            nas = SynologyNASController(config_file=args.config)
            
            if args.status:
                # Show NAS status
                print("Synology NAS Status:")
                print("-" * 50)
                
                status = nas.get_status()
                
                # Basic status
                online_status = "ONLINE" if status['online'] else "OFFLINE"
                print(f"Status:        {online_status}")
                print(f"IP Address:    {status['ip_address']}")
                print(f"MAC Address:   {status['mac_address']}")
                print(f"Ethernet Port: {status['ethernet_port']}")
                
                eth_status = "ACTIVE" if status['ethernet_active'] else "INACTIVE"
                print(f"Ethernet:      {eth_status}")
                
                # System information (if available)
                if 'system_info' in status and status['system_info']:
                    print("\nSystem Information:")
                    print("-" * 50)
                    sys_info = status['system_info']
                    
                    if 'model' in sys_info:
                        print(f"Model:         {sys_info['model']}")
                    if 'firmware_ver' in sys_info:
                        print(f"Firmware:      {sys_info['firmware_ver']}")
                    if 'up_time' in sys_info:
                        print(f"Uptime:        {sys_info['up_time']}")
                    if 'sys_temp' in sys_info:
                        print(f"Temperature:   {sys_info['sys_temp']}°C")
                    if 'cpu_family' in sys_info and 'cpu_series' in sys_info:
                        print(f"CPU:           {sys_info['cpu_family']} {sys_info['cpu_series']}")
                    if 'ram_size' in sys_info:
                        print(f"RAM:           {sys_info['ram_size']} MB")
                
            elif args.power_on:
                # Power on the NAS
                print("Sending Wake-on-LAN packet to power on NAS...")
                result = nas.power_on()
                
                if result:
                    print("SUCCESS: Wake-on-LAN packet sent")
                    print("The NAS should boot up in 30-60 seconds")
                else:
                    print("FAILED: Could not send Wake-on-LAN packet")
                    sys.exit(1)
            
            elif args.power_off:
                # Power off the NAS
                if not args.force:
                    print("WARNING: This will shut down the NAS!")
                    try:
                        confirm = input("Are you sure you want to shutdown the NAS? (yes/no): ")
                        if confirm.lower() not in ['yes', 'y']:
                            print("Shutdown cancelled")
                            sys.exit(0)
                    except KeyboardInterrupt:
                        print("\nShutdown cancelled by user (Ctrl+C)")
                        sys.exit(0)
                
                print("Sending shutdown command to NAS...")
                result = nas.power_off()
                
                if result:
                    print("SUCCESS: Shutdown command sent")
                    print("The NAS will shut down in a few seconds")
                else:
                    print("FAILED: Could not send shutdown command")
                    sys.exit(1)
        
        except ValueError as e:
            print(f"Configuration error: {e}")
            print("\nTo create a password template, run:")
            print("python synology_nas_controller.py --create-config")
            print("Make sure constants.json exists (run makefile to generate from constants.js)")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nOperation cancelled by user (Ctrl+C)")
            sys.exit(0)
        except Exception as e:
            print(f"ERROR: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)
    
    main()
