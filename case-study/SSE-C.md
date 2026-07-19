## 3. Codefinger — AWS S3 SSE-C Ransomware 공격
 
### 3.1 개요
 
2025년 1월 13일 보안 회사 Halcyon의 RISE Team이 **Codefinger** 위협 그룹이 Amazon S3 버킷을 대상으로 랜섬웨어 캠페인을 수행 중임을 공개했다.
 
이 공격은 AWS의 취약점을 직접 악용하는 것이 아니라, AWS의 합법적 기능인 **SSE-C(Server-Side Encryption with Customer-Provided Keys)** 를 랜섬웨어 수단으로 전용한 것이다. 공격자는 외부에 노출된 IAM 자격 증명(Access Key ID + Secret Access Key)을 획득한 뒤 공격자 본인만 보유한 AES-256 키로 S3 객체를 재암호화한다. AWS는 SSE-C 요청을 처리할 때 키를 저장하지 않기 때문에 공격자의 키 없이는 복호화가 원천적으로 불가능하다. 추가로 S3 Lifecycle Policy를 설정해 7일 후 객체를 자동 삭제함으로써 피해자를 시간 압박 하에 놓는다.
 
- **공개 시점**: 2025년 1월 13일
- **최초 확인 피해 조직**: 최소 2곳 (Halcyon 고객사 아님)
- **암호화 알고리즘**: AES-256 (SSE-C)
- **복구 가능 여부**: 공격자 키 없이 불가
- **자동 삭제 유예 기간**: 암호화 후 7일
---
 
### 3.2 공격 흐름
 
```
[1] AWS 자격 증명 획득
    - GitHub 등 공개 저장소 하드코딩 키
    - 애플리케이션 설정 파일 misconfiguration
    - 다크웹 유통 유출 자격 증명
      ↓
[2] IAM 권한 확인
    - s3:GetObject / s3:PutObject 두 권한만으로 공격 가능
      ↓
[3] SSE-C 헤더를 이용한 S3 객체 재암호화
    - HTTP 헤더: x-amz-server-side-encryption-customer-algorithm: AES256
    - 공격자가 생성·보관하는 AES-256 키 사용
    - AWS는 키를 저장하지 않음 → CloudTrail에는 HMAC만 기록
      ↓
[4] S3 Lifecycle Policy 설정
    - 암호화된 객체에 7일 후 자동 삭제 정책 적용
    - 버저닝이 활성화되어 있어도 이전 버전까지 삭제 유도
      ↓
[5] 각 디렉터리에 랜섬 노트 삽입
    - Bitcoin 지갑 주소 + Client ID 포함
      ↓
[6] 몸값 요구 / 협박
    - 7일 내 미지불 시 데이터 영구 삭제
```
 
---
 
### 3.3 MITRE ATT&CK 매핑
 
| 순서 | 전술 | 기법 ID | 기법명 | 적용 내용 |
|------|------|---------|--------|-----------|
| 1 | Reconnaissance | T1593 | Search Open Websites/Domains | GitHub 등 공개 저장소에서 노출된 AWS 키 탐색 |
| 2 | Initial Access | T1078.004 | Valid Accounts: Cloud Accounts | 노출된 AWS IAM 액세스 키 사용 |
| 3 | Defense Evasion | T1550 | Use Alternate Authentication Material | 장기 자격 증명(액세스 키) 직접 사용으로 MFA 우회 |
| 4 | Discovery | T1619 | Cloud Storage Object Discovery | `s3:GetObject`로 버킷 내 객체 목록 확인 |
| 5 | Impact | T1486 | Data Encrypted for Impact | SSE-C AES-256으로 S3 객체 재암호화 |
| 6 | Impact | T1485 | Data Destruction | S3 Lifecycle Policy로 7일 후 객체 삭제 설정 |
| 7 | Impact | T1490 | Inhibit System Recovery | 버전 관리 우회, 기존 객체 덮어쓰기로 복구 방해 |
 
---
 
### 3.4 대응 방안
 
**즉각 대응**
 
1. 침해된 IAM 액세스 키 즉시 비활성화 및 삭제
2. AWS CloudTrail 로그에서 `s3:PutObject` + SSE-C 헤더(`x-amz-server-side-encryption-customer-algorithm`) 호출 내역 분석
3. 영향받은 S3 버킷의 **Lifecycle Policy 즉시 삭제** → 7일 자동 삭제 차단
4. AWS Support에 연락하여 `AWSCompromisedKeyQuarantineV2` 격리 정책 적용 요청
5. 피해 버킷 범위 및 암호화된 객체 목록 식별
**취약점 제거**
 
- 장기 액세스 키 사용 지양 → EC2 Instance Profile, Lambda Execution Role, IAM Roles Anywhere 등 **임시 자격 증명으로 전환**
- GitHub Actions, CI/CD 파이프라인에서 **OIDC 연동**으로 키 없이 AWS 인증
- AWS Secrets Manager를 통한 자격 증명 중앙 관리
- SSE-C 사용 원천 차단 — S3 버킷 정책 또는 SCP에 아래 Deny 조건 적용:
```json
{
  "Effect": "Deny",
  "Action": "s3:PutObject",
  "Resource": "arn:aws:s3:::your-bucket/*",
  "Condition": {
    "Null": {
      "s3:x-amz-server-side-encryption-customer-algorithm": "false"
    }
  }
}
```
 
**탐지 강화**
 
- **CloudTrail S3 데이터 이벤트 로깅 활성화** (기본 비활성)
- `x-amz-server-side-encryption-customer-algorithm` 헤더가 포함된 PutObject 이벤트 모니터링
- S3 Lifecycle Policy 생성·수정(`PutBucketLifecycle`) 이벤트에 대한 알림 설정
- **AWS GuardDuty 활성화** — 비정상적인 S3 접근 패턴 자동 탐지
**백업 및 복원력**
 
- **S3 Versioning + MFA Delete 활성화** (Lifecycle Policy에 의한 삭제도 방어)
- Cross-region 또는 Cross-account 복제본 유지 (공격자가 접근 불가한 별도 계정)
- 정기적인 복구 훈련으로 실제 복원 가능 여부 검증