# vuln-hospital-booking

자동화 SOC 플랫폼 실습을 위한 취약 병원 예약 웹 애플리케이션입니다.

## 개발 서버 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

브라우저에서 `http://localhost:5000`으로 접속합니다.

## Docker로 실행

```bash
docker compose up --build
```

브라우저에서 `http://localhost:5000`으로 접속합니다.

## 상태 확인

```bash
curl http://localhost:5000/health/live
```

정상 응답:

```json
{
  "status": "live"
}
```
