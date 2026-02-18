# Digital Key 시스템 — 전체 프로세스

## 구성 요소

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  dk-server   │     │   dk-web    │     │   ESP32-S3   │
│  :8100       │     │   :8000     │     │  (차량)      │
│              │     │             │     │              │
│ 키 생성/관리  │     │ BLE 연결    │     │ BLE + WiFi   │
│ 차량 등록     │     │ 챌린지-응답  │     │ NVS 키저장소  │
│ 계정 관리     │     │ 잠금/해제   │     │ 근접 감지     │
└──────┬───────┘     └──────┬──────┘     └──────┬───────┘
       │                    │                    │
       │   HTTP API         │  WebSocket+BLE     │  WiFi HTTP
       └────────────────────┴────────────────────┘
```

| 구성 요소 | 역할 | 접속 |
|-----------|------|------|
| **dk-server** | 키 생성, 차량/계정/키 관리 (딜러용 대시보드) | `http://localhost:8100` (브라우저) |
| **dk-web** | 사용자 Web UI, BLE로 차량 연결/인증/잠금 | `http://localhost:8000` |
| **ESP32-S3** | 차량 측 장치, BLE 광고 + WiFi로 서버에서 키 수신 (2.4GHz only) | BLE `DK-XXXX` |

---

## 1. 초기 설정

### 1-1. 계정 생성

dk-server 첫 실행 시 계정을 만든다.

```
$ dk-server
First run — set up an account for dk-server.
Name: Chandler
PIN: ****
Digital Key Server running on http://0.0.0.0:8100
  LAN: http://172.30.1.9:8100
  ESP32 DK_SERVER_URL: http://172.30.1.9:8100
```

대시보드(`http://localhost:8100`)에서 추가 계정도 만들 수 있다.
예: `Chandler`(딜러), `42dot`(공유 대상)

### 1-2. 차량 등록

dk-server 대시보드에서:
1. **+ Add** 클릭
2. 차량 이름 (`My Car`) + BLE 주소 (`AA:BB:CC:DD:EE:FF`) 입력
3. **Register**

이 BLE 주소는 ESP32의 주소다. (`idf.py monitor`에서 `BT addr: XX:XX:XX:XX:XX:XX` 로그로 확인)

---

## 2. 키 생성 (dk-server)

### 이전 방식 (로컬)
```
로컬 PEM 파일 생성 → 수동으로 key_id 입력 → BLE로 직접 프로비저닝
```

### 현재 방식 (클라우드)
```
dk-server가 자동으로 키페어 생성 → 서버에 저장 → ESP32가 WiFi로 받아감
```

### 2-1. 키 추가 과정

dk-server 대시보드에서 차량 카드의 🔑 버튼 클릭:

1. **Account** 선택 — 이 키를 사용할 계정 (예: `Chandler`)
2. **Role** 선택 — `owner` / `family` / `guest`
3. guest 선택 시 **만료일** 입력
4. **Create Key** 클릭

서버가 내부적으로 하는 일:
```python
# 1. ECC P-256 키페어 자동 생성
private_key = ec.generate_private_key(SECP256R1)
public_key  = private_key.public_key()   # 65바이트 (04 + X + Y)
key_id      = random 16자리 hex

# 2. vehicles.json에 저장
{
  "key_id": "a1b2c3d4e5f6a7b8",
  "account": "Chandler",
  "role": "owner",
  "public_key": "04ab12...cd34",     ← 130자 hex (ESP32에 전달)
  "private_key": "-----BEGIN...",     ← PEM (dk-web이 다운로드)
  "expires_at": null
}
```

**핵심: private key는 서버에만 저장되고, public key만 ESP32에 전달된다.**

---

## 3. ESP32 키 수신 (WiFi 클라우드 동기화)

### 3-1. ESP32 WiFi 설정

`firmware/main/dk_wifi.h` 상단의 상수를 수정:
```c
#define DK_WIFI_SSID             "MyWiFi"    /* 비워두면 WiFi 비활성화 */
#define DK_WIFI_PASSWORD         "password"
#define DK_SERVER_URL            "http://dk-server.local:8100"
#define DK_CLOUD_POLL_INTERVAL_S  30
```

> **ESP32-S3는 2.4GHz WiFi만 지원.** 5GHz SSID에는 연결 불가.

`DK_SERVER_URL`은 `http://dk-server.local:8100`이 기본값.
dk-server가 mDNS로 `dk-server.local`을 광고하므로 IP 하드코딩 불필요.

### 3-2. 부팅 순서

