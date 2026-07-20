# vuln-hospital-booking

자동화 SOC 플랫폼 실습을 위한 취약 병원 예약 웹 애플리케이션입니다.

## 개발 서버 실행

로컬에서 실행하려면 PostgreSQL이 먼저 실행 중이어야 합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg://hospital:hospital@localhost:5433/hospital"
python run.py
```

브라우저에서 `http://localhost:5000`으로 접속합니다.

## Docker로 실행

```bash
docker compose up --build
```

브라우저에서 `http://localhost:5001`으로 접속합니다.

## 데이터베이스 초기화

Docker 환경에서 테이블을 생성합니다.

```bash
docker compose exec web flask --app run init-db
```

초기 실습 데이터를 삽입합니다.

```bash
docker compose exec web flask --app run seed-db
```

`seed-db`는 기존 사용자 데이터가 있으면 중복 삽입하지 않고 건너뜁니다.

로컬 Flask 실행 환경에서는 다음 명령을 사용합니다.

```bash
flask --app run init-db
flask --app run seed-db
```

## 초기 계정

`seed-db` 실행 후 다음 계정으로 로그인할 수 있습니다.

| 역할 | 아이디 | 비밀번호 |
| --- | --- | --- |
| 관리자 | `admin` | `AdminPass123!` |
| 직원 | `staff` | `StaffPass123!` |
| 환자 | `alice` | `PatientPass123!` |
| 환자 | `bob` | `PatientPass123!` |
| 의사 | `dr.kim` | `DoctorPass123!` |
| 의사 | `dr.lee` | `DoctorPass123!` |
| 의사 | `dr.park` | `DoctorPass123!` |

## 관리자 API

다음 관리자 기능은 관리자 계정으로 로그인한 세션에서만 사용할 수 있습니다.
브라우저에서는 관리자 화면으로 표시되고, JSON 요청에서는 API 응답을 반환합니다.

| 엔드포인트 | 메서드 | 설명 |
| --- | --- | --- |
| `/admin` | `GET` | 관리자 대시보드 요약 |
| `/admin/appointments` | `GET` | 전체 예약 조회 |
| `/admin/documents` | `GET` | 전체 문서 조회 |
| `/admin/security-events` | `GET` | 애플리케이션 보안 이벤트 확인 |

## SQL Injection 실습 모드

의사 검색 API와 진료 안내문 검색 화면/API는 인증 없이 호출할 수 있는 공개 검색 기능입니다.

| 엔드포인트 | 메서드 | 설명 |
| --- | --- | --- |
| `/clinic-guides` | `GET` | 공개 진료 안내문 검색 화면 |
| `/api/doctors/search` | `GET` | 공개 의사 검색 |
| `/api/public/clinic-guides/search` | `GET` | 공개 진료 안내문 검색 |

현재 브랜치의 공개 검색 API들은 SQL Injection 공격 시나리오 재현을 위해 의도적으로 취약한 SQL 문자열 조합을 사용합니다. 공개 검색 API가 호출되면 `SQLI_DOCTOR_SEARCH_USED` 또는 `SQLI_CLINIC_GUIDE_SEARCH_USED` 보안 이벤트가 기록됩니다.

대응 단계에서는 이 취약 SQL 문자열 조합 코드를 제거하고 파라미터 바인딩 쿼리로 교체해 차단 효과를 보여주면 됩니다.

보호된 문서 다운로드가 짧은 시간에 반복되면 `BULK_DOCUMENT_DOWNLOAD` 경보와 함께 SOAR 시뮬레이션 이벤트가 기록되고 현재 세션이 폐기됩니다.

다운로드 상관분석 임계값은 다음 환경 변수로 조정할 수 있습니다.

```bash
export BULK_DOWNLOAD_WINDOW_SECONDS=60
export BULK_DOWNLOAD_THRESHOLD=5
```

## 인증 기능 확인

Docker 환경에서 서버와 DB를 실행한 뒤 DB를 초기화합니다.

```bash
docker compose up -d --build
docker compose exec web flask --app run init-db
docker compose exec web flask --app run seed-db
```

브라우저에서 로그인 화면을 확인합니다.

```text
http://localhost:5001/login
```

로그아웃은 로그인 후 상단의 로그아웃 버튼으로 실행합니다.

## 상태 확인

```bash
curl http://localhost:5000/health/live
```

DB 연결까지 확인하려면 다음 주소를 확인합니다.

```bash
curl http://localhost:5000/health/ready
```

Docker로 실행 중이라면 다음 주소로 확인합니다.

```bash
curl http://localhost:5001/health/live
curl http://localhost:5001/health/ready
```

정상 응답:

```json
{
  "status": "live"
}
```

Readiness 정상 응답:

```json
{
  "checks": {
    "database": "ok"
  },
  "status": "ready"
}
```
