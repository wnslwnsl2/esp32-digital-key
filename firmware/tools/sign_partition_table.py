#!/usr/bin/env python3
"""
Sign partition table for ESP32-S3 Secure Boot V2
This script pads and signs the partition table binary for secure boot.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def pad_binary(input_file, output_file, block_size=4096):
    """Pad binary file to block size alignment"""
    with open(input_file, "rb") as f:
        data = f.read()

    current_size = len(data)
    if current_size % block_size == 0:
        print(f"✓ Already aligned to {block_size} bytes")
        padded = data
    else:
        padding_size = block_size - (current_size % block_size)
        padded = data + b"\xff" * padding_size
        print(f"✓ Padded from {current_size} to {len(padded)} bytes")

    with open(output_file, "wb") as f:
        f.write(padded)

    return len(padded)


def sign_binary(input_file, output_file, key_file):
    """Sign binary with secure boot key"""
    cmd = [
        sys.executable,
        "-m",
        "espsecure",
        "sign_data",
        "--version",
        "2",
        "--keyfile",
        str(key_file),
        "--output",
        str(output_file),
        str(input_file),
    ]

    print(f"Signing: {input_file}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Signing failed: {result.stderr}")
        return False

    print(f"✓ Signed: {output_file}")
    return True


def verify_signature(signed_file, key_file):
    """Verify signature of signed binary"""
    cmd = [
        sys.executable,
        "-m",
        "espsecure",
        "verify_signature",
        "--version",
        "2",
        "--keyfile",
        str(key_file),
        str(signed_file),
    ]

    print(f"Verifying: {signed_file}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Verification failed: {result.stderr}")
        return False

    print(f"✓ Signature verified")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Sign partition table for ESP32-S3 Secure Boot V2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Sign partition table in current project
  python sign_partition_table.py

  # Sign specific partition table
  python sign_partition_table.py --input custom_partitions.bin

  # Use specific key
  python sign_partition_table.py --key keys/my_key.pem
        """,
    )

    parser.add_argument(
        "--input",
        "-i",
        default="build/partition_table/partition-table.bin",
        help="Input partition table binary (default: build/partition_table/partition-table.bin)",
    )

    parser.add_argument(
        "--key",
        "-k",
        default="keys/secure_boot_signing_key.pem",
        help="Secure boot signing key (default: keys/secure_boot_signing_key.pem)",
    )

    parser.add_argument(
        "--output-dir",
        "-o",
        default="build/partition_table",
        help="Output directory (default: build/partition_table)",
    )

    parser.add_argument(
        "--skip-verify", action="store_true", help="Skip signature verification"
    )

    args = parser.parse_args()

    # Convert paths
    input_file = Path(args.input)
    key_file = Path(args.key)
    output_dir = Path(args.output_dir)

    # Check input files
    if not input_file.exists():
        print(f"❌ Input file not found: {input_file}")
        return 1

    if not key_file.exists():
        print(f"❌ Key file not found: {key_file}")
        return 1

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Define output files
    padded_file = output_dir / "partition-table-padded.bin"
    # Overwrite original partition-table.bin with signed version
    signed_file = output_dir / "partition-table.bin"  # Overwrite original!

    print("=" * 60)
    print("ESP32-S3 Partition Table Signing Tool")
    print("=" * 60)
    print(f"Input:  {input_file}")
    print(f"Key:    {key_file}")
    print(f"Output: {signed_file}")
    print("-" * 60)

    # Step 1: Pad the partition table
    print("\n1. Padding partition table...")
    padded_size = pad_binary(input_file, padded_file)

    # Step 2: Sign the padded partition table
    print("\n2. Signing partition table...")
    if not sign_binary(padded_file, signed_file, key_file):
        return 1

    # Step 3: Verify the signature
    if not args.skip_verify:
        print("\n3. Verifying signature...")
        if not verify_signature(signed_file, key_file):
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