```c
app_main()
├── NVS 초기화
├── DkAuth_Init()
├── DkKeystore_Init()       // NVS에서 기존 키 로드
├── DkLock_Init()
├── DkLed_Init()
├── DkWifi_Init()           // WiFi STA 연결 (비동기)
├── DkCloud_Init()          // 클라우드 동기화 task 시작
├── BleStack_Init()         // BLE 광고 시작 "DK-XXXX"
├── DkProximity_Init()
└── DkButton_Init()
```

### 3-3. 클라우드 동기화 동작

`dk_cloud` task가 30초마다 반복:

```
ESP32                              dk-server
  │                                    │
  │  GET /api/provision/AA:BB:CC:...   │
  │ ──────────────────────────────────>│
  │                                    │
  │  { "keys": [                       │
  │    { "key_id": "a1b2...",          │
  │      "public_key": "04ab..." },    │
  │    { "key_id": "f9e8...",          │
  │      "public_key": "04cd..." }     │
  │  ]}                                │
  │ <──────────────────────────────────│
  │                                    │
  │  → 새 키: NVS keystore에 추가       │
  │  → 삭제된 키: (다음 구현 예정)       │
```

ESP32 로그 예시:
```
I (dk_wifi) WiFi STA initialized, connecting to MyWiFi
I (dk_wifi) got IP: 192.168.0.15
I (dk_cloud) cloud key sync task started (poll every 30s)
I (dk_cloud) WiFi connected, starting cloud key sync
I (dk_cloud) server has 2 keys for AA:BB:CC:DD:EE:FF
I (dk_cloud) added key from cloud: a1b2c3d4e5f6a7b8
```

**`DK_WIFI_SSID`를 비워두면** WiFi/Cloud 모듈은 자동으로 스킵되고, 기존 BLE-only 방식으로 동작한다.

---

## 4. dk-web 로그인 및 차량 연결

### 4-1. 로그인

사용자가 `http://localhost:8000`에서 PIN 로그인.
PIN은 dk-server의 계정 시스템으로 검증된다.

```
사용자 Chandler → PIN 입력 → dk-server 검증 → 세션 생성
```

### 4-2. 차량 목록 필터링

로그인한 계정에 키가 배정된 차량만 표시된다.

```
dk-web                         dk-server
  │                                │
  │  GET /api/vehicles?account=Chandler
  │ ──────────────────────────────>│
  │                                │
  │  (Chandler의 키가 있는 차량만)  │
  │ <──────────────────────────────│
```

- `Chandler`로 로그인 → Chandler에게 배정된 키가 있는 차량 표시
- `42dot`로 로그인 → 42dot에게 공유된 차량만 표시

### 4-3. BLE 연결 + 인증

차량을 선택하면 다음 과정이 자동 실행:

```
dk-web                    ESP32
  │                         │
  │ ① BLE Connect           │
  │ ───────────────────────>│
  │                         │
  │ ② Private key 다운로드   │     dk-server
  │     GET /api/vehicles/{id}/keys/{key_id}/private
  │ ─────────────────────────────────────────>│
  │ <─────────────────────── PEM 응답 ────────│
  │                         │
  │ ③ Provision (pubkey)    │
  │ ───────────────────────>│  (이미 WiFi로 받았으면 skip)
  │                         │
  │ ④ Challenge 읽기        │
  │ <───────────────────────│  32바이트 랜덤
  │                         │
  │ ⑤ 서명 (private key)    │
  │  sig = ECDSA(challenge) │
  │                         │
  │ ⑥ Response 쓰기         │
  │ ───────────────────────>│
  │   key_id + signature    │
  │                         │
  │ ⑦ ESP32 검증            │
  │   pubkey로 sig 검증  ✓  │
  │                         │
  │ ⑧ Auth State 읽기       │
  │ <───────────────────────│  AUTH_OK (3)
  │                         │
  │ ⑨ 잠금/해제 가능         │
```

**이전과 달라진 점:**
- 이전: 로컬 `~/.dk-client/{key_id}.pem` 파일 필요
- 현재: dk-server에서 private key를 HTTP로 다운로드 → 로컬 PEM 불필요

로컬 PEM이 있으면 fallback으로 여전히 사용 가능 (하위 호환).

---

## 5. 키 공유

### 5-1. 딜러가 다른 계정에 차량 공유

dk-server 대시보드에서 차량 카드의 👥 버튼 클릭:

1. **Account** 선택 — 공유 대상 (예: `42dot`)
2. **Role** 선택 — `family` 또는 `guest`
3. guest면 **만료일** 설정
4. **Share** 클릭

내부 동작:
```
dk-server: 새 키페어 생성 → account=42dot으로 저장
           ↓
ESP32: 다음 폴링(30초 이내)에서 새 public key 수신 → NVS에 추가
           ↓
42dot: dk-web 로그인 → 공유된 차량 보임 → BLE 연결/인증 성공
```

