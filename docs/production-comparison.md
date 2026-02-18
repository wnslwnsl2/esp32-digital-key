# Digital Key: 실무(Production) 비교 분석

## 같은 점 (실무와 유사)

| 영역 | 이 프로젝트 | 실무 (CCC Digital Key 등) |
|------|------------|--------------------------|
| **비대칭 키 인증** | ECC P-256 ECDSA challenge-response | CCC 2.0/3.0도 P-256 ECDSA 사용 |
| **상호 인증** | device pubkey 검증 + 챌린지-응답 | 차량도 인증서로 신원 증명 |
| **클라우드 키 프로비저닝** | dk-server에서 키 생성 → WiFi로 ESP32에 배포 | OEM 서버에서 키 생성 → OTA로 차량에 배포 |
| **다중 키 관리** | owner/family/guest 역할 구분 | Owner Key, Friend Key 등 역할 구분 |
| **키 공유** | dk-web에서 owner가 다른 계정에 공유 | 모바일 앱에서 owner가 친구에게 공유 |
| **서버-디바이스 분리** | dk-server(관리) ↔ dk-web(제어) | OEM 클라우드(관리) ↔ 모바일앱(제어) |
| **차량 자가 키 생성** | ESP32가 ECC device keypair 자체 생성 | 차량 ECU에서 키 생성 (공장 프로비저닝) |
| **이벤트 로깅** | auth/lock 이벤트를 서버에 보고 | 감사 로그(audit trail) 필수 |
| **BLE 근접 감지** | RSSI 기반 zone 판단 + 자동 잠금 | BLE를 근접 감지 채널로 사용 |

## 다른 점 (실무와 차이)

### 1. 키 저장: 서버 DB vs. Secure Element

```
이 프로젝트:  dk-server의 vehicles.json (파일시스템)
              dk-web이 HTTP로 private key 다운로드하여 메모리에서 사용
실무:         Secure Element (SE) / TEE / StrongBox
              개인키가 SE 밖으로 나오지 않음
```

실무에서는 개인키가 **절대 SE 밖으로 나오지 않음**. 서명 연산 자체가 SE 내부에서 수행됨.
이 프로젝트는 서버에서 HTTP로 private key를 전송하므로 network intercept 위험이 있음.

### 2. 측위: RSSI vs. UWB

```
이 프로젝트:  BLE RSSI → zone 레벨 판단
실무 (CCC 3.0):  UWB (Ultra-Wideband) ToF 측위 + BLE
```

RSSI는 **relay attack에 취약**. 공격자가 BLE 신호를 중계하면 원거리에서도 잠금 해제 가능.
실무에서는 UWB의 Time-of-Flight로 물리적 거리를 cm 단위로 검증하고, **anti-relay** 프로토콜을 적용.

### 3. 인증서 체계: raw pubkey vs. PKI

```
이 프로젝트:  key_id + raw public key 직접 등록
              device pubkey도 hex 값 비교
실무:         CA → OEM 인증서 → 디바이스 인증서 (X.509 체인)
```

실무는 **Certificate Authority 기반 PKI**로 키의 출처와 유효성을 검증.
인증서 폐기(revocation), 만료(expiry) 관리 포함.

### 4. 통신 보안: 평문 vs. 암호화 채널

```
이 프로젝트:  BLE GATT 평문
              WiFi HTTP 평문
              WebSocket HTTP
실무:         BLE: Secure Channel (AES-CCM 암호화)
              서버: mTLS / OAuth 2.0
```

특히 private key가 HTTP 평문으로 전송되는 점은 실무에서는 허용 불가.
실무는 **서비스 간 통신도 인증 필수** (mTLS, JWT 등).

### 5. 클라이언트: Web UI vs. 네이티브 앱

```
이 프로젝트:  브라우저 → WebSocket → Python 서버 → BLE (bleak)
실무:         네이티브 앱 → CoreBluetooth / Android BLE → 직접 통신
```

실무에서는 BLE 통신을 **네이티브 앱이 직접** 수행.
중간 서버를 거치지 않아 latency가 낮고, SE 접근도 네이티브 API로만 가능.

### 6. 상태 관리: 단순 플래그 vs. 복잡한 FSM

```
이 프로젝트:  auth_state 4단계 (NONE/PENDING/FAILED/OK)
              auto-scan → connect → auth → subscribe
실무:         수십 개 상태의 FSM
              - 트랜잭션 타임아웃, 재시도 정책
              - 동시 연결 핸들링
              - 배터리 부족 모드 (NFC passive)
```

### 7. 키 삭제 동기화: 미구현 vs. 즉시 폐기

```
이 프로젝트:  서버에서 키 삭제 → ESP32 다음 폴링에서 감지 (최대 30초 지연)
              ESP32 keystore에서 삭제 로직 미완성
실무:         키 폐기(revocation) → 즉시 반영
              CRL(Certificate Revocation List) 또는 OCSP
```

## 요약

> **암호학적 핵심(P-256 challenge-response, 상호 인증, 클라우드 프로비저닝)**은 실무와 유사하지만,
> **키 보호(SE)**, **측위(UWB)**, **PKI**, **통신 암호화** 등 **신뢰 경계(trust boundary)**를 강화하는 레이어가 빠져 있음.

프로토타입/학습용으로는 핵심 흐름을 잘 재현하고 있고, 프로덕션으로 가려면 위 차이점들이 보안 요건이 됨.
