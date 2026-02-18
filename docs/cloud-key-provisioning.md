# Digital Key — 설정 및 사용 가이드

## 1. 시스템 시작

### 1-1. dk-server 시작

```bash
dk-server
```

첫 실행 시 계정을 생성한다:

```
First run — set up an account for dk-server.
Name: Chandler
PIN: ****
Digital Key Server running on http://0.0.0.0:8100
  LAN: http://172.30.1.9:8100
```

대시보드: `http://localhost:8100`

### 1-2. dk-web 시작

```bash
dk-web
```

사용자 앱: `http://localhost:8000`

### 1-3. ESP32 펌웨어

WiFi 설정 (`firmware/main/dk_wifi.h`):

```c
#define DK_WIFI_SSID             "MyWiFi"
#define DK_WIFI_PASSWORD         "password"
#define DK_SERVER_URL            "http://dk-server.local:8100"
#define DK_CLOUD_POLL_INTERVAL_S  30
```

> `DK_WIFI_SSID`를 비워두면 WiFi/Cloud 모듈은 skip되고 BLE-only로 동작한다.
> ESP32-S3는 **2.4GHz WiFi만** 지원.

빌드 및 플래시:

```bash
cd firmware
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

---

## 2. 초기 설정 (dk-server 대시보드)

### 2-1. 계정 추가

대시보드에서 Accounts → **+ Add**:
- Name: 계정 이름 (예: `42dot`)
- PIN: 로그인 비밀번호

### 2-2. 차량 등록

대시보드에서 Vehicles → **+ Add**:
- Name: 차량 이름 (예: `My Car`)
- BLE Address: ESP32의 BLE 주소 (`AA:BB:CC:DD:EE:FF`)

> BLE 주소는 `idf.py monitor`에서 `BT addr: XX:XX:XX:XX:XX:XX` 로그로 확인

### 2-3. Owner 지정

차량 카드에서 👤 버튼 → 계정 선택 → **Set Owner**

이때 서버가 자동으로:
1. ECC P-256 키페어 생성 (key_id + public_key + private_key)
2. `account=선택한 계정`, `role=owner`로 저장

---

## 3. ESP32 클라우드 동기화

ESP32 부팅 후 WiFi 연결이 완료되면:

### 3-1. Device Pubkey 등록

```
ESP32                              dk-server
  │                                    │
  │  POST /api/provision/AA:BB:.../device-key
  │  { "device_public_key": "04ab..." }
  │ ──────────────────────────────────>│
  │                                    │  → 차량 레코드에 저장
```

ESP32가 자체 생성한 ECC P-256 device keypair의 public key를 서버에 등록한다.
이후 dk-web이 상호 인증 시 이 값을 참조하여 rogue device를 감지한다.

### 3-2. 키 동기화 (30초 주기)

```
ESP32                              dk-server
  │                                    │
  │  GET /api/provision/AA:BB:CC:...   │
  │ ──────────────────────────────────>│
  │                                    │
  │  { "keys": [                       │
  │    { "key_id": "a1b2...",          │
  │      "public_key": "04ab..." }     │
  │  ]}                                │
  │ <──────────────────────────────────│
  │                                    │
  │  → 새 키: NVS에 추가 + auto-approve│
```

ESP32 로그:

```
I (dk_wifi) got IP: 192.168.0.15
I (dk_cloud) registering device pubkey to server
I (dk_cloud) device pubkey registered successfully
I (dk_cloud) server has 1 keys for AA:BB:CC:DD:EE:FF
I (dk_cloud) added key from cloud: a1b2c3d4e5f6a7b8
```

---

## 4. dk-web 사용

### 4-1. 로그인

`http://localhost:8000`에서 PIN 입력 → dk-server로 검증 → 세션 생성

### 4-2. 자동 연결

로그인 후 화면:
- **Account, Vehicle, Role** 정보 표시
- 등록된 차량을 자동으로 BLE 스캔
- 차량 발견 시 자동 연결 + 인증

연결 과정 (Progress UI에 표시):

| Step | 동작 |
|------|------|
| **Connect** | BLE 연결 |
| **Authenticate** | dk-server에서 private key 다운로드 → 챌린지-응답 |
| **Device Auth** | 서버 등록 device pubkey와 비교 → 상호 인증 |
| **Subscribe** | 200ms 주기 상태 모니터링 시작 |

연결 완료 후:
- 잠금/해제 상태 실시간 표시
- RSSI, Zone, Auth 상태 모니터링
- BLE 끊기면 자동으로 재스캔 → 재연결

### 4-3. 키 공유

Owner만 사용 가능. Info 카드에 **Share** 버튼이 표시된다.

1. **Share** 클릭
2. 공유 대상 계정 선택
3. Role 선택: `Family` 또는 `Guest`
4. Guest면 만료일 설정
5. **Share** 클릭

내부 동작:

```
dk-web → POST /api/share → dk-server (새 키페어 생성)
                                ↓
ESP32 ← WiFi 폴링 (30초 이내) ← dk-server (새 public key)
                                ↓
공유 대상: dk-web 로그인 → 차량 표시 → BLE 연결/인증 성공
```

