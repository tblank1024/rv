# Modern Kasa Smart Plug Power Strip HS300 controller using python-kasa library
# This version uses the official python-kasa library which supports modern encryption
# and authentication methods. Requires "third party compatibility" enabled in Kasa app.

import asyncio
import json
from typing import Dict, List, Optional, Union
import kasa


class KasaPowerStripError(Exception):
    """Exception raised for Kasa power strip communication errors."""
    pass


class KasaPowerStrip:
    """Modern controller for Kasa HS300 Smart Power Strip using python-kasa library.
       
       Requires initial setup using the Kasa app to link the device to a TP-Link account. 
       And, in the device settings, you must enable "Third Party Compatibility." This uses
       the less secure authentication method, allowing anyone on the local network to control 
       the device without needing to log in with the TP-Link account each time.
       
       Features:
       - Individual outlet control (on/off/toggle)
       - Real-time power monitoring per outlet
       - Energy consumption tracking
       - Comprehensive power summaries
       - Test mode for sequential outlet testing
       - Power usage monitoring over time
    """
    
    def __init__(self, host: str, timeout: int = 10):
        """
        Initialize the Kasa Power Strip controller.
        
        Args:
            host: IP address of the power strip
            timeout: Connection timeout in seconds (default: 10)
        """
        self.host = host
        self.timeout = timeout
        self.device = None
        self._loop = None
    
    def _get_loop(self):
        """Get or create event loop for async operations."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Loop is closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop
    
    def _run_async(self, coro):
        """Run async function synchronously."""
        loop = self._get_loop()
        return loop.run_until_complete(coro)
    
    async def _ensure_connected(self):
        """Ensure device is connected and updated."""
        if self.device is None:
            self.device = await kasa.Device.connect(host=self.host)
        await self.device.update()
    
    def connect(self) -> bool:
        """
        Connect to the device and perform initial discovery.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            return self._run_async(self._async_connect())
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    async def _async_connect(self) -> bool:
        """Async version of connect."""
        try:
            self.device = await kasa.Device.connect(host=self.host)
            await self.device.update()
            return True
        except Exception as e:
            raise KasaPowerStripError(f"Failed to connect to device: {e}")
    
    def disconnect(self):
        """Disconnect from the device."""
        if self.device:
            try:
                self._run_async(self.device.disconnect())
            except:
                pass  # Ignore errors during disconnect
            self.device = None
    
    def get_system_info(self) -> Dict:
        """Get system information from the power strip."""
        return self._run_async(self._async_get_system_info())
    
    async def _async_get_system_info(self) -> Dict:
        """Async version of get_system_info."""
        await self._ensure_connected()
        
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
        """
        Turn on a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            True if successful
        """
        return self._run_async(self._async_turn_on_outlet(outlet_id))
    
    async def _async_turn_on_outlet(self, outlet_id: int) -> bool:
        """Async version of turn_on_outlet."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        if not 0 <= outlet_id < len(self.device.children):
            raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
        
        outlet = list(self.device.children)[outlet_id]
        await outlet.turn_on()
        return True
    
    def turn_off_outlet(self, outlet_id: int) -> bool:
        """
        Turn off a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            True if successful
        """
        return self._run_async(self._async_turn_off_outlet(outlet_id))
    
    async def _async_turn_off_outlet(self, outlet_id: int) -> bool:
        """Async version of turn_off_outlet."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        if not 0 <= outlet_id < len(self.device.children):
            raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
        
        outlet = list(self.device.children)[outlet_id]
        await outlet.turn_off()
        return True
    
    def toggle_outlet(self, outlet_id: int) -> bool:
        """
        Toggle the state of a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            True if successful
        """
        return self._run_async(self._async_toggle_outlet(outlet_id))
    
    async def _async_toggle_outlet(self, outlet_id: int) -> bool:
        """Async version of toggle_outlet."""
        await self._ensure_connected()
        
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
    
    def get_outlet_status(self, outlet_id: int) -> Dict:
        """
        Get the status of a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Outlet status information
        """
        return self._run_async(self._async_get_outlet_status(outlet_id))
    
    async def _async_get_outlet_status(self, outlet_id: int) -> Dict:
        """Async version of get_outlet_status."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        if not 0 <= outlet_id < len(self.device.children):
            raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
        
        outlet = list(self.device.children)[outlet_id]
        await outlet.update()
        
        return {
            "outlet_id": outlet_id,
            "alias": outlet.alias,
            "is_on": outlet.is_on,
            "device_id": outlet.device_id,
            "model": outlet.model,
            "has_emeter": hasattr(outlet, 'emeter_realtime') and outlet.has_emeter
        }
    
    def get_all_outlet_status(self) -> List[Dict]:
        """Get the status of all outlets."""
        return self._run_async(self._async_get_all_outlet_status())
    
    async def _async_get_all_outlet_status(self) -> List[Dict]:
        """Async version of get_all_outlet_status."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        statuses = []
        for i, outlet in enumerate(self.device.children):
            await outlet.update()
            statuses.append({
                "outlet_id": i,
                "alias": outlet.alias,
                "is_on": outlet.is_on,
                "device_id": outlet.device_id,
                "model": outlet.model,
                "has_emeter": hasattr(outlet, 'emeter_realtime') and outlet.has_emeter
            })
        
        return statuses
    
    def turn_on_all_outlets(self) -> List[Dict]:
        """Turn on all outlets."""
        return self._run_async(self._async_turn_on_all_outlets())
    
    async def _async_turn_on_all_outlets(self) -> List[Dict]:
        """Async version of turn_on_all_outlets."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        results = []
        for i, outlet in enumerate(self.device.children):
            try:
                await outlet.turn_on()
                results.append({"outlet_id": i, "success": True, "error": None})
            except Exception as e:
                results.append({"outlet_id": i, "success": False, "error": str(e)})
        
        return results
    
    def turn_off_all_outlets(self) -> List[Dict]:
        """Turn off all outlets."""
        return self._run_async(self._async_turn_off_all_outlets())
    
    async def _async_turn_off_all_outlets(self) -> List[Dict]:
        """Async version of turn_off_all_outlets."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        results = []
        for i, outlet in enumerate(self.device.children):
            try:
                await outlet.turn_off()
                results.append({"outlet_id": i, "success": True, "error": None})
            except Exception as e:
                results.append({"outlet_id": i, "success": False, "error": str(e)})
        
        return results
    
    def get_power_consumption(self, outlet_id: int) -> Dict:
        """
        Get power consumption data for a specific outlet.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Power consumption data
        """
        return self._run_async(self._async_get_power_consumption(outlet_id))
    
    async def _async_get_power_consumption(self, outlet_id: int) -> Dict:
        """Async version of get_power_consumption."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        if not 0 <= outlet_id < len(self.device.children):
            raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
        
        outlet = list(self.device.children)[outlet_id]
        
        if not hasattr(outlet, 'emeter_realtime') or not outlet.has_emeter:
            return {
                "outlet_id": outlet_id,
                "error": "Outlet does not support power monitoring"
            }
        
        await outlet.update()
        emeter = outlet.emeter_realtime
        
        return {
            "outlet_id": outlet_id,
            "alias": outlet.alias,
            "power_w": emeter.power,
            "voltage_v": emeter.voltage,
            "current_a": emeter.current,
            "total_kwh": emeter.total
        }
    
    def get_all_power_consumption(self) -> List[Dict]:
        """Get power consumption for all outlets that support it."""
        return self._run_async(self._async_get_all_power_consumption())
    
    async def _async_get_all_power_consumption(self) -> List[Dict]:
        """Async version of get_all_power_consumption."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        results = []
        for i, outlet in enumerate(self.device.children):
            try:
                if hasattr(outlet, 'emeter_realtime') and outlet.has_emeter:
                    await outlet.update()
                    emeter = outlet.emeter_realtime
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias,
                        "power_w": emeter.power,
                        "voltage_v": emeter.voltage,
                        "current_a": emeter.current,
                        "total_kwh": emeter.total
                    })
                else:
                    results.append({
                        "outlet_id": i,
                        "alias": outlet.alias,
                        "error": "Outlet does not support power monitoring"
                    })
            except Exception as e:
                results.append({
                    "outlet_id": i,
                    "error": str(e)
                })
        
        return results
    
    def get_detailed_power_data(self, outlet_id: int) -> Dict:
        """
        Get detailed power data for a specific outlet including energy stats.
        
        Args:
            outlet_id: Outlet number (0-5)
            
        Returns:
            Detailed power data including realtime and historical consumption
        """
        return self._run_async(self._async_get_detailed_power_data(outlet_id))
    
    async def _async_get_detailed_power_data(self, outlet_id: int) -> Dict:
        """Async version of get_detailed_power_data."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        if not 0 <= outlet_id < len(self.device.children):
            raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
        
        outlet = list(self.device.children)[outlet_id]
        await outlet.update()
        
        # Get basic info
        power_data = {
            "outlet_id": outlet_id,
            "alias": outlet.alias,
            "is_on": outlet.is_on,
            "has_energy_monitoring": outlet.has_emeter if hasattr(outlet, 'has_emeter') else False
        }
        
        # Get energy module data if available
        if hasattr(outlet, 'modules') and 'Energy' in outlet.modules:
            energy_module = outlet.modules['Energy']
            
            # Real-time data
            if hasattr(energy_module, 'current_consumption'):
                power_data.update({
                    "current_power_w": energy_module.current_consumption,
                    "voltage_v": getattr(energy_module, 'voltage', None),
                    "current_a": getattr(energy_module, 'current', None),
                })
            
            # Energy consumption data
            if hasattr(energy_module, 'consumption_today'):
                power_data.update({
                    "energy_today_kwh": energy_module.consumption_today,
                    "energy_this_month_kwh": getattr(energy_module, 'consumption_this_month', None),
                    "energy_total_kwh": getattr(energy_module, 'consumption_total', None),
                })
        
        # Fallback to deprecated emeter_realtime if Energy module not available
        elif hasattr(outlet, 'emeter_realtime') and outlet.has_emeter:
            emeter = outlet.emeter_realtime
            power_data.update({
                "current_power_w": emeter.power,
                "voltage_v": emeter.voltage,
                "current_a": emeter.current,
                "energy_total_kwh": emeter.total,
            })
        else:
            power_data["error"] = "Energy monitoring not supported"
        
        return power_data
    
    def get_all_detailed_power_data(self) -> List[Dict]:
        """Get detailed power data for all outlets."""
        return self._run_async(self._async_get_all_detailed_power_data())
    
    async def _async_get_all_detailed_power_data(self) -> List[Dict]:
        """Async version of get_all_detailed_power_data."""
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        results = []
        for i in range(len(self.device.children)):
            try:
                power_data = await self._async_get_detailed_power_data(i)
                results.append(power_data)
            except Exception as e:
                results.append({
                    "outlet_id": i,
                    "error": str(e)
                })
        
        return results
    
    def monitor_power_usage(self, outlet_id: int, duration_seconds: int = 60, interval_seconds: int = 5) -> List[Dict]:
        """
        Monitor power usage for a specific outlet over time.
        
        Args:
            outlet_id: Outlet number (0-5)
            duration_seconds: Total monitoring duration in seconds
            interval_seconds: Sampling interval in seconds
            
        Returns:
            List of power readings over time
        """
        return self._run_async(self._async_monitor_power_usage(outlet_id, duration_seconds, interval_seconds))
    
    async def _async_monitor_power_usage(self, outlet_id: int, duration_seconds: int = 60, interval_seconds: int = 5) -> List[Dict]:
        """Async version of monitor_power_usage."""
        import time
        import datetime
        
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        if not 0 <= outlet_id < len(self.device.children):
            raise ValueError(f"Outlet ID must be between 0 and {len(self.device.children) - 1}")
        
        outlet = list(self.device.children)[outlet_id]
        readings = []
        
        print(f"Starting power monitoring for Outlet {outlet_id} ({outlet.alias})")
        print(f"Duration: {duration_seconds}s, Interval: {interval_seconds}s")
        print("=" * 50)
        
        start_time = time.time()
        reading_count = 0
        
        while (time.time() - start_time) < duration_seconds:
            try:
                await outlet.update()
                timestamp = datetime.datetime.now()
                
                reading = {
                    "reading_number": reading_count + 1,
                    "timestamp": timestamp.isoformat(),
                    "elapsed_seconds": round(time.time() - start_time, 1),
                    "outlet_id": outlet_id,
                    "alias": outlet.alias,
                    "is_on": outlet.is_on
                }
                
                # Get power data
                if hasattr(outlet, 'modules') and 'Energy' in outlet.modules:
                    energy_module = outlet.modules['Energy']
                    if hasattr(energy_module, 'current_consumption'):
                        reading.update({
                            "power_w": energy_module.current_consumption,
                            "voltage_v": getattr(energy_module, 'voltage', None),
                            "current_a": getattr(energy_module, 'current', None),
                        })
                elif hasattr(outlet, 'emeter_realtime') and outlet.has_emeter:
                    emeter = outlet.emeter_realtime
                    reading.update({
                        "power_w": emeter.power,
                        "voltage_v": emeter.voltage,
                        "current_a": emeter.current,
                    })
                else:
                    reading["error"] = "No energy monitoring available"
                
                readings.append(reading)
                reading_count += 1
                
                # Print real-time reading
                if "power_w" in reading:
                    print(f"Reading {reading_count}: {reading['power_w']:.1f}W, {reading['voltage_v']:.1f}V, {reading['current_a']:.3f}A at {timestamp.strftime('%H:%M:%S')}")
                else:
                    print(f"Reading {reading_count}: {reading.get('error', 'No data')} at {timestamp.strftime('%H:%M:%S')}")
                
                # Wait for next interval
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                error_reading = {
                    "reading_number": reading_count + 1,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "elapsed_seconds": round(time.time() - start_time, 1),
                    "outlet_id": outlet_id,
                    "error": str(e)
                }
                readings.append(error_reading)
                print(f"Reading {reading_count + 1}: Error - {e}")
                reading_count += 1
                await asyncio.sleep(interval_seconds)
        
        print("=" * 50)
        print(f"Monitoring completed. Collected {len(readings)} readings.")
        
        return readings
    
    def get_power_summary(self) -> Dict:
        """
        Get a comprehensive power summary for the entire power strip.
        
        Returns:
            Summary of power usage across all outlets
        """
        return self._run_async(self._async_get_power_summary())
    
    async def _async_get_power_summary(self) -> Dict:
        """Async version of get_power_summary."""
        import datetime
        
        await self._ensure_connected()
        
        # Get main device power data
        summary = {
            "device_alias": self.device.alias,
            "total_outlets": len(self.device.children) if hasattr(self.device, 'children') else 0,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        # Get device-level power if available
        if hasattr(self.device, 'modules') and 'Energy' in self.device.modules:
            energy_module = self.device.modules['Energy']
            if hasattr(energy_module, 'current_consumption'):
                summary["total_power_w"] = energy_module.current_consumption
                summary["total_voltage_v"] = getattr(energy_module, 'voltage', None)
                summary["total_current_a"] = getattr(energy_module, 'current', None)
        elif hasattr(self.device, 'emeter_realtime') and self.device.has_emeter:
            emeter = self.device.emeter_realtime
            summary.update({
                "total_power_w": emeter.power,
                "total_voltage_v": emeter.voltage,
                "total_current_a": emeter.current,
            })
        
        # Get individual outlet data
        outlet_data = await self._async_get_all_detailed_power_data()
        summary["outlets"] = outlet_data
        
        # Calculate statistics
        active_outlets = [o for o in outlet_data if o.get("is_on", False) and "error" not in o]
        summary["active_outlets_count"] = len(active_outlets)
        
        if active_outlets:
            total_outlet_power = sum(o.get("current_power_w", 0) for o in active_outlets)
            avg_voltage = sum(o.get("voltage_v", 0) for o in active_outlets if o.get("voltage_v")) / len(active_outlets)
            
            summary["calculated_total_power_w"] = total_outlet_power
            summary["average_voltage_v"] = round(avg_voltage, 1) if avg_voltage else None
        
        return summary
    
    def test_outlets(self, test_duration: int = 3) -> List[Dict]:
        """
        Test mode: Turn on each outlet sequentially for specified duration.
        
        Args:
            test_duration: Duration in seconds to keep each outlet on (default: 3)
            
        Returns:
            List of test results for each outlet
        """
        return self._run_async(self._async_test_outlets(test_duration))
    
    async def _async_test_outlets(self, test_duration: int = 3) -> List[Dict]:
        """Async version of test_outlets."""
        import time
        
        await self._ensure_connected()
        
        if not hasattr(self.device, 'children'):
            raise KasaPowerStripError("Device does not have child outlets")
        
        results = []
        outlet_count = len(self.device.children)
        
        print(f"Starting outlet test mode - {outlet_count} outlets, {test_duration} seconds each...")
        print("=" * 60)
        
        # First, turn off all outlets
        print("Turning off all outlets...")
        for i, outlet in enumerate(self.device.children):
            try:
                await outlet.turn_off()
                print(f"  Outlet {i} ({outlet.alias}): OFF")
            except Exception as e:
                print(f"  Outlet {i}: Failed to turn off - {e}")
        
        print("\nStarting sequential test...")
        time.sleep(1)  # Brief pause before starting test
        
        # Test each outlet sequentially
        for i, outlet in enumerate(self.device.children):
            start_time = time.time()
            try:
                print(f"\nTesting Outlet {i} ({outlet.alias})...")
                
                # Turn on the outlet
                await outlet.turn_on()
                print(f"  ✓ Turned ON at {time.strftime('%H:%M:%S')}")
                
                # Wait for specified duration
                for remaining in range(test_duration, 0, -1):
                    print(f"  Timer: {remaining} seconds remaining", end="\r")
                    time.sleep(1)
                
                # Turn off the outlet
                await outlet.turn_off()
                end_time = time.time()
                actual_duration = end_time - start_time
                
                print(f"\n  ✓ Turned OFF at {time.strftime('%H:%M:%S')}")
                print(f"  Duration: {actual_duration:.1f} seconds")
                
                results.append({
                    "outlet_id": i,
                    "alias": outlet.alias,
                    "success": True,
                    "duration": actual_duration,
                    "error": None
                })
                
            except Exception as e:
                print(f"  ✗ Error testing outlet {i}: {e}")
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


def main():
    """Example usage of the KasaPowerStrip class."""
    import sys
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
    else:
        command = "demo"
    
    # Check for specific commands
    test_mode = command == "test"
    power_mode = command == "power"
    monitor_mode = command == "monitor"
    summary_mode = command == "summary"
    
    test_duration = 3
    outlet_id = 0
    monitor_duration = 60
    monitor_interval = 5
    
    # Parse additional arguments
    if len(sys.argv) > 2:
        try:
            if test_mode:
                test_duration = int(sys.argv[2])
            elif power_mode:
                outlet_id = int(sys.argv[2])
            elif monitor_mode:
                outlet_id = int(sys.argv[2])
                if len(sys.argv) > 3:
                    monitor_duration = int(sys.argv[3])
                if len(sys.argv) > 4:
                    monitor_interval = int(sys.argv[4])
        except ValueError:
            print("Invalid arguments. Using defaults.")
    
    # Use your actual power strip IP address
    power_strip = KasaPowerStrip("10.0.0.188")
    
    try:
        # Connect to the device
        print("Connecting to power strip...")
        if not power_strip.connect():
            print("Failed to connect to power strip")
            return
        
        if test_mode:
            # Run test mode
            print(f"\n🧪 RUNNING TEST MODE - {test_duration} seconds per outlet")
            results = power_strip.test_outlets(test_duration)
            
            print("\n📊 Test Summary:")
            for result in results:
                status = "✅ PASS" if result["success"] else "❌ FAIL"
                if result["success"]:
                    print(f"  {status} Outlet {result['outlet_id']} ({result['alias']}): {result['duration']:.1f}s")
                else:
                    print(f"  {status} Outlet {result['outlet_id']} ({result['alias']}): {result['error']}")
                    
        elif power_mode:
            # Get detailed power data for specific outlet
            print(f"\n⚡ POWER DATA FOR OUTLET {outlet_id}")
            power_data = power_strip.get_detailed_power_data(outlet_id)
            print(json.dumps(power_data, indent=2))
            
        elif monitor_mode:
            # Monitor power usage over time
            print(f"\n📈 MONITORING OUTLET {outlet_id}")
            readings = power_strip.monitor_power_usage(outlet_id, monitor_duration, monitor_interval)
            
            print(f"\n📊 Monitoring Results Summary:")
            if readings:
                power_readings = [r for r in readings if "power_w" in r]
                if power_readings:
                    avg_power = sum(r["power_w"] for r in power_readings) / len(power_readings)
                    max_power = max(r["power_w"] for r in power_readings)
                    min_power = min(r["power_w"] for r in power_readings)
                    print(f"  Average Power: {avg_power:.2f}W")
                    print(f"  Maximum Power: {max_power:.2f}W")
                    print(f"  Minimum Power: {min_power:.2f}W")
                    print(f"  Total Readings: {len(power_readings)}")
                    
        elif summary_mode:
            # Get comprehensive power summary
            print(f"\n📋 POWER STRIP SUMMARY")
            summary = power_strip.get_power_summary()
            print(json.dumps(summary, indent=2))
            
        else:
            # Run normal demo mode
            # Get system information
            print("\n💡 System Info:")
            system_info = power_strip.get_system_info()
            print(json.dumps(system_info, indent=2))
            
            # Get status of all outlets
            print("\n🔌 All Outlet Status:")
            all_status = power_strip.get_all_outlet_status()
            for status in all_status:
                print(f"Outlet {status['outlet_id']}: {status['alias']} - {'ON' if status['is_on'] else 'OFF'}")
            
            # Get detailed power data for all outlets
            print("\n⚡ Detailed Power Data:")
            power_data = power_strip.get_all_detailed_power_data()
            for data in power_data:
                if "error" not in data:
                    print(f"Outlet {data['outlet_id']} ({data['alias']}): {data.get('current_power_w', 0)}W, {data.get('voltage_v', 0)}V, {data.get('current_a', 0)}A")
                    if data.get('energy_today_kwh'):
                        print(f"  Today: {data['energy_today_kwh']}kWh, Total: {data.get('energy_total_kwh', 0)}kWh")
                else:
                    print(f"Outlet {data['outlet_id']}: {data['error']}")
            
            # Example: Turn outlet 0 off and back on
            print(f"\n🔧 Testing outlet 0 control...")
            print("Turning off outlet 0...")
            power_strip.turn_off_outlet(0)
            
            print("Checking status...")
            status = power_strip.get_outlet_status(0)
            print(f"Outlet 0: {status['alias']} - {'ON' if status['is_on'] else 'OFF'}")
            
            print("Turning on outlet 0...")
            power_strip.turn_on_outlet(0)
            
            status = power_strip.get_outlet_status(0)
            print(f"Outlet 0: {status['alias']} - {'ON' if status['is_on'] else 'OFF'}")
        
    except KasaPowerStripError as e:
        print(f"Power strip error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        power_strip.disconnect()
    
    # Print usage help
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1].lower() == "help"):
        print("\n" + "="*60)
        print("USAGE EXAMPLES:")
        print("  python kasa_ctrl.py                    # Run demo mode")
        print("  python kasa_ctrl.py test [duration]    # Test mode (default: 3s per outlet)")
        print("  python kasa_ctrl.py power [outlet_id]  # Get detailed power data (default: outlet 0)")
        print("  python kasa_ctrl.py monitor [outlet_id] [duration] [interval]")
        print("                                          # Monitor power usage (default: outlet 0, 60s, 5s interval)")
        print("  python kasa_ctrl.py summary             # Get comprehensive power summary")
        print("  python kasa_ctrl.py help                # Show this help")
        print("="*60)


if __name__ == "__main__":
    main()