### 5-2. 키 회수

dk-server 대시보드에서 해당 키의 ✕ 버튼 클릭.

```
dk-server: 키 삭제
           ↓
ESP32: 다음 폴링에서 키 목록 변경 감지 (삭제 로직은 추후 구현)
           ↓
42dot: 인증 시도 → ESP32에 public key 없음 → 인증 실패
```

---

## 6. 데이터 흐름 요약

```
                    vehicles.json
                    ┌─────────────────────────────┐
                    │ { id, name, ble_address,     │
                    │   keys: [                    │
                    │     { key_id,                │
                    │       account: "Chandler",   │
                    │       role: "owner",         │
                    │       public_key: "04ab...", │◄── ESP32에 전달 (WiFi)
                    │       private_key: "PEM..." }│◄── dk-web이 다운로드 (HTTP)
                    │   ]                          │
                    │ }                            │
                    └─────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         dk-server     dk-web       ESP32
        (관리/생성)   (인증/사용)   (검증/저장)
```

| 데이터 | 어디에 | 누가 사용 |
|--------|--------|-----------|
| private_key (PEM) | dk-server `vehicles.json` | dk-web이 HTTP로 다운로드해서 서명에 사용 |
| public_key (hex) | dk-server + ESP32 NVS | ESP32가 서명 검증에 사용 |
| key_id | 모든 곳 | 키 식별자 (16자 hex) |
| account | dk-server | 키 소유 계정, 차량 필터링에 사용 |
| role | dk-server + 대시보드 | owner/family/guest 구분 |
| expires_at | dk-server | guest 키 만료 시간 (표시용, 검증은 추후) |

---

## 7. 검증 체크리스트

| # | 테스트 | 확인 방법 |
|---|--------|-----------|
| 1 | 키 자동 생성 | 대시보드에서 🔑 → account 선택 → Create Key → 키 목록에 key_id, account, role 표시 |
| 2 | ESP32 WiFi 동기화 | `idf.py monitor` → `dk_cloud: added key from cloud: xxxx` 로그 |
| 3 | dk-web 로그인 필터링 | Chandler로 로그인 → Chandler 키가 있는 차량만 표시 |
| 4 | 클라우드 키 인증 | dk-web에서 차량 연결 → `Using cloud key: xxxx` 로그 → AUTH_OK |
| 5 | 키 공유 | 대시보드 👥 → 42dot에 공유 → 42dot 로그인 → 차량 표시 → 연결 성공 |
| 6 | 키 회수 | 대시보드에서 키 ✕ → 42dot 재연결 시 인증 실패 |

---

## 8. 네트워크 구성

```
같은 2.4GHz WiFi 네트워크
┌──────────────────────────────────────────────┐
│                                              │
│   dk-server (WSL2)        ESP32-S3           │
│   192.168.0.x:8100        192.168.0.y        │
│         │                      │             │
│   시작 시 LAN IP 출력     dk_wifi.h에 IP 설정  │
│                                              │
└──────────────────────────────────────────────┘
```

- **mDNS**: dk-server 시작 시 `zeroconf`로 `dk-server.local` 광고, ESP32는 `mdns` 컴포넌트로 해석
- **IP 고정 불필요**: DHCP IP가 바뀌어도 `.local` 호스트명으로 자동 추적
- **dk-server는 Windows에서 실행** (WSL2의 NAT 문제 회피)
- **2.4GHz 필수**: ESP32-S3는 5GHz WiFi 미지원. 공유기에서 2.4GHz 밴드 활성화 필요
- **포트**: dk-server는 `0.0.0.0:8100`에 바인드 (같은 네트워크의 모든 장치에서 접근 가능)
- **브라우저**: Windows에서는 `http://localhost:8100`으로 접근

---

## API 레퍼런스

### dk-server (:8100)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/vehicles/{id}/keys` | 키 생성 (account, role, expires_at) |
| GET | `/api/vehicles/{id}/keys/{kid}/private` | Private key PEM 다운로드 |
| DELETE | `/api/vehicles/{id}/keys/{kid}` | 키 삭제 |
| GET | `/api/provision/{ble_address}` | ESP32용 — public key 목록 |
| POST | `/api/vehicles/{id}/share` | 다른 계정에 차량 공유 |
| GET | `/api/vehicles?account=X` | 계정별 차량 필터링 |
| GET | `/api/accounts/{name}/keys` | 계정의 모든 키 조회 |

### 기존 API (변경 없음)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/login` | PIN 로그인 |
| GET/POST/DELETE | `/api/accounts` | 계정 CRUD |
| GET/POST/DELETE | `/api/vehicles` | 차량 CRUD |
| GET/POST | `/api/events` | 이벤트 로그 |
