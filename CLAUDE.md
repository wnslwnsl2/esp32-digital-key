# Digital Key — Claude Code Instructions

## Project Overview

ESP32-S3 디지털 키 시스템. CCC Digital Key 표준의 핵심 구조를 구현한 프로토타입.

- ECC P-256 챌린지-응답 인증 (상호 인증)
- 클라우드 키 프로비저닝 (dk-server → WiFi → ESP32)
- BLE RSSI 근접 감지 + 자동 잠금
- 키 공유 (owner → family/guest)

## System Components

```
dk-server (:8100)           dk-web (:8000)             ESP32-S3 (Vehicle)
OEM Backend / 딜러 대시보드    사용자 Web UI                BLE + WiFi
┌──────────────────┐        ┌─────────────────┐        ┌──────────────────┐
│ 키 생성/관리      │  HTTP  │ Auto-scan       │  BLE   │ NimBLE GATT      │
│ 차량/계정 등록    │◄──────│ 챌린지-응답 인증  │◄──────│ ECC P-256 인증    │
│ PIN 인증         │───────►│ 키 공유 (owner)  │──────►│ NVS Keystore     │
│ 이벤트 로그       │        │ Passive Entry    │        │ WiFi 키 동기화    │
└──────────────────┘        └─────────────────┘        └──────────────────┘
```

## Directory Structure

- `firmware/` — ESP-IDF project (ESP32-S3, NimBLE, WiFi)
- `client/` — Python package (dk-web + dk-server)
- `docs/` — Architecture, process guide, production comparison

## Build & Run

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
dk-server          # OEM backend on :8100
dk-web             # User Web UI on :8000
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
| System Status | 06 | R/N | 8-byte packed status (200ms) |
| Key Mgmt | 07 | W | cmd(1) + key_id(16) |
| Device Pubkey | 08 | R | 65-byte uncompressed EC point |
| Device Auth | 09 | W/R | Challenge(32) write → Signature read |

## Key Files

### Firmware

| Module | Files |
|--------|-------|
| BLE stack | `components/ble_stack/` |
| Auth | `main/dk_auth.{c,h}` |
| GATT | `main/dk_service.{c,h}` |
| Keystore | `main/dk_keystore.{c,h}` |
| Proximity | `main/dk_proximity.{c,h}` |
| Lock | `main/dk_lock.{c,h}` |
| WiFi STA | `main/dk_wifi.{c,h}` |
| Cloud sync | `main/dk_cloud.{c,h}` |
| Button | `main/dk_button.{c,h}` |
| LED | `main/dk_led.{c,h}` |

### Client (Python)

| Module | Files |
|--------|-------|
| dk-web app | `server/app.py` |
| dk-server app | `server/reg_app.py` |
| Data store | `server/store.py` |
| WebSocket | `server/websocket.py` |
| Entry points | `server/__init__.py` |
| BLE client | `ble.py` |
| Crypto | `crypto.py` |

## Key Flows

1. **Setup**: dk-server에서 계정 생성 → 차량 등록 → owner 지정
2. **Cloud sync**: ESP32가 WiFi로 dk-server에서 public key 수신 + device pubkey 등록
3. **Connect**: dk-web 로그인 → auto-scan → BLE 연결 → 챌린지-응답 인증 → 상호 인증
4. **Share**: dk-web에서 owner가 다른 계정에 키 공유 → ESP32가 WiFi로 자동 수신

## Reference Repos

- `~/repositories/firmware/v1` — NimBLE, NVS, component patterns
- `~/repositories/firmware/rvt-monitor` — bleak, pyproject.toml, CLI patterns