### 4-4. 키 회수

dk-server 대시보드에서 해당 키의 ✕ 버튼으로 삭제.
ESP32가 다음 폴링에서 키 목록 변경을 감지하고 적용한다.

---

## 5. 데이터 모델

### Vehicle (vehicles.json)

```json
{
  "id": "uuid8자",
  "name": "My Car",
  "ble_address": "AA:BB:CC:DD:EE:FF",
  "device_public_key": "04ab...(130 hex)",
  "created_at": "ISO timestamp",
  "keys": [...]
}
```

### Key

```json
{
  "key_id": "16자 hex",
  "account": "Chandler",
  "role": "owner",
  "public_key": "04ab...(130 hex)",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "expires_at": null,
  "created_at": "ISO timestamp"
}
```

| 데이터 | 위치 | 용도 |
|--------|------|------|
| private_key | dk-server (vehicles.json) | dk-web이 HTTP로 다운로드하여 서명 |
| public_key | dk-server + ESP32 NVS | ESP32가 서명 검증 |
| device_public_key | dk-server + ESP32 (자체 생성) | dk-web이 상호 인증에 사용 |
| key_id | 모든 곳 | 키 식별자 |
| account | dk-server | 키 소유 계정, 차량 필터링 |

---

## 6. API Reference

### dk-server (:8100)

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/login` | PIN 로그인 |
| `GET` | `/api/accounts` | 계정 목록 |
| `POST` | `/api/accounts` | 계정 생성 (name, pin) |
| `DELETE` | `/api/accounts/{name}` | 계정 삭제 |
| `GET` | `/api/vehicles` | 차량 목록 (`?account=X`로 필터링) |
| `POST` | `/api/vehicles` | 차량 등록 (name, ble_address) |
| `DELETE` | `/api/vehicles/{id}` | 차량 삭제 |
| `POST` | `/api/vehicles/{id}/keys` | 키 생성 (account, role) |
| `GET` | `/api/vehicles/{id}/keys/{kid}/private` | Private key PEM 다운로드 |
| `DELETE` | `/api/vehicles/{id}/keys/{kid}` | 키 삭제 |
| `POST` | `/api/vehicles/{id}/share` | 키 공유 (account, role, expires_at) |
| `GET` | `/api/provision/{ble_addr}` | ESP32용 — public key 목록 |
| `POST` | `/api/provision/{ble_addr}/device-key` | ESP32 device pubkey 등록 |
| `GET` | `/api/events` | 이벤트 로그 |
| `POST` | `/api/events` | 이벤트 기록 |

### dk-web (:8000)

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | 메인 UI (index.html) |
| `GET` | `/login` | 로그인 페이지 |
| `POST` | `/api/login` | PIN 로그인 (dk-server 프록시) |
| `POST` | `/api/logout` | 로그아웃 |
| `GET` | `/api/accounts` | 계정 목록 (dk-server 프록시) |
| `POST` | `/api/share` | 키 공유 (dk-server 프록시) |
| `WS` | `/ws` | WebSocket (실시간 BLE 제어) |

---

## 7. 검증 체크리스트

| # | 테스트 | 확인 방법 |
|---|--------|-----------|
| 1 | 계정/차량 등록 | dk-server 대시보드에서 생성 확인 |
| 2 | Owner 지정 | 👤 → 계정 선택 → 키 목록에 owner 표시 |
| 3 | ESP32 WiFi 동기화 | `idf.py monitor` → `dk_cloud: added key from cloud` |
| 4 | Device pubkey 등록 | `dk_cloud: device pubkey registered successfully` |
| 5 | dk-web 로그인 | PIN 입력 → 계정/차량 정보 표시 |
| 6 | Auto-scan + 연결 | 차량 자동 발견 → progress 표시 → 연결 완료 |
| 7 | 상호 인증 | Device Auth step done 확인 |
| 8 | 키 공유 | Owner로 Share → 대상 계정 로그인 → 차량 표시 → 연결 성공 |
| 9 | 키 회수 | 대시보드에서 키 삭제 → 대상 계정 인증 실패 |
| 10 | Factory reset | BOOT 3초 → NVS 삭제 → 재동기화 |

---

## 8. 네트워크 구성

```
같은 2.4GHz WiFi 네트워크
┌──────────────────────────────────────────────┐
│                                              │
│   dk-server (WSL2/Windows)   ESP32-S3        │
│   0.0.0.0:8100               WiFi STA       │
│   mDNS: dk-server.local      mDNS resolve   │
│                                              │
│   dk-web (WSL2)              BLE 연결        │
│   127.0.0.1:8000             WSL2 USB pass   │
│                                              │
└──────────────────────────────────────────────┘
```

- **mDNS**: dk-server → `dk-server.local` 광고, ESP32 → mDNS로 해석
- **2.4GHz 필수**: ESP32-S3는 5GHz 미지원
- **dk-web BLE**: WSL2에서 Bluetooth USB passthrough 필요 (`scripts/wsl-bluetooth.ps1`)
