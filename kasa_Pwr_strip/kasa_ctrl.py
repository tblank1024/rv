# Modern Kasa Smart Plug Power Strip HS300 controller CLI interface
# This module provides a command-line interface for the KasaPowerStrip class.

import asyncio
import json
import sys
from kasa_power_strip import KasaPowerStrip, KasaPowerStripError


def main():
    """Example usage of the KasaPowerStrip class."""
    # Run the main async function
    asyncio.run(async_main())


async def async_main():
    """Async main function to handle all operations."""
    # Parse command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
    else:
        command = "test"  # Default command
    
    outlet_id = 0  # Default outlet
    test_duration = 3  # Default test duration
    ip_address = None
    
    # Parse additional arguments
    discover_mode = command == "discover"
    test_mode = command == "test"
    power_mode = command == "power"
    monitor_mode = command == "monitor"
    status_mode = command == "status"
    
    # Parse outlet_id and ip_address if provided
    try:
        if len(sys.argv) > 2:
            if test_mode:
                test_duration = int(sys.argv[2])
            else:
                outlet_id = int(sys.argv[2])
        if len(sys.argv) > 3:
            if sys.argv[3].count('.') == 3:
                ip_address = sys.argv[3]
        if len(sys.argv) > 4:
            if test_mode and sys.argv[3].count('.') == 3:
                ip_address = sys.argv[3]
            elif test_mode:
                if sys.argv[2].count('.') == 3:
                    ip_address = sys.argv[2]
    except ValueError:
        print("Invalid arguments. Using defaults.")
    
    # Handle discovery mode
    if discover_mode:
        print("Discovering Kasa devices on the network...")
        print("This may take a few seconds...\n")
        
        try:
            power_strips = await KasaPowerStrip.discover_power_strips()
            
            if not power_strips:
                print("No power strips found on any network")
                print("\nTroubleshooting:")
                print("  - Ensure power strip is connected to WiFi")
                print("  - Check you're on the same network")
                print("  - Verify 'Third Party Compatibility' is enabled")
            else:
                print(f"Found {len(power_strips)} power strip(s):")
                for i, strip in enumerate(power_strips, 1):
                    network_info = f" (on {strip.get('interface', 'unknown')})" if 'interface' in strip else ""
                    print(f"\n{i}. {strip['alias']}{network_info}")
                    print(f"   IP: {strip['ip']}")
                    print(f"   Model: {strip['model']}")
                    print(f"   MAC: {strip['mac']}")
                    print(f"   Outlets: {strip['children_count']}")
                    if strip.get('rssi'):
                        print(f"   Signal: {strip['rssi']} dBm")
                    if 'network' in strip:
                        print(f"   Network: {strip['network']}")
                
                print(f"\nTo use auto-connect with selection:")
                print(f"   python3 kasa_ctrl.py test")
                print(f"   # OR specify IP explicitly:")
                print(f"   python3 kasa_ctrl.py test 3 {power_strips[0]['ip']}")
        
        except Exception as e:
            print(f"Discovery failed: {e}")
        
        return
    
    # Set up power strip connection
    if ip_address:
        power_strip = KasaPowerStrip(ip_address)
        print(f"Using specified IP: {ip_address}")
        # Connect to the device
        print("Connecting to power strip...")
        if not await power_strip._async_connect():
            print("Failed to connect to power strip")
            return
    else:
        print("No IP specified, scanning all networks for power strips...")
        
        # Run auto-connect in async context
        try:
            power_strip = await KasaPowerStrip.auto_connect()
            if power_strip is None:
                print("No power strip selected or connection failed")
                return
        except Exception as e:
            print(f"Auto-discovery error: {e}")
            return
    
    try:
        if test_mode:
            # Run test mode
            print(f"\nRUNNING TEST MODE - {test_duration} seconds per outlet")
            results = await power_strip._async_test_outlets(test_duration)
            
            print("\nTest Summary:")
            for result in results:
                status = "PASS" if result["success"] else "FAIL"
                if result["success"]:
                    print(f"  {status} Outlet {result['outlet_id']} ({result['alias']}): {result['duration']:.1f}s")
                else:
                    print(f"  {status} Outlet {result['outlet_id']} ({result['alias']}): {result['error']}")
                    
        elif power_mode:
            # Get detailed power data for specific outlet
            print(f"\nPOWER DATA FOR OUTLET {outlet_id}")
            power_data = power_strip.get_detailed_power_data(outlet_id)
            print(json.dumps(power_data, indent=2))
            
        elif monitor_mode:
            # Monitor power usage over time
            print(f"\nMONITORING OUTLET {outlet_id}")
            readings = await power_strip.monitor_outlet(outlet_id, duration=30)
            
            print(f"\nMonitoring Results Summary:")
            for timestamp, data in readings.items():
                print(f"  {timestamp}: {data['power_mw']} mW, {data['current_ma']} mA")
                    
        elif status_mode:
            # Get comprehensive status
            await power_strip._ensure_connected()  # Make sure properties are loaded
            print(f"\nConnected to: {power_strip.host}")
            print(f"Device: {power_strip.device.alias}")
            print(f"Model: {power_strip.device.model}")
            print(f"Firmware: {getattr(power_strip.device, 'fw_ver', getattr(power_strip.device, 'firmware_version', 'N/A'))}")
            print(f"Hardware: {getattr(power_strip.device, 'hw_ver', getattr(power_strip.device, 'hardware_version', 'N/A'))}")
            print(f"MAC: {power_strip.device.mac}")
            
            print(f"\nPOWER STRIP SUMMARY")
            print(f"Total Outlets: {len(power_strip.device.children)}")
            print(f"Switches On: {sum(1 for c in power_strip.device.children if c.is_on)}")
            print(f"Total Power: {sum(c.current_consumption for c in power_strip.device.children):.1f} W")
            print(f"Signal Strength: {power_strip.device.rssi} dBm")
            
            print("\nSystem Info:")
            print(f"  Uptime: {getattr(power_strip.device, 'on_time', 'N/A')} seconds")
            print(f"  Latitude: {getattr(power_strip.device, 'latitude', 'N/A')}")
            print(f"  Longitude: {getattr(power_strip.device, 'longitude', 'N/A')}")
            
            print("\nAll Outlet Status:")
            for i, outlet in enumerate(power_strip.device.children):
                status = "ON" if outlet.is_on else "OFF"
                print(f"  {outlet.alias}: {status}")
                power = getattr(outlet, 'current_consumption', getattr(outlet, 'power', 0))
                current = getattr(outlet, 'current', 0)
                energy_today = getattr(outlet, 'energy_today', 0)
                energy_total = getattr(outlet, 'energy_total', 0)
                print(f"    Power: {power:.1f} W | Current: {current:.0f} mA")
                print(f"    Today: {energy_today:.3f} kWh | Total: {energy_total:.3f} kWh")
            
            print("\nDetailed Power Data:")
            for i, outlet in enumerate(power_strip.device.children):
                if hasattr(outlet, 'realtime'):
                    realtime = outlet.realtime
                    print(f"\n  {outlet.alias} (Outlet {i}):")
                    print(f"    Voltage: {realtime.voltage:.1f} V | Current: {realtime.current:.0f} mA")
                    print(f"    Power: {realtime.power:.1f} W | Total: {realtime.total:.3f} kWh")
                else:
                    print(f"\n  {outlet.alias} (Outlet {i}): Detailed data not available")
                
        else:
            # Simple control mode
            print(f"\nTesting outlet 0 control...")
            await power_strip.turn_on_outlet(0)
            print("Outlet 0 turned ON")
            
            await asyncio.sleep(2)
            
            await power_strip.turn_off_outlet(0)
            print("Outlet 0 turned OFF")
            
    except Exception as e:
        print(f"Error: {e}")
        return


if __name__ == "__main__":
    main()
