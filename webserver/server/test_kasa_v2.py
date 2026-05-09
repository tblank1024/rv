#!/usr/bin/env python3
"""
Test script to connect to HS300 using KlapTransportV2 directly.
This works around a python-kasa bug where IOT devices with new_klap=1
are incorrectly mapped to KlapTransport (v1) instead of KlapTransportV2.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("KASA_IP", "10.0.0.188")
USERNAME = os.getenv("KASA_USERNAME", "")
PASSWORD = os.getenv("KASA_PASSWORD", "")

async def main():
    from kasa import Credentials
    from kasa.iot import IotStrip
    from kasa.protocols import IotProtocol
    from kasa.transports.klaptransport import KlapTransportV2
    from kasa.deviceconfig import (
        DeviceConfig,
        DeviceConnectionParameters,
        DeviceEncryptionType,
        DeviceFamily,
    )

    creds = Credentials(USERNAME, PASSWORD)
    print(f"Connecting to {HOST} using KlapTransportV2 ...")

    conn_type = DeviceConnectionParameters(
        device_family=DeviceFamily.IotSmartPlugSwitch,
        encryption_type=DeviceEncryptionType.Klap,
    )
    config = DeviceConfig(host=HOST, credentials=creds, connection_type=conn_type)

    # Bypass device_factory: directly construct IotProtocol with KlapTransportV2
    transport = KlapTransportV2(config=config)
    protocol = IotProtocol(transport=transport)

    # Use IotStrip (HS300 is a power strip)
    device = IotStrip(host=HOST, protocol=protocol)

    try:
        await device.update()
        print(f"\nSUCCESS: Connected!")
        print(f"   Alias   : {device.alias}")
        print(f"   Model   : {device.model}")
        print(f"   Outlets : {len(device.children)}")
        print()
        for plug in device.children:
            state = "ON " if plug.is_on else "OFF"
            print(f"   [{state}] {plug.alias}")
    except Exception as e:
        print(f"\nFAILED: {e}")
    finally:
        await device.disconnect()

asyncio.run(main())
