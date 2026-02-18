"""GATT UUID constants and status parsing."""

import struct
from dataclasses import dataclass

# Service UUID
DK_SERVICE_UUID = "12345678-1234-1234-1234-123456789abc"

# Characteristic UUIDs
# Firmware uses DK_CHR_UUID128(last_byte) which sets byte[15] of the LE
# representation. In UUID string form, byte[15] is the first two hex chars.
# Service:  12345678-1234-1234-1234-123456789abc
# Chr 0x01: 01345678-1234-1234-1234-123456789abc  (byte[15]=0x01)
_CHR_BASE = "345678-1234-1234-1234-123456789abc"
CHR_AUTH_STATE    = "01" + _CHR_BASE
CHR_CHALLENGE     = "02" + _CHR_BASE
CHR_RESPONSE      = "03" + _CHR_BASE
CHR_PROVISION     = "04" + _CHR_BASE
CHR_LOCK_CMD      = "05" + _CHR_BASE
CHR_SYSTEM_STATUS = "06" + _CHR_BASE
CHR_KEY_MGMT        = "07" + _CHR_BASE
CHR_DEVICE_PUBKEY   = "08" + _CHR_BASE
CHR_DEVICE_AUTH     = "09" + _CHR_BASE

# Device name prefix for scanning
DEVICE_PREFIX = "DK-"

# Auth states
AUTH_DISCONNECTED = 0
AUTH_CONNECTED    = 1
AUTH_CHALLENGE    = 2
AUTH_OK           = 3
AUTH_FAILED       = 4

AUTH_NAMES = {
    0: "disconnected",
    1: "connected",
    2: "challenge_sent",
    3: "authenticated",
    4: "failed",
}

# Zone levels
ZONE_NONE      = 0
ZONE_FAR       = 1
ZONE_NEAR      = 2
ZONE_IMMEDIATE = 3

ZONE_NAMES = {0: "none", 1: "far", 2: "near", 3: "immediate"}

# Lock states
LOCK_LOCKED   = 0
LOCK_UNLOCKED = 1

LOCK_NAMES = {0: "LOCKED", 1: "UNLOCKED"}

# Key management commands
KEY_MGMT_DELETE  = 0x01
KEY_MGMT_APPROVE = 0x02


@dataclass
class SystemStatus:
    auth_state: int
    zone_level: int
    rssi: int
    lock_state: int
    registered_keys: int
    pending_keys: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "SystemStatus":
        if len(data) < 6:
            raise ValueError(f"status too short: {len(data)} bytes")
        auth, zone, rssi, lock, reg, pend = struct.unpack("<BBbBBB", data[:6])
        return cls(auth, zone, rssi, lock, reg, pend)

    def display(self) -> str:
        return (
            f"Auth: {AUTH_NAMES.get(self.auth_state, '?'):<14} "
            f"Zone: {ZONE_NAMES.get(self.zone_level, '?'):<10} "
            f"RSSI: {self.rssi:>4} dBm  "
            f"Lock: {LOCK_NAMES.get(self.lock_state, '?'):<10} "
            f"Keys: {self.registered_keys} reg / {self.pending_keys} pending"
        )
