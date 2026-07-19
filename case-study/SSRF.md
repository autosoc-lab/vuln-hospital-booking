## 4. Capital One — SSRF + IMDSv1 침해사고
 

### 4.1 개요
 
2019년 7월 29일 미국 대형 은행 **Capital One**에서 **1억 600만 명** 이상의 고객 개인정보가 유출된 사실이 밝혀졌다. 피해액은 약 1억 5,000만 달러에 달한다.
 
공격자는 Capital One이 AWS 위에서 운영하는 웹 애플리케이션의 **방화벽(WAF) 설정 취약점(SSRF)**을 악용해, EC2 인스턴스 메타데이터 서비스(IMDSv1, `http://169.254.169.254`)에 접근했다. IMDSv1은 별도 인증 없이 누구든 해당 엔드포인트에 요청을 보내면 IAM 임시 자격 증명을 반환하는 구조였다. 탈취한 자격 증명으로 S3 버킷에 접근하여 민감 데이터를 대량 유출했다.
 
AWS는 "AWS는 설계된 대로 동작했으며, 해당 사고는 클라우드 서버 자체 취약점이 아니라 방화벽 설정 오류가 원인"이라고 밝혔다. (공유 책임 모델)
 
- **사고 발생**: 2019년 7월 29일
- **피해 규모**: 1억 600만 명 개인정보 유출, 1억 5,000만 달러 손실
- **유출 정보**: 이름·주소·생년월일 등 신상정보, 신용점수·한도·예금잔액 등 금융정보, 14만 명 사회보장번호, 8만 개 계좌번호, 2016~2018년 23일간 거래내역
- **공격자 접근 수단**: Tor Browser + VPN
---
 
### 4.2 공격 흐름
 
```
[1] 공격 대상 선정 및 초기 접근
    - Tor Browser + VPN을 이용한 익명 접근
    - Capital One 웹 애플리케이션(WAF) 탐색
      ↓
[2] SSRF 취약점 악용
    - WAF의 잘못된 방화벽 설정을 통해 서버를 내부 요청 프록시로 악용
    - 서버가 외부 입력값을 검증 없이 내부 URL로 전달
      ↓
[3] EC2 IMDS(IMDSv1) 접근 → IAM 임시 자격 증명 탈취
    - IMDSv1 엔드포인트: http://169.254.169.254/latest/meta-data/iam/security-credentials/
    - 요청 예시:
      curl http://example.com/?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/ISRM-WAF-Role
    - 응답으로 AccessKeyId, SecretAccessKey, Token 반환
      ↓
[4] 탈취한 자격 증명을 로컬 AWS CLI에 등록
    - aws configure 명령으로 ~/.aws/credentials에 등록
    - aws sts get-caller-identity로 자격 증명 유효성 확인
      ↓
[5] S3 버킷 목록 조회 및 데이터 탈취
    - aws s3 ls --profile example (버킷 목록 열거)
    - aws s3 sync s3://{bucket_name} [로컬 경로] (버킷 전체 동기화)
      ↓
[6] 1억 600만 명 고객 개인정보 대량 유출
```
 
**사고의 근본 원인:**
- 외부 입력값을 검증 없이 서버에 전달하는 SSRF 취약점
- IMDSv1은 토큰 인증 없이 누구나 `169.254.169.254`에 요청 가능
- `ISRM-WAF-Role`에 S3 접근 권한이 과도하게 부여됨 (최소 권한 원칙 미준수)
- S3 버킷 암호화 미적용 및 접근 로그 모니터링 부재
---
 
### 4.3 MITRE ATT&CK 매핑
 
| 순서 | 전술 | 기법 ID | 기법명 | 적용 내용 |
|------|------|---------|--------|-----------|
| 1 | Reconnaissance | T1595.002 | Active Scanning: Vulnerability Scanning | Capital One 웹 애플리케이션 엔드포인트 및 SSRF 가능 지점 탐색 |
| 2 | Initial Access | T1190 | Exploit Public-Facing Application | WAF 방화벽 설정 취약점(SSRF) 악용으로 초기 접근 |
| 3 | Defense Evasion | T1090 | Proxy | Tor Browser + VPN을 통한 공격자 IP 익명화 |
| 4 | Credential Access | T1552.005 | Unsecured Credentials: Cloud Instance Metadata API | IMDSv1(`169.254.169.254`) 접근으로 EC2 IAM 임시 자격 증명 탈취 |
| 5 | Privilege Escalation | T1078.004 | Valid Accounts: Cloud Accounts | 탈취한 IAM 임시 자격 증명(`ISRM-WAF-Role`)으로 AWS CLI 인증 |
| 6 | Discovery | T1619 | Cloud Storage Object Discovery | `aws s3 ls`로 S3 버킷 목록 열거 |
| 7 | Collection | T1530 | Data from Cloud Storage | S3 버킷 내 고객 개인정보 수집 |
| 8 | Exfiltration | T1537 | Transfer Data to Cloud Account | `aws s3 sync`로 버킷 전체 데이터 로컬 다운로드 |
 
---
 
### 4.4 대응 방안
 
**즉각 대응**
 
1. 침해된 IAM 임시 자격 증명(`ISRM-WAF-Role`) 즉시 폐기 및 관련 IAM Role 비활성화
2. AWS CloudTrail 로그에서 해당 자격 증명의 `s3:ListBuckets`, `s3:GetObject`, `s3:Sync` 이력 전수 확인
3. 유출된 S3 버킷 범위 및 접근된 객체 목록 특정
4. 영향받은 고객 범위 파악 후 법적 신고 및 이해관계자 통보
**취약점 제거**
 
- **SSRF 방어**: 외부 입력값을 URL로 사용하는 모든 경로에 서버 측 URL 검증 적용, 내부 IP 대역(`169.254.0.0/16`, `10.0.0.0/8` 등)으로의 요청 차단
- **IMDSv1 → IMDSv2 강제 전환**: EC2 메타데이터 서비스를 IMDSv2(토큰 기반 세션 인증)로 전환하면 SSRF를 통한 자격 증명 탈취 원천 차단
```bash
  aws ec2 modify-instance-metadata-options \
    --instance-id i-xxxxxxxxx \
    --http-tokens required \
    --http-put-response-hop-limit 1
```
- **IAM 최소 권한 원칙 적용**: `ISRM-WAF-Role`에 S3 접근 권한이 필요한지 재검토, 불필요한 권한 제거
- 각 애플리케이션·EC2 인스턴스·Auto Scaling Group에 **고유한 IAM Role** 부여 (역할 공유 금지)
- S3 버킷 데이터 **서버 측 암호화(SSE-S3 또는 SSE-KMS) 활성화**
**모니터링 강화**
 
- **CloudTrail 활성화** 및 S3 데이터 이벤트 로깅 설정
- `169.254.169.254`로 향하는 비정상 트래픽 탐지 규칙 적용
- 비정상적인 S3 대량 다운로드(`sync`, `GetObject` 반복 호출) 알림 설정
- **AWS GuardDuty** 활성화 — 비정상 자격 증명 사용 및 S3 접근 패턴 자동 탐지
- 허가된 IP 또는 VPC 엔드포인트에서만 S3 접근이 가능하도록 버킷 정책 제한
**사후 조치**
 
- 전체 IAM 자격 증명 주기적 감사 및 미사용 키·역할 제거
- 웹 애플리케이션 정기 SSRF 취약점 점검 (DAST, 침투 테스트)
- 클라우드 책임 분담 모델(Shared Responsibility Model) 기반 보안 정책 재수립
- 사고 대응 플레이북 정비 및 유출 시 고객 통보 절차 마련