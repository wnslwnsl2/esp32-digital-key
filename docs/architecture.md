# Digital Key System Architecture

## Overview

ESP32-S3 기반 디지털 키 시스템. CCC(Car Connectivity Consortium) Digital Key 표준의 핵심 구조를 구현한다.

## System Components

```
dk-server (OEM Backend)        dk-web (Mobile App)         ESP32 (Vehicle)
Port 8100                      Port 8000                   BLE + WiFi
┌──────────────────┐    HTTP   ┌─────────────────┐   BLE   ┌──────────────┐
│ Vehicle Registry │◄─────────│ Auto-scan       │◄────────│ NimBLE Stack │
│ Key Generation   │  키/인증  │ Challenge-Resp  │ Auth/Cmd│ ECC Auth     │
│ Account/PIN Auth │──────────►│ Key Sharing     │────────►│ NVS Keystore │
│ Event Log        │           │ Passive Entry   │         │ WiFi Cloud   │
└──────────────────┘           └─────────────────┘         └──────────────┘
        │                                                         │
        │              WiFi HTTP (키 동기화)                        │
        └─────────────────────────────────────────────────────────┘
```

| Component | Role | 실무 대응 |
|-----------|------|----------|
| `dk-server` | 키 생성, 차량/계정 관리, 딜러 대시보드 | OEM Backend (BMW Connected, Mercedes me) |
| `dk-web` | BLE 연결, 인증, 잠금 제어, 키 공유 | Mobile App (스마트폰 앱) |
| ESP32 | BLE GATT 서비스, ECC 인증, WiFi 키 수신 | Vehicle ECU (디지털 키 모듈) |

## Core Principles

**서버가 권한의 원천(Source of Authority)**

- dk-server가 모든 키를 생성하고 관리한다
- ESP32는 WiFi로 서버에서 승인된 public key만 수신한다
- dk-web은 서버에서 private key를 다운로드하여 인증에 사용한다
- 키 공유/회수는 서버 통해 이루어지고, ESP32가 자동 동기화한다

**상호 인증(Mutual Authentication)**

- 클라이언트 → 차량: ECDSA 챌린지-응답으로 사용자 신원 증명
- 차량 → 클라이언트: device pubkey 검증으로 차량 신원 확인 (rogue device 방지)

## Flows

### 1. 초기 설정 (Initial Setup)

```
딜러                dk-server              ESP32
  │                     │                    │
  ├─ 계정 생성 ────────►│                    │
  │  (이름, PIN)        │                    │
  │                     │                    │
  ├─ 차량 등록 ────────►│                    │
  │  (이름, BLE 주소)   │                    │
  │                     │                    │
  ├─ Owner 지정 ───────►│                    │
  │  (계정 선택)        │                    │
  │                     │                    │
  │                     │  WiFi: device pubkey│
  │                     │◄───────────────────│  부팅 시 자동 등록
  │                     │                    │
  │                     │  WiFi: public keys  │
  │                     │───────────────────►│  30초 주기 동기화
```

### 2. 일상 사용 (Daily Use — Auto-scan)

```
dk-web                    dk-server                    ESP32
  │                          │                           │
  ├─ PIN 로그인 ────────────►│                           │
  │◄──── 계정 + 차량 목록 ───│                           │
  │                          │                           │
  │  Auto-scan 시작          │                           │
  │  (등록된 차량 BLE 주소 검색)                          │
  │ ─── BLE Scan ──────────────────────────────────────►│
  │                          │                           │
  │  차량 발견!              │                           │
  │                          │                           │
  │ ① BLE Connect ──────────────────────────────────────►│
  │                          │                           │
  │ ② Private key 다운로드   │                           │
  │ ────────────────────────►│                           │
  │◄──── PEM 응답 ──────────│                           │
  │                          │                           │
  │ ③ Challenge 읽기 ◄──────────────────────────────────│  32-byte random
  │    ECDSA 서명            │                           │
  │ ④ Response 쓰기 ────────────────────────────────────►│  key_id + sig
  │                          │                    검증 ✓ │
  │ ⑤ Auth OK ◄─────────────────────────────────────────│
  │                          │                           │
  │ ⑥ Device Auth            │                           │
  │    서버에서 device pubkey 확인                        │
  │    challenge 전송 ──────────────────────────────────►│
  │    서명 검증 ◄──────────────────────────────────────│
  │                          │                           │
  │ ⑦ Status Subscribe ─────────────────────────────────►│  200ms 주기
  │                          │                           │
  │                          │                    RSSI ◄─│  Passive Entry (자동 잠금/해제)
```

### 3. 키 공유 (Key Sharing)

```
Owner (dk-web)          dk-server              ESP32
  │                        │                     │
  ├─ Share 클릭            │                     │
  │  (계정, role 선택)     │                     │
  │                        │                     │
  ├─ POST /api/share ─────►│                     │
  │                        ├─ 새 키페어 생성      │
  │                        │                     │
  │                        │  WiFi: 새 pubkey     │
  │                        │────────────────────►│  다음 폴링에서 수신
  │                        │                     │
  │                        │                     │
공유 대상 (dk-web)         │                     │
  │                        │                     │
  ├─ PIN 로그인 ──────────►│                     │
  │◄── 공유된 차량 목록 ───│                     │
  │                        │                     │
  ├─ Auto-scan → BLE 연결 → 인증 성공            │
```

