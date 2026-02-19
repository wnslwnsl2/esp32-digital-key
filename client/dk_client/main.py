"""CLI entry point for dk-client."""

import argparse
import asyncio
import sys

from .ble import DkBleClient, scan
from .crypto import load_or_create_key, get_public_key_bytes, sign_challenge
from .protocol import (
    AUTH_NAMES,
    AUTH_OK,
    CHR_AUTH_STATE,
    CHR_CHALLENGE,
    CHR_KEY_MGMT,
    CHR_RESPONSE,
    CHR_SYSTEM_STATUS,
    KEY_MGMT_APPROVE,
    KEY_MGMT_DELETE,
    LOCK_NAMES,
    ZONE_NAMES,
    SystemStatus,
)


def _header(title: str):
    print(f"\n── {title} " + "─" * max(1, 44 - len(title)))


def _info(label: str, value: str):
    print(f"   {label + ':':<14} {value}")


def _ok(msg: str):
    print(f"   ✓ {msg}")


def _fail(msg: str):
    print(f"   ✗ {msg}")


def _show_key(key_id: str, pk):
    """Display loaded key info."""
    from pathlib import Path
    _header("Key")
    pem_path = Path.home() / ".dk-client" / f"{key_id}.pem"
    _info("Key ID", key_id)
    _info("Key file", str(pem_path))
    pubkey = get_public_key_bytes(pk)
    _info("Public key", f"{pubkey[:4].hex()}...{pubkey[-4:].hex()} ({len(pubkey)} bytes)")


async def _connect(client: DkBleClient):
    """Connect with progress display."""
    _header("Connect")
    print(f"   Connecting to {client.address}...")
    ok = await client.connect()
    if not ok:
        _fail("Connection failed")
        sys.exit(1)
    _ok("Connected")


async def _disconnect(client: DkBleClient):
    _header("Disconnect")
    await client.disconnect()
    _ok("Disconnected")
    print()


async def _authenticate(client: DkBleClient, key_id: str, pk) -> bool:
    """Perform challenge-response auth with progress display.

    Returns True if authenticated.
    """
    _header("Challenge")
    print("   Reading challenge from device...")
    challenge = await client.read(CHR_CHALLENGE)
    _info("Challenge", f"{challenge.hex()} ({len(challenge)} bytes)")

    _header("Sign")
    print("   Signing with ECDSA-SHA256...")
    sig = sign_challenge(pk, challenge)
    _info("Signature", f"{sig[:8].hex()}... ({len(sig)} bytes DER)")

    _header("Authenticate")
    key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
    payload = key_id_bytes + sig
    _info("Payload", f"key_id({len(key_id_bytes)}) + sig({len(sig)}) = {len(payload)} bytes")
    print("   Writing response...")
    await client.write(CHR_RESPONSE, payload)

    state = await client.read(CHR_AUTH_STATE)
    state_val = state[0]
    state_name = AUTH_NAMES.get(state_val, f"unknown({state_val})")
    if state_val == AUTH_OK:
        _ok(f"Auth state: {state_name}")
        return True
    else:
        _fail(f"Auth state: {state_name}")
        return False


# ── Commands ─────────────────────────────────────────────


async def cmd_scan(args):
    print(f"Scanning for DK devices ({args.timeout}s)...")
    devices = await scan(timeout=args.timeout)
    if not devices:
        print("No devices found.")
        return
    print(f"\nFound {len(devices)} device(s):\n")
    for d in devices:
        print(f"  {d.name:<12} {d.address}   RSSI: {d.rssi} dBm")
    print()


async def cmd_auth(args):
    key_id, pk = load_or_create_key()
    _show_key(key_id, pk)

    client = DkBleClient(args.addr)
    await _connect(client)
    await _authenticate(client, key_id, pk)
    await _disconnect(client)


