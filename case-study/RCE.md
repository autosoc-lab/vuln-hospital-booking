 ## 1. 패키지 취약점을 이용한 RCE 공격 시나리오
 
### 1.1 개요
 
HTML 문서를 PDF로 변환하는 웹 서비스에서 오픈소스 패키지 **ReportLab 3.6.12**의 취약점(CVE-2023-33733)을 악용한 원격 코드 실행(RCE) 공격 시나리오다.
 
공격자는 PDF 변환 API의 색상(`text_color`) 필드에 조작된 Python 표현식을 삽입한다. 취약한 버전의 ReportLab은 해당 값을 `toColor()` 함수로 처리하는 과정에서 임의 Python 코드를 실행한다. 그 결과 웹 애플리케이션 프로세스 권한으로 셸 명령이 실행되고, 시스템 정보 수집 및 내부 서버로의 HTTP 콜백이 발생한다.
 
- **CVE**: CVE-2023-33733
- **취약 버전**: ReportLab 3.6.12 이하
- **패치 버전**: ReportLab 3.6.13 (`ast.parse()` 기반 제한 파서로 교체)
- **대상 엔드포인트**: `POST /api/pdf/render`
---
 
### 1.2 공격 흐름
 
```
[1] 공격자가 PDF 변환 API 기능 확인 및 정상 요청 기준선 파악
      ↓
[2] text_color 필드에 조작된 Python 표현식 삽입하여 요청 전송
      ↓
[3] Flask 서버가 입력을 ReportLab toColor() 함수에 전달
      ↓
[4] 취약한 ReportLab이 입력을 평가하면서 Python 코드 실행
      ↓
[5] 웹 프로세스(gunicorn/python)가 셸(sh) 자식 프로세스 생성
      ↓
[6] id, hostname, uname 등 시스템 정보 수집
      ↓
[7] /tmp/rce_lab/rce_success.txt, system_info.txt 표식 파일 생성
      ↓
[8] 내부 수집 서버(collector:9000)로 HTTP POST 콜백 전송
      ↓
[9] SIEM이 웹 요청 + 셸 실행 + 파일 생성 + 비정상 아웃바운드 연결 연관 분석
      ↓
[10] SOAR가 공격 IP 차단, 컨테이너 격리, 증적 수집 자동 수행
      ↓
[11] ReportLab 3.6.13 이상으로 패치 후 재배포 및 동일 공격 차단 검증
```
 
**예상 프로세스 트리:**
```
nginx → gunicorn → python → sh → id, hostname, uname
```
 
---
 
### 1.3 MITRE ATT&CK 매핑
 
| 순서 | 전술 | 기법 ID | 기법명 | 적용 내용 |
|------|------|---------|--------|-----------|
| 1 | Initial Access | T1190 | Exploit Public-Facing Application | 외부 노출된 PDF 변환 API의 패키지 취약점 악용 |
| 2 | Execution | T1059.006 | Command and Scripting Interpreter: Python | ReportLab 처리 과정에서 Python 코드 실행 |
| 3 | Execution | T1059.004 | Command and Scripting Interpreter: Unix Shell | Python 웹 프로세스가 셸을 실행하여 명령 수행 |
| 4 | Discovery | T1082 | System Information Discovery | 호스트 이름 및 운영체제 정보 수집 |
| 5 | Command and Control | T1071.001 | Application Layer Protocol: Web Protocols | 내부 수집 서버로 HTTP 콜백 전송 |
 
---
 
### 1.4 대응 방안
 
**즉각 대응**
- 공격 출발지 IP 임시 차단 (Nginx / 방화벽)
- 취약한 `/api/pdf/render` 엔드포인트 비활성화
- 대상 컨테이너 네트워크 격리 (삭제 전 증적 보존 우선)
- 관련 로그 보존 기간 연장 및 증적 수집 (프로세스 트리, 생성 파일 SHA-256, 네트워크 연결 목록, pip freeze 결과)
**취약점 제거**
- ReportLab 3.6.12 → **3.6.13 이상**으로 의존성 업데이트
- 수정된 의존성을 기반으로 컨테이너 이미지 **새로 빌드** (기존 컨테이너 직접 수정 금지)
- 외부 입력을 색상 처리 함수에 직접 전달하지 않도록 검증 로직 추가
- 허용 색상값을 화이트리스트(색상명 또는 HEX 형식)로 제한
**사후 조치**
- 의존성 버전 고정 및 정기 SCA(소프트웨어 구성 분석) 스캔
- SBOM 생성 및 관리
- 웹 애플리케이션의 셸 실행 차단 (seccomp, AppArmor 등)
- 애플리케이션 아웃바운드 통신 허용 목록 적용
- 취약점 경보 수신 채널 및 패치 절차 수립
---
 