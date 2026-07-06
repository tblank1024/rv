"""
Runtime monkey-patches for python-kasa bugs affecting HS300 with new_klap=1 firmware.

Bug: python-kasa maps IOT.SMARTPLUGSWITCH → IotPlug + KlapTransport (v1) regardless
     of login_version. HS300 with new_klap=1 requires KlapTransportV2 and IotStrip.

Fixed in: (not yet upstream as of python-kasa 0.10.2)

Import this module once before using KasaPowerStrip to apply the patches.
Patches survive pip upgrades since they are applied at runtime, not to library files.
"""

import logging

_log = logging.getLogger(__name__)
_patches_applied = False

# The patches below reach into python-kasa internals (device_factory._connect,
# transport classes). They are verified against exactly this version.
EXPECTED_KASA_VERSION = "0.10.2"


def _check_kasa_version():
    try:
        from importlib.metadata import version

        installed = version("python-kasa")
    except Exception:
        return
    if installed != EXPECTED_KASA_VERSION:
        _log.warning(
            "kasa_patches: python-kasa %s installed but patches were written for %s"
            " — HS300 patches may not apply correctly",
            installed,
            EXPECTED_KASA_VERSION,
        )


def apply():
    """Apply all patches. Safe to call multiple times."""
    global _patches_applied
    if _patches_applied:
        return

    _check_kasa_version()
    _patch_device_factory()
    _patches_applied = True
    _log.debug("kasa_patches: all patches applied")


def _patch_device_factory() -> None:
    """
    Patch 1: Use KlapTransportV2 for IOT.KLAP devices with login_version=2.
    Patch 2: Re-classify IotPlug → IotStrip when sysinfo reports children (HS300).
    """
    try:
        import kasa.device_factory as factory
        from kasa.iot import IotDevice, IotStrip
        from kasa.transports.klaptransport import KlapTransportV2

        if getattr(factory, "_hs300_patched", False):
            return  # Already applied (sitecustomize.py may have run first)

        _original_connect = factory._connect

        async def _patched_connect(config, protocol):
            from kasa.device_factory import get_device_class_from_sys_info
            from kasa.protocols import IotProtocol
            from kasa.transports import XorTransport

            ctype = config.connection_type

            # Patch 1: Use KlapTransportV2 for IOT.KLAP + login_version=2
            if (
                isinstance(protocol, IotProtocol)
                and not isinstance(protocol._transport, (XorTransport, KlapTransportV2))
                and ctype.login_version == 2
            ):
                protocol._transport = KlapTransportV2(config=config)

            device = await _original_connect(config, protocol)

            # Patch 2: Re-classify IotPlug → IotStrip when sysinfo has children (HS300)
            if (
                device is not None
                and isinstance(device, IotDevice)
                and not isinstance(device, IotStrip)
            ):
                try:
                    last = getattr(device, "_last_update", None)
                    if last:
                        corrected = get_device_class_from_sys_info(last)
                        if corrected is not type(device):
                            new_dev = corrected(host=config.host, protocol=protocol)
                            await new_dev.update()
                            device = new_dev
                except Exception:
                    pass

            return device

        _patched_connect._original = _original_connect
        factory._connect = _patched_connect
        factory._hs300_patched = True
        _log.debug("kasa_patches: device_factory._connect patched successfully")

    except Exception as exc:
        _log.warning("kasa_patches: failed to patch device_factory: %s", exc)
