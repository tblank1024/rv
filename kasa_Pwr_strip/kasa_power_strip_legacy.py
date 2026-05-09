# Modern Kasa Smart Plug Power Strip HS300 controller classes - SYNC ONLY VERSION
# This module contains the KasaPowerStrip class and related exceptions for controlling
# Kasa HS300 Smart Power Strip using the python-kasa library.
# 
# NOTE: This version has been simplified to remove all async methods and threading complexity
# that was causing system instability in Docker environments.

import asyncio
import json
import ipaddress
import time
import os
from typing import Dict, List, Optional, Union
import kasa


class KasaPowerStripError(Exception):
    """Exception raised for Kasa power strip communication errors."""
    pass


class KasaPowerStrip:
    """Simplified synchronous controller for Kasa HS300 Smart Power Strip.
       
       This version uses only blocking operations to avoid threading issues.
       All async methods have been removed for system stability.
       
       Features:
       - Individual outlet control (on/off/toggle)
       - Real-time power monitoring per outlet
       - Energy consumption tracking
       - Power summaries
       - Test mode for sequential outlet testing
       - Basic device discovery
    """
    
    def __init__(self, host: Optional[str] = None, timeout: int = 10):
        """
        Initialize the Kasa Power Strip controller.
        
        Args:
            host: IP address of the power strip (if None, will auto-discover)
            timeout: Connection timeout in seconds (default: 10)
        """
        import os
        
        # Support environment variables for Docker configuration
        self.host = host or os.getenv('KASA_HOST')
        self.timeout = timeout or int(os.getenv('KASA_DEFAULT_TIMEOUT', '10'))
        self.device = None
        self._is_docker = self._detect_docker_environment()
    
    def _detect_docker_environment(self) -> bool:
        """Detect if running inside a Docker container."""
        import os
        return os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER') == 'true'
    
    def _run_async(self, coro):
        """
        Run an async coroutine in a blocking manner with proper error handling and timeout.
        This is the ONLY method that deals with asyncio - all other methods are purely sync.
        """
        def run_with_timeout():
            try:
                # Try to get existing event loop
                try:
                    loop = asyncio.get_running_loop()
                    # We're in an async context, need to run in thread
                    import concurrent.futures
                    import threading
                    
                    result = None
                    exception = None
                    
                    def run_in_thread():
                        nonlocal result, exception
                        try:
                            # Create new event loop for this thread
                            new_loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(new_loop)
                            try:
                                result = new_loop.run_until_complete(
                                    asyncio.wait_for(coro, timeout=self.timeout)
                                )
                            finally:
                                new_loop.close()
                                asyncio.set_event_loop(None)
                        except Exception as e:
                            exception = e
                    
                    thread = threading.Thread(target=run_in_thread)
                    thread.start()
                    thread.join(timeout=self.timeout + 5)
                    
                    if thread.is_alive():
                        raise TimeoutError(f"Operation timed out after {self.timeout + 5} seconds")
                    
                    if exception:
                        raise exception
                    
                    return result
                    
                except RuntimeError:
                    # No event loop running, we can create one
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        return loop.run_until_complete(
                            asyncio.wait_for(coro, timeout=self.timeout)
                        )
                    finally:
                        loop.close()
                        asyncio.set_event_loop(None)
            
            except asyncio.TimeoutError:
                raise TimeoutError(f"Kasa operation timed out after {self.timeout} seconds")
            except Exception as e:
                if "Cannot connect to host" in str(e):
                    raise KasaPowerStripError(f"Cannot connect to Kasa device at {self.host}: {e}")
                elif "timeout" in str(e).lower():
                    raise TimeoutError(f"Kasa operation timed out: {e}")
                elif "time zone" in str(e).lower() or "timezone" in str(e).lower():
                    print(f"⚠️  Timezone issue detected: {e}")
                    print("💡 This is usually harmless - device connection may still work")
                    # For timezone errors, we'll continue but log the issue
                    return None  # Let the caller handle this gracefully
                else:
                    raise KasaPowerStripError(f"Kasa operation failed: {e}")
        
        return run_with_timeout()
    
    @classmethod
    def discover_power_strips_sync(cls, scan_all_networks=False, timeout=30):
        """
        Synchronous wrapper for discovering power strips.
        Enhanced with Docker network debugging and better error reporting.
        
        Args:
            scan_all_networks: Legacy parameter (ignored in sync version)
            timeout: Discovery timeout in seconds
            
        Returns:
            List of discovered power strip information
        """
        try:
            async def enhanced_discover():
                print(f"🔍 Starting Kasa discovery (timeout: {timeout}s)...")
                
                # Check Docker environment
                is_docker = os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER') == 'true'
                if is_docker:
                    print("🐳 Running in Docker container")
                    
                    # Check network capabilities
                    try:
                        import socket
                        # Test if we can create raw sockets (indicates NET_RAW capability)
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
                            sock.close()
                            print("✅ NET_RAW capability available")
                        except PermissionError:
                            print("⚠️  NET_RAW capability missing - may affect discovery")
                        
                        # Check network interfaces
                        try:
                            with open('/proc/net/dev', 'r') as f:
                                interfaces = f.readlines()[2:]  # Skip headers
                                print(f"📡 Available network interfaces: {len(interfaces)}")
                                for line in interfaces[:3]:  # Show first 3
                                    iface = line.split(':')[0].strip()
                                    print(f"   - {iface}")
                        except Exception as e:
                            print(f"⚠️  Cannot read network interfaces: {e}")
                            
                    except Exception as e:
                        print(f"⚠️  Network capability check failed: {e}")
                
                # Attempt discovery
                print("🔍 Attempting Kasa device discovery...")
                devices = await kasa.Discover.discover(timeout=timeout)
                discovered = []
                
                print(f"📡 Discovery found {len(devices)} device(s)")
                
                for ip, device in devices.items():
                    try:
                        print(f"🔌 Testing device at {ip}...")
                        await device.update()
                        if hasattr(device, 'children') and len(device.children) > 1:
                            print(f"✅ Found power strip: {device.alias} at {ip}")
                            discovered.append({
                                "ip": ip,
                                "alias": device.alias,
                                "model": device.model,
                                "device_type": type(device).__name__,
                                "mac": getattr(device, 'mac', 'Unknown'),
                                "children_count": len(device.children),
                                "rssi": getattr(device, 'rssi', None)
                            })
                        else:
                            print(f"⚠️  Device at {ip} is not a power strip (children: {len(getattr(device, 'children', []))})")
                    except Exception as e:
                        print(f"❌ Error updating device {ip}: {e}")
                
                if discovered:
                    print(f"✅ Discovery completed: Found {len(discovered)} power strip(s)")
                else:
                    print("❌ Discovery completed: No power strips found")
                    print("💡 Troubleshooting tips:")
                    print("   - Verify power strip is powered on and connected to network")
                    print("   - Check if power strip is on same subnet as Docker host")
                    print("   - Consider setting KASA_HOST environment variable with direct IP")
                
                return discovered
            
            # Create a temporary instance to use _run_async
            temp_instance = cls(host="dummy", timeout=timeout)
            return temp_instance._run_async(enhanced_discover())
            
        except Exception as e:
            print(f"Discovery failed: {e}")
            return []
    
    @classmethod
    def auto_connect_sync(cls, timeout: int = 10) -> Optional['KasaPowerStrip']:
        """
        Synchronous auto-connect that tries environment variable first, then discovery.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            KasaPowerStrip instance if found and connected, None otherwise
        """
        import os
        
        # Check for environment variable first
        env_host = os.getenv('KASA_HOST')
        if env_host:
            print(f"Using Kasa host from environment: {env_host}")
            try:
                strip = cls(host=env_host, timeout=timeout)
                if strip.connect():
                    return strip
            except Exception as e:
                print(f"Failed to connect to environment-specified host {env_host}: {e}")
        
        # Try discovery
        print("Discovering power strips...")
        power_strips = cls.discover_power_strips_sync(timeout=timeout)
        
        if not power_strips:
            print("No power strips found")
            return None
        
        # Use first one found
        strip_info = power_strips[0]
        print(f"Connecting to {strip_info['alias']} at {strip_info['ip']}...")
        try:
            strip = cls(host=strip_info["ip"], timeout=timeout)
            if strip.connect():
                return strip
        except Exception as e:
            print(f"Failed to connect: {e}")
        
        return None
    
    def _ensure_connected_sync(self):
        """Ensure device is connected and updated - sync version."""
        async def connect_and_update():
            if self.device is None:
                self.device = await kasa.Device.connect(host=self.host)
            await self.device.update()
        
        self._run_async(connect_and_update())
    
    def connect(self) -> bool:
        """
        Connect to the device and perform initial discovery.
        If no host was specified, attempts auto-discovery.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # If no host specified, use discovery
            if self.host is None:
                print("🔍 No host specified, checking environment or using discovery...")
                
                # Check for environment variable first (useful for Docker deployments)
                env_host = os.getenv('KASA_HOST')
                if env_host:
                    print(f"🎯 Using Kasa host from environment: {env_host}")
                    self.host = env_host
                else:
                    # Use sync discovery
                    print("🔍 No KASA_HOST set, attempting discovery...")
                    power_strips = self.discover_power_strips_sync()
                    if not power_strips:
                        raise KasaPowerStripError("No power strips found on network")
                    
                    print(f"✅ Found {len(power_strips)} power strip(s):")
                    for i, strip in enumerate(power_strips):
                        print(f"  {i+1}. {strip['alias']} at {strip['ip']} ({strip['model']})")
                    
                    # Use the first one found
                    self.host = power_strips[0]["ip"]
                    print(f"🎯 Connecting to {power_strips[0]['alias']} at {self.host}...")
            else:
                print(f"🎯 Using pre-configured host: {self.host}")
            
            # Connect to device
            print(f"🔌 Attempting to connect to Kasa device at {self.host}...")
            async def sync_connect():
                try:
                    self.device = await kasa.Device.connect(host=self.host)
                    await self.device.update()
                    return True
                except Exception as e:
                    if "time zone" in str(e).lower() or "timezone" in str(e).lower():
                        print(f"⚠️  Timezone warning during update: {e}")
                        print("🔄 Attempting connection without full update...")
                        # Try connecting without update for timezone issues
                        self.device = await kasa.Device.connect(host=self.host)
                        return True
                    else:
                        raise e
            
            result = self._run_async(sync_connect())
            if result is None:
                # Handle timezone issues gracefully
                print("⚠️  Connection completed with warnings (likely timezone related)")
            else:
                print(f"✅ Successfully connected to Kasa device at {self.host}")
            
            # Display device information (if we have a device)
            if self.device:
                print(f"📋 Device Info:")
                try:
                    print(f"   - Alias: {getattr(self.device, 'alias', 'Unknown')}")
                    print(f"   - Model: {getattr(self.device, 'model', 'Unknown')}")
                    print(f"   - Children: {len(getattr(self.device, 'children', []))}")
                    if hasattr(self.device, 'children') and len(self.device.children) > 0:
                        print(f"   - Power Strip: Yes")
                    else:
                        print(f"   - Power Strip: No (not a multi-outlet device)")
                except Exception as e:
                    print(f"   - Info retrieval warning: {e}")
            
            return True
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the device."""
        if self.device:
            try:
                async def sync_disconnect():
                    await self.device.disconnect()
                
                self._run_async(sync_disconnect())
            except:
                pass  # Ignore errors during disconnect
            self.device = None
    
    def get_system_info(self) -> Dict:
        """Get system information from the power strip."""
        self._ensure_connected_sync()
        
        return {
            "alias": self.device.alias,
            "model": self.device.model,
            "device_id": self.device.device_id,
            "hw_version": self.device.hw_info.get("hw_ver"),
            "sw_version": self.device.hw_info.get("sw_ver"),
            "mac": self.device.mac,
            "rssi": getattr(self.device, 'rssi', None),
            "is_on": self.device.is_on,
            "children_count": len(self.device.children) if hasattr(self.device, 'children') else 0,
            "children": [
                {
                    "index": i,
                    "alias": child.alias,
                    "device_id": child.device_id,
                    "is_on": child.is_on
                }
                for i, child in enumerate(self.device.children)
            ] if hasattr(self.device, 'children') else []
        }
    
    def turn_on_outlet(self, outlet_id: int) -> bool:
        """Turn on a specific outlet."""
        async def sync_turn_on():
            self._ensure_connected_sync()
            
            if not hasattr(self.device, 'children'):
                raise KasaPowerStripError("Device does not have child outlets")
            
            if not 0 <= outlet_id < len(self.device.children):
                raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
            
            outlet = list(self.device.children)[outlet_id]
            await outlet.turn_on()
            return True
        
        return self._run_async(sync_turn_on())
    
    def turn_off_outlet(self, outlet_id: int) -> bool:
        """Turn off a specific outlet."""
        async def sync_turn_off():
            self._ensure_connected_sync()
            
            if not hasattr(self.device, 'children'):
                raise KasaPowerStripError("Device does not have child outlets")
            
            if not 0 <= outlet_id < len(self.device.children):
                raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
            
            outlet = list(self.device.children)[outlet_id]
            await outlet.turn_off()
            return True
        
        return self._run_async(sync_turn_off())
    
    def toggle_outlet(self, outlet_id: int) -> bool:
        """Toggle the state of a specific outlet."""
        async def sync_toggle():
            self._ensure_connected_sync()
            
            if not hasattr(self.device, 'children'):
                raise KasaPowerStripError("Device does not have child outlets")
            
            if not 0 <= outlet_id < len(self.device.children):
                raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
            
            outlet = list(self.device.children)[outlet_id]
            if outlet.is_on:
                await outlet.turn_off()
            else:
                await outlet.turn_on()
            return True
        
        return self._run_async(sync_toggle())
    
    def get_outlet_status(self, outlet_id: int) -> Dict:
        """Get status of a specific outlet."""
        self._ensure_connected_sync()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        if not 0 <= outlet_id < len(self.device.children):
            raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
        
        outlet = list(self.device.children)[outlet_id]
        return {
            "outlet_id": outlet_id,
            "alias": outlet.alias,
            "is_on": outlet.is_on,
            "device_id": outlet.device_id
        }
    
    def get_all_outlet_status(self) -> List[Dict]:
        """Get status of all outlets."""
        self._ensure_connected_sync()
        
        if not hasattr(self.device, 'children'):
            return []
        
        return [
            {
                "outlet_id": i,
                "alias": child.alias,
                "is_on": child.is_on,
                "device_id": child.device_id
            }
            for i, child in enumerate(self.device.children)
        ]
    
    def turn_on_all_outlets(self) -> List[Dict]:
        """Turn on all outlets."""
        async def sync_turn_on_all():
            self._ensure_connected_sync()
            
            if not hasattr(self.device, 'children'):
                return []
            
            results = []
            for i, outlet in enumerate(self.device.children):
                try:
                    await outlet.turn_on()
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias,
                        "success": True,
                        "is_on": True
                    })
                except Exception as e:
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias,
                        "success": False,
                        "error": str(e)
                    })
            
            return results
        
        return self._run_async(sync_turn_on_all())
    
    def turn_off_all_outlets(self) -> List[Dict]:
        """Turn off all outlets."""
        async def sync_turn_off_all():
            self._ensure_connected_sync()
            
            if not hasattr(self.device, 'children'):
                return []
            
            results = []
            for i, outlet in enumerate(self.device.children):
                try:
                    await outlet.turn_off()
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias,
                        "success": True,
                        "is_on": False
                    })
                except Exception as e:
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias,
                        "success": False,
                        "error": str(e)
                    })
            
            return results
        
        return self._run_async(sync_turn_off_all())
    
    def get_power_consumption(self, outlet_id: int) -> Dict:
        """Get power consumption for a specific outlet."""
        async def sync_get_power():
            self._ensure_connected_sync()
            
            if not hasattr(self.device, 'children'):
                raise KasaPowerStripError("Device does not have child outlets")
            
            if not 0 <= outlet_id < len(self.device.children):
                raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
            
            outlet = list(self.device.children)[outlet_id]
            
            # Get current power consumption
            current_power = getattr(outlet, 'current_consumption', 0)
            voltage = getattr(outlet, 'voltage', 0)
            current = getattr(outlet, 'current', 0)
            
            return {
                "outlet_id": outlet_id,
                "alias": outlet.alias,
                "current_power_w": current_power,
                "voltage_v": voltage,
                "current_a": current,
                "is_on": outlet.is_on
            }
        
        return self._run_async(sync_get_power())
    
    def get_all_power_consumption(self) -> List[Dict]:
        """Get power consumption for all outlets."""
        if not hasattr(self.device, 'children'):
            return []
        
        results = []
        for i in range(len(self.device.children)):
            try:
                power_data = self.get_power_consumption(i)
                results.append(power_data)
            except Exception as e:
                results.append({
                    "outlet_id": i,
                    "alias": f"Outlet {i}",
                    "error": str(e),
                    "current_power_w": 0,
                    "voltage_v": 0,
                    "current_a": 0,
                    "is_on": False
                })
        
        return results
    
    def get_power_summary(self) -> Dict:
        """Get a summary of power consumption across all outlets."""
        power_data = self.get_all_power_consumption()
        
        total_power = sum(outlet.get('current_power_w', 0) for outlet in power_data)
        active_outlets = sum(1 for outlet in power_data if outlet.get('is_on', False))
        total_outlets = len(power_data)
        
        return {
            "total_power_w": total_power,
            "active_outlets": active_outlets,
            "total_outlets": total_outlets,
            "average_power_per_active_outlet": total_power / active_outlets if active_outlets > 0 else 0,
            "outlets": power_data
        }
    
    def test_outlets(self, test_duration: int = 3) -> List[Dict]:
        """Test all outlets by turning them on/off sequentially."""
        async def sync_test():
            self._ensure_connected_sync()
            
            if not hasattr(self.device, 'children'):
                return []
            
            results = []
            outlet_count = len(self.device.children)
            
            print(f"Starting outlet test mode - {outlet_count} outlets")
            print(f"Each outlet will be ON for {test_duration} seconds")
            print("=" * 60)
            
            for i, outlet in enumerate(self.device.children):
                start_time = time.time()
                try:
                    print(f"\nTesting Outlet {i} ({outlet.alias})...")
                    
                    # Turn on the outlet
                    await outlet.turn_on()
                    print(f"  Turned ON at {time.strftime('%H:%M:%S')}")
                    
                    # Wait for specified duration
                    for remaining in range(test_duration, 0, -1):
                        print(f"  Timer: {remaining} seconds remaining", end="\r")
                        time.sleep(1)
                    
                    # Turn off the outlet
                    await outlet.turn_off()
                    end_time = time.time()
                    actual_duration = end_time - start_time
                    
                    print(f"\n  Turned OFF at {time.strftime('%H:%M:%S')}")
                    print(f"  Duration: {actual_duration:.1f} seconds")
                    
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias,
                        "success": True,
                        "duration": actual_duration,
                        "error": None
                    })
                    
                except Exception as e:
                    print(f"  Error testing outlet {i}: {e}")
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias if hasattr(outlet, 'alias') else f"Outlet {i}",
                        "success": False,
                        "duration": 0,
                        "error": str(e)
                    })
            
            print("\n" + "=" * 60)
            print("Test mode completed!")
            
            # Summary
            successful_tests = sum(1 for r in results if r["success"])
            print(f"Results: {successful_tests}/{outlet_count} outlets tested successfully")
            
            return results
        
        return self._run_async(sync_test())


# Legacy alias for backwards compatibility
KasaHS300Controller = KasaPowerStrip
