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