async def cmd_status(args):
    key_id, pk = load_or_create_key()
    _show_key(key_id, pk)

    client = DkBleClient(args.addr)
    await _connect(client)

    ok = await _authenticate(client, key_id, pk)
    if not ok:
        await _disconnect(client)
        return

    _header("Status Monitor")
    print("   Subscribing to system status notifications...")

    first = True

    def on_status(data: bytes):
        nonlocal first
        st = SystemStatus.from_bytes(data)
        if first:
            _ok("Subscribed — streaming (Ctrl+C to stop)\n")
            # Print column header
            print(
                f"   {'Auth':<14} {'Zone':<10} {'RSSI':>8}   "
                f"{'Lock':<10} {'Keys':>12}"
            )
            print("   " + "─" * 58)
            first = False

        auth = AUTH_NAMES.get(st.auth_state, "?")
        zone = ZONE_NAMES.get(st.zone_level, "?")
        lock = LOCK_NAMES.get(st.lock_state, "?")
        keys = f"{st.registered_keys} reg / {st.pending_keys} pend"
        print(
            f"\r   {auth:<14} {zone:<10} {st.rssi:>5} dBm   "
            f"{lock:<10} {keys:>12}",
            end="", flush=True,
        )

    await client.subscribe(CHR_SYSTEM_STATUS, on_status)

    try:
        while client.connected:
            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        print()
        await _disconnect(client)


async def cmd_approve(args):
    key_id, pk = load_or_create_key()
    _show_key(key_id, pk)

    client = DkBleClient(args.addr)
    await _connect(client)

    ok = await _authenticate(client, key_id, pk)
    if not ok:
        _fail("Only owner can approve keys")
        await _disconnect(client)
        return

    _header("Approve Key")
    _info("Target key", args.key_id)
    target_id = args.key_id.encode("ascii").ljust(16, b"\x00")[:16]
    print("   Writing approve command...")
    await client.write(CHR_KEY_MGMT, bytes([KEY_MGMT_APPROVE]) + target_id)
    _ok(f"Key approved: {args.key_id}")

    await _disconnect(client)


async def cmd_delete(args):
    key_id, pk = load_or_create_key()
    _show_key(key_id, pk)

    client = DkBleClient(args.addr)
    await _connect(client)

    ok = await _authenticate(client, key_id, pk)
    if not ok:
        _fail("Only owner can delete keys")
        await _disconnect(client)
        return

    _header("Delete Key")
    _info("Target key", args.key_id)
    target_id = args.key_id.encode("ascii").ljust(16, b"\x00")[:16]
    print("   Writing delete command...")
    await client.write(CHR_KEY_MGMT, bytes([KEY_MGMT_DELETE]) + target_id)
    _ok(f"Key deleted: {args.key_id}")

    await _disconnect(client)


def main():
    parser = argparse.ArgumentParser(prog="dk-client",
                                     description="ESP32 Digital Key Client")
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Scan for DK devices")
    p_scan.add_argument("--timeout", type=float, default=5.0)

    # auth
    p_auth = sub.add_parser("auth", help="Challenge-response authentication")
    p_auth.add_argument("addr", help="Device BLE address")

    # status
    p_status = sub.add_parser("status", help="Monitor system status")
    p_status.add_argument("addr", help="Device BLE address")

    # approve
    p_approve = sub.add_parser("approve", help="Approve pending key (owner)")
    p_approve.add_argument("addr", help="Device BLE address")
    p_approve.add_argument("key_id", help="Key ID to approve")

    # delete
    p_delete = sub.add_parser("delete", help="Delete key (owner)")
    p_delete.add_argument("addr", help="Device BLE address")
    p_delete.add_argument("key_id", help="Key ID to delete")

    args = parser.parse_args()

    handlers = {
        "scan": cmd_scan,
        "auth": cmd_auth,
        "status": cmd_status,
        "approve": cmd_approve,
        "delete": cmd_delete,
    }

    asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    main()