### 4. 키 회수

```
딜러/Owner              dk-server              ESP32
  │                        │                     │
  ├─ 키 삭제 (✕ 버튼) ───►│                     │
  │                        ├─ 키 제거            │
  │                        │                     │
  │                        │  WiFi: 변경된 목록   │
  │                        │────────────────────►│  다음 폴링에서 감지
  │                        │                     │
공유 대상:                  │                     │
  인증 시도 → public key 없음 → AUTH_FAILED       │
```

### 5. 중고차 인수 (Ownership Transfer)

```
이전 오너            딜러/dk-server              ESP32
  │                     │                         │
  ├── 소유권 이전 ─────►│                         │
  │                     ├── 기존 키 전체 삭제      │
  │                     ├── 새 Owner 지정          │
  │                     │                         │
  │                     │  Factory Reset           │
  │                     │  (BOOT 버튼 3초)         │
  │                     │                    ┌────┤
  │                     │                    │NVS │
  │                     │                    │전삭│
  │                     │                    │제  │
  │                     │                    └────┤
  │                     │                         │
  │                     │  WiFi: 새 owner pubkey   │
  │                     │────────────────────────►│
```

## Authentication Protocol

### Client → Vehicle (챌린지-응답)

1. ESP32가 32-byte random challenge 생성
2. dk-web이 dk-server에서 받은 private key로 ECDSA-SHA256 서명
3. ESP32가 NVS에 저장된 public key로 서명 검증
4. 검증 성공 → AUTH_OK, 실패 → AUTH_FAILED

### Vehicle → Client (상호 인증)

1. dk-web이 dk-server에서 등록된 device pubkey 조회
2. ESP32의 BLE device pubkey와 비교 (hex 매칭)
3. dk-web이 32-byte challenge 전송
4. ESP32가 device private key로 서명 → dk-web이 검증
5. 불일치 시 "possible rogue device" 경고

## GATT Service

UUID: `12345678-1234-1234-1234-123456789abc`

| Characteristic | UUID suffix | Flags | Purpose |
|----------------|------------|-------|---------|
| Auth State | 01 | R/N | 연결별 인증 상태 |
| Challenge | 02 | R | 32-byte random (읽을 때 생성) |
| Response | 03 | W | key_id(16) + ECDSA sig |
| System Status | 06 | R/N | 8-byte packed (200ms) |
| Key Mgmt | 07 | W | cmd(1) + key_id(16) |
| Device Pubkey | 08 | R | 65-byte uncompressed EC point |
| Device Auth | 09 | W/R | Challenge(32) write → Signature read |

## ESP32 Boot Sequence

```c
app_main()
├── NVS 초기화
├── DkAuth_Init()           // ECC device keypair 생성/로드
├── DkKeystore_Init()       // NVS에서 기존 키 로드
├── DkLock_Init()
├── DkLed_Init()
├── DkWifi_Init()           // WiFi STA 연결 (SSID 비면 skip)
├── DkCloud_Init()          // device pubkey 등록 + 키 동기화 task
├── BleStack_Init()         // BLE 광고 시작 "DK-XXXX"
├── DkProximity_Init()      // RSSI 감시
├── DkService_StartStatusTimer()  // 200ms 상태 알림
└── DkButton_Init()         // BOOT 3초 → factory reset
```

## Factory Reset

GPIO 0 (BOOT 버튼) 3초 long press:

1. 모든 BLE 연결 종료
2. NVS 키스토어 전체 삭제
3. 잠금 상태 복원
4. LED 피드백 (노란색 → 파란색 → OFF)

## Security

| Layer | Mechanism |
|-------|-----------|
| 사용자 인증 | ECC P-256 Challenge-Response (ECDSA-SHA256) |
| 차량 인증 | Device pubkey 검증 + 챌린지-응답 (상호 인증) |
| 키 관리 | dk-server 중앙 생성/관리, WiFi로 ESP32에 배포 |
| 근접 | BLE RSSI Passive Entry (자동 잠금/해제) |
| 계정 | PIN 인증 (SHA-256 + salt) |
| 리셋 | 물리 버튼 (BOOT 3초) — 원격 리셋 불가 |

## Network

```
같은 2.4GHz WiFi 네트워크
┌──────────────────────────────────────────┐
│   dk-server        dk-web       ESP32    │
│   :8100            :8000        WiFi+BLE │
│                                          │
│   mDNS: dk-server.local                  │
└──────────────────────────────────────────┘
```

- dk-server가 mDNS로 `dk-server.local` 광고
- ESP32는 mDNS로 서버 주소 자동 해석 (IP 하드코딩 불필요)
- ESP32-S3는 **2.4GHz WiFi만** 지원
