# CTD 영어 서술형 OCR 채점 백엔드

강사별 수업 데이터가 분리되는 FastAPI 백엔드입니다. 조교가 폰스캔 PDF를 올리면 페이지 단위로 답안지를 이미지화하고, Gemini OCR 모델과 Gemini 채점 모델을 분리 호출해 학생 원문을 보존한 상태로 개인화 피드백을 생성합니다.

## 핵심 원칙

- OCR과 채점은 분리합니다. OCR 단계는 `raw_ocr_text`만 만들고 문장을 절대 고치지 않습니다.
- 채점 모델이 `raw_ocr_text`를 수정해 반환해도 서버가 원본 OCR 값으로 되돌립니다.
- 학생 피드백은 강사 말투를 목표로 합니다. 문항별 `diagnosis`, `correction_strategy`,
  `drill_recommendation`을 분리해 뭉뚱그린 AI식 총평을 줄입니다.
- AI식 표현이 감지되면 `feedback_quality_flags`와 답안별 audit flag가 붙어 검수 대상으로 올라갑니다.
- 강사는 `X-Instructor-Id` 기준으로 본인 수업의 학생, 시험, 답안지만 조회합니다.
- OCR 이름이 수업 명단에서 1명만 매칭되면 자동 연결합니다.
- 동명이인이 있으면 `student_match_status=ambiguous`와 후보 목록을 남기고, 사용자가 마지막에 누구의 답안지인지 선택합니다.
- 학생 삭제는 soft delete입니다. 명단과 자동 매칭에서는 빠지지만 과거 답안/발송 기록은 보존됩니다.

## 실행

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
docker compose up -d postgres redis
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

별도 터미널에서 채점 워커를 실행합니다. API 서버는 PDF를 큐에 넣고, 워커가 실제 OCR/채점을 처리합니다.

```powershell
.\\.venv\\Scripts\\Activate.ps1
python -m app.workers.run_rq_worker
```

`.env`에는 운영 기준 기본값이 들어 있습니다.

```env
DATABASE_URL=postgresql+asyncpg://ctd_ocr:ctd_ocr@localhost:5432/ctd_ocr
AI_PROVIDER=gemini
GEMINI_API_KEY="API 키를 입력하세요."
GEMINI_OCR_MODEL=gemini-3.5-flash
GEMINI_GRADING_MODEL=gemini-3.5-flash
QUEUE_PROVIDER=redis
MESSAGE_PROVIDER=solapi_kakao
SOLAPI_API_KEY="API 키를 입력하세요."
```

Gemini, Redis, 카카오 알림톡 없이 API 배선만 확인할 때는 `AI_PROVIDER=mock`, `QUEUE_PROVIDER=inline`, `MESSAGE_PROVIDER=mock`으로 실행합니다. `inline` 큐는 로컬 QA용이며 API 요청 안에서 채점을 끝낸 뒤 응답합니다.

## 기본 흐름

1. `POST /api/v1/instructors`로 강사를 만듭니다.
2. 이후 요청에는 `X-Instructor-Id: {instructor_id}` 헤더를 붙입니다.
3. `POST /api/v1/classes`로 학생 등록용 수업을 만듭니다.
4. `POST /api/v1/students`로 학생을 등록합니다. 수동 반이 없으면 `class_ids`는 비워도 됩니다.
5. `POST /api/v1/jobs`로 반 선택, PDF, 서술형 문항 총 개수, 문항별 강사 코멘트를 업로드합니다.
6. `GET /api/v1/jobs/{job_id}/submissions`에서 페이지별 채점 결과와 동명이인 후보를 확인합니다.
7. 동명이인이면 `POST /api/v1/submissions/{submission_id}/assign-student`로 학생을 확정합니다.
8. `POST /api/v1/submissions/{submission_id}/messages/draft`로 문자 초안을 만들고, 문자 연동 후 발송합니다.

## 주요 API

- `POST /api/v1/instructors`: 강사 생성
- `GET /api/v1/instructors`: 강사 목록
- `POST /api/v1/classes`: 현재 강사의 수업 생성
- `GET /api/v1/classes`: 현재 강사의 수업 목록
- `POST /api/v1/students`: 학생 등록
- `GET /api/v1/students`: 학생 목록
- `PATCH /api/v1/students/{student_id}`: 학생 정보 수정
- `DELETE /api/v1/students/{student_id}`: 학생 삭제
- `GET /api/v1/students/{student_id}/exams`: 학생별 시험 이력. 시험당 1개 요약
- `GET /api/v1/students/{student_id}/exams/{exam_id}/submissions`: 해당 시험 답안지 이미지 목록
- `PATCH /api/v1/exams/{exam_id}`: OCR 채점 후 시험 날짜 수정
- `POST /api/v1/jobs`: PDF 채점 작업 생성
- `GET /api/v1/jobs/{job_id}`: 작업 진행 상태
- `GET /api/v1/submissions/{submission_id}`: 답안지 이미지, OCR, 채점 상세
- `POST /api/v1/submissions/{submission_id}/assign-student`: 동명이인/미매칭 학생 수동 확정
- `POST /api/v1/submissions/{submission_id}/messages/draft`: 문자 초안 생성
- `POST /api/v1/messages/{message_id}/send`: SOLAPI 카카오 알림톡 발송 요청
- `GET /api/v1/dashboard/rankings?exam_id=...`: 시험 랭킹
- `GET /api/v1/dashboard/students/{student_id}/growth`: 학생 성장세

