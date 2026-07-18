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
