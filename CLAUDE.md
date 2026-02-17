# Digital Key — Claude Code Instructions

## Project Overview

ESP32-S3 디지털 키 시스템. ECC P-256 챌린지-응답 인증 + BLE RSSI 근접 감지.

## Directory Structure

- `firmware/` — ESP-IDF project (ESP32-S3, NimBLE)
- `client/` — Python pip package (bleak + cryptography)

## Build

### Firmware

```bash
cd firmware
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

### Client

```bash
pip install -e client/
dk-client scan
```

## Conventions

### Firmware (C)

- Public API: `DkModule_FunctionName()` (PascalCase)
- Internal: `snake_case`
- Static variables: `s_` prefix
- Logging: `ESP_LOG*` with `static const char *TAG`
- Error returns: `esp_err_t`, logged with `esp_err_to_name()`

### Python

- Functions: `snake_case`
- Classes: `PascalCase`

## GATT Service

UUID: `12345678-1234-1234-1234-123456789abc`

| Chr | UUID suffix | Flags | Purpose |
|-----|------------|-------|---------|
| Auth State | 01 | R/N | Per-conn auth state |
| Challenge | 02 | R | 32-byte random (generated on read) |
| Response | 03 | W | key_id(16) + ECDSA sig |
| Provision | 04 | W | key_id(16) + pubkey(65) |
| Lock Cmd | 05 | W | 0=lock, 1=unlock |
| System Status | 06 | R/N | 8-byte packed status (200ms) |
| Key Mgmt | 07 | W | cmd(1) + key_id(16) |

## Key Files

| Module | Files |
|--------|-------|
| BLE stack | `components/ble_stack/` |
| Auth | `main/dk_auth.{c,h}` |
| GATT | `main/dk_service.{c,h}` |
| Keystore | `main/dk_keystore.{c,h}` |
| Proximity | `main/dk_proximity.{c,h}` |
| Lock | `main/dk_lock.{c,h}` |
| Client CLI | `client/dk_client/main.py` |
| Client BLE | `client/dk_client/ble.py` |
| Client crypto | `client/dk_client/crypto.py` |

## Reference Repos

- `~/repositories/firmware/v1` — NimBLE, NVS, component patterns
- `~/repositories/firmware/rvt-monitor` — bleak, pyproject.toml, CLI patterns