## 업로드 예시

`POST /api/v1/jobs`는 multipart form입니다.

- `class_id`: 선택한 반 ID. 기본 반으로 `전체 학생`, `예비고1`, `고1`, `고2`, `고3/N수`가 자동 생성됩니다.
- `pdf`: 폰스캔 PDF
- `question_count`: 서술형 문항 총 개수. 예: 5문항 시험지는 `5`
- `comments_json`: 문항별 강사 코멘트 JSON. `question_count`만큼 필요

```json
[
  {
    "question_number": 1,
    "comment": "어법끝 p.42 관계대명사 파트 보강",
    "model_answer": "The birds in a line ...",
    "rubric": "핵심 의미 0.6, 관계대명사 구조 0.2, 시제/수일치 0.2",
    "book_reference": "어법끝 p.42",
    "reinforcement_target": "관계대명사 who/which",
    "max_score": 1
  }
]
```

시험명은 `{업로드 날짜} {반 이름} 서술형`으로 자동 생성됩니다. 시험 날짜도 업로드 날짜로 자동 저장되며, OCR 채점 후 `PATCH /api/v1/exams/{exam_id}`로 수정할 수 있습니다.

학생이 일부 문항을 쓰지 않은 경우 해당 문항은 빈 답안으로 저장되고 자동 0점 처리됩니다. 예를 들어 5문항 시험에서 4개만 작성했다면 남은 1개는 틀린 문항으로 반영됩니다.

학생 등록 시 `grade_level`을 `예비고1`, `고1`, `고2`, `고3/N수` 중 하나로 넣으면 현재 학년도 기준 학년이 자동 계산됩니다. 학년도는 3월 시작 기준입니다. 예를 들어 2026학년도에 `고1`로 등록한 학생은 2027년 3월부터 조회 시 `고2`로 표시됩니다.

수동 반을 따로 운영하지 않는 강사는 학생 등록 때 `class_ids`를 비워도 됩니다. 학생은 자동으로 `전체 학생`과 현재 학년 반에 포함됩니다. `월수금 7시` 같은 별도 운영 반이 있으면 그때만 `class_ids`에 해당 반 ID를 넣습니다.

## 검증

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall app tests
```

## 카카오 알림톡 설정

카톡 발송은 SOLAPI 알림톡(ATA) 기준입니다. SOLAPI 콘솔에서 카카오 채널, 알림톡 템플릿을 승인받은 뒤 아래 값을 채웁니다.

- `SOLAPI_API_KEY`
- `SOLAPI_API_SECRET`
- `SOLAPI_SENDER_NUMBER`: 대체 문자 발송을 허용할 때 필요한 사전 등록 발신번호
- `SOLAPI_KAKAO_PF_ID`
- `SOLAPI_KAKAO_TEMPLATE_ID`
- `SOLAPI_KAKAO_BODY_VARIABLE`: 기본 `#{내용}`. 템플릿 문구에 이 치환 변수를 넣어두면 AI 피드백 본문이 이 변수로 들어갑니다.

실제 발송 요청이 SOLAPI에 접수되면 메시지 상태는 `queued`가 됩니다. 추후 delivery webhook을 붙이면 `sent/failed` 확정 상태로 갱신하면 됩니다.

## 운영 구성

기본 DB는 Postgres입니다. `docker-compose.yml`의 Postgres/Redis는 로컬 운영 확인용이고, 실제 서버에서는 관리형 Postgres와 Redis로 `DATABASE_URL`, `REDIS_URL`만 교체하면 됩니다.

채점 작업은 Redis Queue(RQ)로 들어갑니다. API 서버와 워커를 분리 실행해야 PDF 업로드 요청이 모델 처리 시간 때문에 오래 붙잡히지 않습니다.

답안지 이미지는 `/storage/...` 정적 URL로 제공됩니다. API 응답에는 서버 내부 보관 경로인 `image_path`와 브라우저 표시용 `image_url`이 함께 내려갑니다.
