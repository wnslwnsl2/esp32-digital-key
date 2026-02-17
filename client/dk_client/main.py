"""CLI entry point for dk-client."""

import argparse
import asyncio
import sys

from .ble import DkBleClient, scan
from .crypto import load_or_create_key, get_public_key_bytes, sign_challenge
from .protocol import (
    CHR_AUTH_STATE,
    CHR_CHALLENGE,
    CHR_KEY_MGMT,
    CHR_LOCK_CMD,
    CHR_PROVISION,
    CHR_RESPONSE,
    CHR_SYSTEM_STATUS,
    KEY_MGMT_APPROVE,
    KEY_MGMT_DELETE,
    SystemStatus,
)


async def cmd_scan(args):
    print("Scanning for DK devices...")
    devices = await scan(timeout=args.timeout)
    if not devices:
        print("No devices found.")
        return
    for d in devices:
        print(f"  {d.name}  {d.address}  RSSI={d.rssi}")


async def cmd_provision(args):
    key_id, pk = load_or_create_key()
    pubkey = get_public_key_bytes(pk)

    client = DkBleClient(args.addr)
    await client.connect()

    # key_id(16 bytes, left-padded with null) + pubkey(65 bytes)
    key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
    data = key_id_bytes + pubkey
    await client.write(CHR_PROVISION, data)
    print(f"Provisioned key: {key_id}")

    await client.disconnect()


async def cmd_auth(args):
    key_id, pk = load_or_create_key()

    client = DkBleClient(args.addr)
    await client.connect()

    # Read challenge
    challenge = await client.read(CHR_CHALLENGE)
    print(f"Challenge: {challenge.hex()[:16]}...")

    # Sign
    sig = sign_challenge(pk, challenge)

    # Write response: key_id(16) + sig
    key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
    await client.write(CHR_RESPONSE, key_id_bytes + sig)

    # Read auth state
    state = await client.read(CHR_AUTH_STATE)
    print(f"Auth state: {state[0]}")

    await client.disconnect()


async def cmd_unlock(args):
    client = DkBleClient(args.addr)
    await client.connect()

    await client.write(CHR_LOCK_CMD, bytes([0x01]))
    print("Unlock command sent.")

    await client.disconnect()


async def cmd_lock(args):
    client = DkBleClient(args.addr)
    await client.connect()

    await client.write(CHR_LOCK_CMD, bytes([0x00]))
    print("Lock command sent.")

    await client.disconnect()


async def cmd_status(args):
    client = DkBleClient(args.addr)
    await client.connect()

    print("Monitoring status (Ctrl+C to stop)...")

    def on_status(data: bytes):
        st = SystemStatus.from_bytes(data)
        # Clear line and print
        print(f"\r{st.display()}", end="", flush=True)

    await client.subscribe(CHR_SYSTEM_STATUS, on_status)

    try:
        while client.connected:
            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        print()
        await client.disconnect()


async def cmd_approve(args):
    key_id, pk = load_or_create_key()

    client = DkBleClient(args.addr)
    await client.connect()

    # First authenticate as owner
    challenge = await client.read(CHR_CHALLENGE)
    sig = sign_challenge(pk, challenge)
    key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
    await client.write(CHR_RESPONSE, key_id_bytes + sig)

    state = await client.read(CHR_AUTH_STATE)
    if state[0] != 3:
        print(f"Auth failed (state={state[0]}). Only owner can approve.")
        await client.disconnect()
        return

    # Approve the pending key
    target_id = args.key_id.encode("ascii").ljust(16, b"\x00")[:16]
    await client.write(CHR_KEY_MGMT, bytes([KEY_MGMT_APPROVE]) + target_id)
    print(f"Approved key: {args.key_id}")

    await client.disconnect()


async def cmd_delete(args):
    key_id, pk = load_or_create_key()

    client = DkBleClient(args.addr)
    await client.connect()

    # Authenticate as owner
    challenge = await client.read(CHR_CHALLENGE)
    sig = sign_challenge(pk, challenge)
    key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
    await client.write(CHR_RESPONSE, key_id_bytes + sig)

    state = await client.read(CHR_AUTH_STATE)
    if state[0] != 3:
        print(f"Auth failed (state={state[0]}). Only owner can delete.")
        await client.disconnect()
        return

    # Delete key
    target_id = args.key_id.encode("ascii").ljust(16, b"\x00")[:16]
    await client.write(CHR_KEY_MGMT, bytes([KEY_MGMT_DELETE]) + target_id)
    print(f"Deleted key: {args.key_id}")

    await client.disconnect()


def main():
    parser = argparse.ArgumentParser(prog="dk-client",
                                     description="ESP32 Digital Key Client")
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Scan for DK devices")
    p_scan.add_argument("--timeout", type=float, default=5.0)

    # provision
    p_prov = sub.add_parser("provision", help="Register key with device")
    p_prov.add_argument("addr", help="Device BLE address")

    # auth
    p_auth = sub.add_parser("auth", help="Challenge-response authentication")
    p_auth.add_argument("addr", help="Device BLE address")

    # unlock
    p_unlock = sub.add_parser("unlock", help="Unlock")
    p_unlock.add_argument("addr", help="Device BLE address")

    # lock
    p_lock = sub.add_parser("lock", help="Lock")
    p_lock.add_argument("addr", help="Device BLE address")

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
        "provision": cmd_provision,
        "auth": cmd_auth,
        "unlock": cmd_unlock,
        "lock": cmd_lock,
        "status": cmd_status,
        "approve": cmd_approve,
        "delete": cmd_delete,
    }

    asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    main()
