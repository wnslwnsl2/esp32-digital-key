# Digital Key System Architecture

## Overview

ESP32-S3 기반 디지털 키 시스템. CCC(Car Connectivity Consortium) Digital Key 표준의 핵심 구조를 구현한다.

## System Components

```
dk-server (OEM Backend)        dk-web (Mobile App)         ESP32 (Vehicle)
Port 8100                      Port 8000                   BLE GATT
┌──────────────────┐    HTTP   ┌─────────────────┐   BLE   ┌──────────────┐
│ Vehicle Registry │◄─────────│ WebSocket UI    │◄────────│ NimBLE Stack │
│ Key Binding      │  인가확인 │ BLE Control     │ Provisio│ ECC Auth     │
│ Event Log        │──────────►│ Status Monitor  │ Auth/Cmd│ NVS Keystore │
│ PIN Auth         │           │                 │────────►│ Lock Control │
└──────────────────┘           └─────────────────┘         └──────────────┘
```

| Component | Role | 실무 대응 |
|-----------|------|----------|
| `dk-server` | 차량 등록, 키 바인딩, 인가, 이벤트 로그 | OEM Backend (BMW Connected, Mercedes me 서버) |
| `dk-web` | BLE 연결, Provision, 인증, 잠금 제어 | Mobile App (스마트폰 앱) |
| ESP32 | BLE GATT 서비스, ECC 챌린지-응답 인증, NVS 키 저장 | Vehicle ECU (차량 내 디지털 키 모듈) |

## Core Principle

**서버가 권한의 원천(Source of Authority)**

- dk-server에 등록되지 않은 키는 차량에 provision 할 수 없다
- dk-web은 provision 전에 반드시 dk-server에 인가를 확인한다
- 차량(ESP32)은 유효한 키 요청이면 수동적으로 수락한다

## Flows

### 1. 신차 출고 (Initial Registration)

```
제조/딜러                dk-server              dk-web              ESP32
    │                       │                     │                   │
    ├─ 차량 등록 ──────────►│                     │                   │
    │  (이름, BLE 주소)     │                     │                   │
    │                       │                     │                   │
    ├─ 오너 키 바인딩 ─────►│                     │                   │
    │  (key_id + role)      │                     │                   │
    │                       │                     │                   │
    │                       │    ① Connect        │                   │
    │                       │◄────────────────────├──── BLE 연결 ────►│
    │                       │                     │                   │
    │                       │    ② 인가 확인       │                   │
    │                       │  "이 키가 이 차량에  │                   │
    │                       │   등록되어 있는가?"  │                   │
    │                       ├────── yes ─────────►│                   │
    │                       │                     │                   │
    │                       │                     ├── ③ Provision ──►│
    │                       │                     │  key_id + pubkey  │
    │                       │                     │                   │
    │                       │                     ├── ④ Auth ────────►│
    │                       │                     │  Challenge-Response│
    │                       │                     │  (ECC P-256)      │
    │                       │                     │                   │
    │                       │                     ├── ⑤ Unlock ─────►│
    │                       │                     │                   │
```

### 2. 중고차 인수 (Ownership Transfer)

```
이전 오너            딜러/dk-server           신규 오너/dk-web        ESP32
    │                     │                       │                   │
    ├── 소유권 이전 ─────►│                       │                   │
    │   (앱에서 양도)     │                       │                   │
    │                     │                       │                   │
    │                     ├── 기존 키 삭제        │                   │
    │                     ├── 신규 오너 키 바인딩  │                   │
    │                     │                       │                   │
    │                     │     Factory Reset      │                   │
    │                     │   (BOOT 버튼 3초)      │                   │
    │                     │                       │    ┌──────────┐   │
    │                     │                       │    │NVS 전삭제│   │
    │                     │                       │    │BLE 연결끊│   │
    │                     │                       │    │잠금 상태 │   │
    │                     │                       │    └──────────┘   │
    │                     │                       │                   │
    │                     │  ① Connect            │                   │
    │                     │◄──────────────────────├──── BLE 연결 ────►│
    │                     │  ② 인가 확인 → yes    │                   │
    │                     ├──────────────────────►├── ③ Provision ──►│
    │                     │                       │   (첫 키 = Owner) │
    │                     │                       ├── ④ Auth ────────►│
```

### 3. 일상 사용 (Daily Use)

```
dk-web                 ESP32
  │                      │
  ├── BLE Connect ──────►│
  ├── Challenge Read ◄───│  32-byte random
  ├── ECDSA Sign         │
  ├── Response Write ───►│  key_id + signature
  │                      ├── Verify (ECC P-256)
  │     Auth OK     ◄────│
  ├── Unlock Cmd ───────►│
  │                      ├── RSSI 근접 확인
  │     Unlocked    ◄────│
  │                      │
  │   (RSSI 감시 계속)    │
  │                      ├── RSSI < 임계값
  │     Auto-locked ◄────│  자동 잠금
```

## Authentication Protocol

ECC P-256 Challenge-Response:

1. ESP32가 32-byte random challenge 생성
2. 클라이언트가 개인키로 ECDSA-SHA256 서명
3. ESP32가 저장된 공개키로 서명 검증
4. 검증 성공 → AUTH_OK, 실패 → AUTH_FAILED

## GATT Service

UUID: `12345678-1234-1234-1234-123456789abc`

| Characteristic | UUID suffix | Flags | Purpose |
|----------------|------------|-------|---------|
| Auth State | 01 | R/N | 연결별 인증 상태 |
| Challenge | 02 | R | 32-byte random (읽을 때 생성) |
| Response | 03 | W | key_id(16) + ECDSA sig |
| Provision | 04 | W | key_id(16) + pubkey(65) |
| Lock Cmd | 05 | W | 0=lock, 1=unlock |
| System Status | 06 | R/N | 8-byte packed (200ms) |
| Key Mgmt | 07 | W | cmd(1) + key_id(16) |

## Factory Reset

GPIO 0 (BOOT 버튼) 3초 long press:

1. 모든 BLE 연결 종료
2. NVS 키스토어 전체 삭제
3. 잠금 상태 복원
4. LED 피드백 (노란색 → 파란색 → OFF)

## Security

| Layer | Mechanism |
|-------|-----------|
| 인증 | ECC P-256 Challenge-Response |
| 인가 | dk-server 키 바인딩 확인 후 provision 허용 |
| 근접 | BLE RSSI 기반 자동 잠금 |
| 관리 | dk-server PIN 인증 (SHA-256 + salt) |
| 리셋 | 물리 버튼 (BOOT 3초) — 원격 리셋 불가 |

## VIN (Vehicle Identification Number)

실무에서는 차대번호(17자리, 예: `KMHD041DBLU123456`)로 차량을 식별한다.
우리 시스템에서는 dk-server의 vehicle ID + BLE address가 이 역할을 한다.
