# Digital Key: 실무(Production) 비교 분석

## 같은 점 (실무와 유사)

| 영역 | 이 프로젝트 | 실무 (CCC Digital Key 등) |
|------|------------|--------------------------|
| **비대칭 키 인증** | ECC P-256 challenge-response | CCC 2.0/3.0도 P-256 ECDSA 사용 |
| **키 프로비저닝 분리** | Provision(등록) → Auth(인증) 2단계 | 동일한 흐름. 키 등록과 인증은 별도 단계 |
| **다중 키 관리** | owner/user 역할, approve/delete | 실무도 Owner Key, Friend Key 등 역할 구분 |
| **BLE 근접 감지** | RSSI 기반 zone 판단 | BLE를 근접 감지 채널로 사용하는 것은 동일 |
| **서버-디바이스 분리** | dk-server(관리) ↔ dk-web(제어) | OEM 클라우드(관리) ↔ 모바일앱(제어) 구조와 유사 |
| **이벤트 로깅** | auth/lock 이벤트를 서버에 보고 | 실무도 감사 로그(audit trail) 필수 |
| **Graceful degradation** | dk-server 꺼지면 스캔 기반 fallback | 오프라인에서도 로컬 키로 동작해야 하는 요건 동일 |

## 다른 점 (실무와 차이)

### 1. 키 저장: 파일 vs. Secure Element

```
이 프로젝트:  ~/.dk-client/{key_id}.pem  (파일시스템)
실무:         Secure Element (SE) / TEE / StrongBox
```

실무에서는 개인키가 **절대 SE 밖으로 나오지 않음**. 서명 연산 자체가 SE 내부에서 수행됨. `.pem` 파일은 복사/탈취가 가능하므로 프로덕션에서는 불가.

### 2. 측위: RSSI vs. UWB

```
이 프로젝트:  BLE RSSI → zone 레벨 판단
실무 (CCC 3.0):  UWB (Ultra-Wideband) ToF 측위 + BLE
```

RSSI는 **relay attack에 취약**. 공격자가 BLE 신호를 중계하면 원거리에서도 잠금 해제 가능. 실무에서는 UWB의 Time-of-Flight로 물리적 거리를 cm 단위로 검증하고, **anti-relay** 프로토콜을 적용.

### 3. 인증 방향: 단방향 vs. 상호 인증

```
이 프로젝트:  클라이언트 → 차량 (단방향)
실무:         상호 인증 (mutual authentication)
```

실무에서는 차량도 자신의 인증서로 클라이언트에게 신원을 증명함. 그래야 **가짜 차량(rogue device)**에 서명을 보내는 것을 방지.

### 4. 인증서 체계: raw pubkey vs. PKI

```
이 프로젝트:  key_id + raw public key 직접 등록
실무:         CA → OEM 인증서 → 디바이스 인증서 (X.509 체인)
```

실무는 **Certificate Authority 기반 PKI**로 키의 출처와 유효성을 검증. 인증서 폐기(revocation), 만료(expiry) 관리 포함.

### 5. 키 공유: 로컬 파일 vs. 클라우드 프로비저닝

```
이 프로젝트:  같은 ~/.dk-client/ 디렉토리의 .pem 파일 공유
실무:         Apple Wallet / Google Wallet을 통한 OTA 키 공유
              OEM 서버가 키 권한을 중개
```

실무에서는 Owner가 친구에게 키를 공유할 때 **OEM 클라우드 → 수신자의 SE에 직접 프로비저닝**. 개인키가 네트워크를 타지 않음.

### 6. 통신 보안: 평문 vs. 암호화 채널

```
이 프로젝트:  BLE GATT 평문 (페어링은 있지만)
              WebSocket 평문 (HTTP)
실무:         BLE: Secure Channel (AES-CCM 암호화)
              서버: mTLS / OAuth 2.0
```

이 프로젝트의 `POST /api/events`를 `PUBLIC_PATHS`에 추가한 것은 편의상이지만, 실무에서는 **서비스 간 통신도 인증 필수** (API key, mTLS, JWT 등).

### 7. 클라이언트: Web UI vs. 네이티브 앱

```
이 프로젝트:  브라우저 WebSocket → Python 서버 → BLE
실무:         네이티브 앱 → CoreBluetooth/Android BLE → 직접 통신
```

실무에서는 BLE 통신을 **네이티브 앱이 직접** 수행. 중간 서버를 거치지 않아 latency가 낮고, SE 접근도 네이티브 API로만 가능.

### 8. 상태 관리: 단순 플래그 vs. 복잡한 FSM

```
이 프로젝트:  auth_state 4단계 (NONE/PENDING/FAILED/OK)
실무:         수십 개 상태의 FSM
              - 트랜잭션 타임아웃, 재시도 정책
              - 동시 연결 핸들링
              - 배터리 부족 모드 (NFC passive)
```

## 요약

> **암호학적 기본 구조(P-256 challenge-response)**는 실무와 같지만, **키 보호(SE)**, **측위(UWB)**, **PKI**, **상호 인증** 등 **신뢰 경계(trust boundary)**를 강화하는 레이어가 빠져 있음.

프로토타입/학습용으로는 핵심 흐름을 잘 재현하고 있고, 프로덕션으로 가려면 위 차이점들이 보안 요건이 됨.
