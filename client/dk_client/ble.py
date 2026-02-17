"""BLE scan / connect / read / write / notify via bleak."""

import asyncio
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner

from .protocol import DEVICE_PREFIX

logger = logging.getLogger(__name__)


def _bluez_remove(address: str):
    """Remove device from BlueZ cache to ensure clean connection."""
    if sys.platform != "linux":
        return
    try:
        subprocess.run(
            ["bluetoothctl", "remove", address],
            capture_output=True, timeout=5,
        )
        logger.debug(f"bluez cache cleared for {address}")
    except Exception:
        pass


@dataclass
class ScannedDevice:
    name: str
    address: str
    rssi: int


async def scan(timeout: float = 5.0) -> list[ScannedDevice]:
    """Scan for DK-xxxx devices."""
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results: list[ScannedDevice] = []

    for address, (device, adv) in devices.items():
        name = device.name or adv.local_name or ""
        if not name.startswith(DEVICE_PREFIX):
            continue
        rssi = adv.rssi if adv.rssi else -100
        results.append(ScannedDevice(name=name, address=address, rssi=rssi))

    results.sort(key=lambda d: d.rssi, reverse=True)
    return results


class DkBleClient:
    """Wrapper around BleakClient for Digital Key operations."""

    def __init__(self, address: str):
        self.address = address
        self.client: Optional[BleakClient] = None

    async def connect(self) -> bool:
        self.client = BleakClient(self.address)
        try:
            await self.client.connect()
        except Exception as e:
            logger.warning(f"connect failed ({e}), clearing BlueZ cache and retrying...")
            _bluez_remove(self.address)
            self.client = BleakClient(self.address)
            try:
                await self.client.connect()
            except Exception as e2:
                logger.error(f"connect retry failed: {e2}")
                return False

        if self.client.is_connected:
            logger.info(f"connected to {self.address}")
            return True
        logger.error(f"not connected after connect() for {self.address}")
        return False

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            logger.info("disconnected")

    async def read(self, uuid: str) -> bytes:
        return await self.client.read_gatt_char(uuid)

    async def write(self, uuid: str, data: bytes):
        await self.client.write_gatt_char(uuid, data)

    async def subscribe(self, uuid: str, callback: Callable[[bytes], None]):
        def handler(sender, data: bytearray):
            callback(bytes(data))
        await self.client.start_notify(uuid, handler)

    async def unsubscribe(self, uuid: str):
        await self.client.stop_notify(uuid)

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.is_connected
