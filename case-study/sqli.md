## 2. SQL Injection 기반 데이터 탈취 공격 시나리오
 
### 2.1 개요
 
MOVEit Transfer 침해사고(2023)의 공격 라이프사이클을 참고하여, **Python/Flask 기반 병원 예약 시스템**에서 발생할 수 있는 SQL Injection 기반 데이터 탈취 공격을 재현한 시나리오다.
 
외부에 공개된 진료 안내문 검색 API(`GET /api/public/documents/search`)의 SQL Injection 취약점을 악용해 PostgreSQL DB 구조를 파악하고, `user_sessions` 테이블에 관리자 권한 세션 레코드를 직접 삽입한다. 이후 삽입한 세션으로 관리자 전용 문서 API에 접근하여 민감 의료 문서를 대량 다운로드하고, 공격 흔적을 지우기 위해 삽입한 세션 레코드를 삭제한다.
 
- **취약점**: SQL Injection (Boolean-based / UNION-based)
- **대상 시스템**: Flask + PostgreSQL 기반 병원 예약 시스템
- **핵심 취약 구조**: 검색어를 SQL문에 문자열로 직접 결합, 세션 권한을 `role_snapshot`으로 고정 캐싱
---
 
### 2.2 공격 흐름
 
```
[1] 공개 진료 안내문 검색 API(GET /api/public/documents/search) 탐색
      ↓
[2] SQL Injection 가능 여부 확인 (Boolean-based 응답 차이 분석)
      ↓
[3] DB 스키마 열거: DBMS 종류, 테이블 목록, 컬럼 구조 확인
    (users, user_sessions, medical_documents 테이블 식별)
      ↓
[4] 공격자가 임의 원문 토큰(LAB-ATTACKER-TOKEN) 생성 및 해시 계산
      ↓
[5] SQL Injection으로 user_sessions 테이블에
    role_snapshot=ADMIN인 신규 세션 레코드 삽입
      ↓
[6] 삽입한 토큰으로 관리자 API(GET /api/admin/documents) 접근
    (정상 로그인 절차 없이 인증 우회)
      ↓
[7] classification=SENSITIVE 문서 목록 열거 및 대상 선별
      ↓
[8] 짧은 시간 내 다수 민감 문서 대량 다운로드
    (GET /api/admin/documents/{document_id}/download)
      ↓
[9] 공격에 사용한 세션 레코드 삭제 (흔적 제거)
      ↓
[10] SIEM이 7단계 이벤트 연쇄를 30분 이내 상관 분석하여 Critical 경보 발생
      ↓
[11] SOAR가 IP 차단, 세션 폐기, 계정 위험 표시, 증적 수집 자동 수행
      ↓
[12] 취약 코드 수정 및 세션 보안 강화 후 서비스 복구
```
 
**권한 우회 핵심 구조:**
```
SQL Injection → user_sessions에 ADMIN role_snapshot 세션 삽입
→ Flask 인증 미들웨어가 users.role 재조회 없이 role_snapshot 신뢰
→ 공격자가 알고 있는 원문 토큰으로 관리자 API 접근
```
 
---
 
### 2.3 MITRE ATT&CK 매핑
 
| 순서 | 공격 단계 | 전술 | 기법 ID | 기법명 | 적용 내용 |
|------|-----------|------|---------|--------|-----------|
| 1 | 공개 API 탐색 | Reconnaissance | T1595.002 | Vulnerability Scanning | 공개 검색 API의 입력 처리 및 취약 가능성 탐색 |
| 2 | SQL Injection 악용 | Initial Access | T1190 | Exploit Public-Facing Application | 외부 공개 Flask API 취약점 악용 |
| 3 | DB 구조 및 데이터 조회 | Collection | T1213.006 | Data from Information Repositories: Databases | PostgreSQL 사용자·세션·문서 정보 수집 |
| 4 | 관리자 세션 삽입 | Credential Access | T1606.001 | Forge Web Credentials: Web Cookies | 공격자가 제어하는 관리자 세션 생성 |
| 5 | 관리자 API 접근 | Defense Evasion | T1550.004 | Use Alternate Authentication Material: Web Session Cookie | 위조된 세션으로 인증 우회하여 보호 API 접근 |
| 6 | 의료 문서 탐색·수집 | Collection | T1005 | Data from Local System | 서버 저장소의 의료 문서 수집 |
| 7 | HTTP 파일 다운로드 | Exfiltration | T1041 | Exfiltration Over C2 Channel | 동일 공격 HTTP 채널을 통해 파일 반환 |
| 8 | 공격 세션 삭제 | Defense Evasion | T1070 | Indicator Removal | 공격자가 생성한 세션 레코드 삭제 |
 
---
 
### 2.4 대응 방안
 
**즉각 대응**
- 공격 출발지 IP 임시 차단 (Nginx 차단 목록 추가)
- 위조된 관리자 세션 및 동일 사용자의 다른 활성 세션 전체 폐기
- 취약한 공개 검색 API 임시 제한 또는 요청 속도 강제 제한
- 대상 컨테이너 즉시 삭제하지 않고 증적 보존 우선 수행
- 관련 로그(웹·DB·세션·문서 접근) 보존 기간 연장
**취약점 제거**
- 문자열 결합 SQL문 제거, **SQLAlchemy ORM 또는 매개변수화 쿼리** 사용
- 검색 가능한 컬럼을 화이트리스트로 제한, 검색어 길이 및 허용 문자 검증
- 공개 검색 결과를 `PUBLIC` 문서로 강제 제한
- 데이터베이스 오류 메시지 외부 노출 차단
- 웹 애플리케이션 DB 계정 권한 최소화 (공개 검색에 필요한 SELECT만 허용)
**세션 보안 강화**
- 모든 관리자 세션 폐기 후 재발급
- `role_snapshot`을 세션에 고정 캐싱하지 않고, **매 요청마다 `users.role`을 DB에서 재조회**하여 권한 검증
- 세션 생성은 인증 모듈을 통해서만 가능하도록 강제
- 관리자 세션 생성 시 MFA 요구
- 세션 발급 IP와 User-Agent 기록 및 비정상 IP 변경 시 추가 인증
**사후 조치**
- 정기적인 DAST(동적 분석) 및 WAF 규칙 적용
- 요청 속도 제한(Rate Limiting) 전 구간 적용
- SIEM 탐지 규칙 보완 및 SOAR 대응 결과·승인 절차 주기적 검토
- 다운로드된 문서 목록과 접근한 환자 범위를 기준으로 개인정보 침해 신고 여부 검토