# CTD OCR Grading Backend Architecture

## 목표

이 백엔드는 영어 서술형 답안지를 학생 1명, PDF 1페이지 단위로 분리 처리한다. 핵심 원칙은 OCR 단계와 채점 단계를 물리적으로 분리해서, OCR 모델이 학생 문장을 고치지 못하게 하는 것이다.

## 처리 흐름

1. 조교가 반, 폰스캔 PDF, 총 문항 수, 문항별 강사 코멘트를 업로드한다.
2. API 서버가 시험과 `grading_jobs` 레코드를 만들고 Redis Queue(RQ)에 작업 ID를 넣는다.
3. 별도 워커가 작업 ID를 받아 PDF를 페이지별 PNG로 렌더링한다.
4. 각 페이지를 독립 submission으로 만들고 병렬 처리한다.
5. OCR 모델은 이미지에서 `raw_ocr_text`만 JSON으로 복원한다.
6. 채점 모델은 OCR JSON과 강사 코멘트/모범답안/루브릭을 받아 점수와 피드백을 만든다.
7. 서버는 채점 모델이 `raw_ocr_text`를 바꾸면 즉시 원본 OCR 값으로 되돌리고 `MODEL_ATTEMPTED_TO_MUTATE_RAW_OCR` 플래그를 남긴다.
8. 대시보드 API는 랭킹, 검수 필요 목록, 학생 성장세를 제공한다.
9. 문자 초안은 `sms_messages`에 저장하고, 발송 시 SOLAPI 카카오 알림톡 API에 접수한다.

## A/B/C/D 피드백 정책

- A: 90-100점. 표현 정밀도, 더 세련된 문장, 심화 학습 방향.
- B: 75-89점. 특정 문법/어순 약점과 바로 풀 보강 문제.
- C: 60-74점. 문장 프레임 재구성, 핵심 개념 재학습.
- D: 60점 미만. 짧고 직접적인 보강, 검수 우선순위 높음.

추천: 등급만 쓰기보다 `needs_human_review`를 별도로 두는 편이 좋다. 예를 들어 B등급이어도 `[Unrecognizable]`이 있거나 OCR 누락이 있으면 검수 대상으로 올려야 한다.

## DB 핵심 테이블

- `exams`: 업로드된 시험 회차와 원본 PDF.
- `instructor_comments`: 문항별 강사 코멘트, 모범답안, 루브릭, 교재/페이지, 보강 파트.
- `grading_jobs`: PDF 처리 작업 상태.
- `submissions`: 페이지 단위 학생 답안. 원본 OCR JSON과 검수 수정 JSON을 분리 보관한다.
- `students`: 학생 기본 정보. 문자 발송 확장 시 전화번호 연결.
- `sms_messages`: 카카오 알림톡 draft, provider 접수 ID, 발송 상태, 오류 기록.

## 운영 컴포넌트

- Postgres: 기본 영속 DB. `DATABASE_URL=postgresql+asyncpg://...`
- Redis Queue(RQ): 채점 작업 큐. API 서버는 enqueue만 하고, 워커가 `JobRunner.process_job`을 실행한다.
- SOLAPI 카카오 알림톡: `draft -> queued -> failed` 상태를 저장한다. delivery webhook 연동 시 `sent` 확정 상태를 추가 갱신한다.

## 확장 포인트

- 문자 발송 웹훅: SOLAPI 발송 결과 웹훅을 받아 `SmsMessage.status`를 `sent/failed`로 확정한다.
- 사이트 교체: 프론트가 바뀌어도 `/api/v1/jobs`, `/api/v1/submissions`, `/api/v1/dashboard/*` 계약은 유지된다.
