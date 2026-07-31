# 안심홍보계약 API

계약 상태 전환, 결정론적 계산, AI 분석 orchestration, Supabase 저장, 모두싸인 연동을 담당하는 FastAPI 앱입니다.

## 실행

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## 구현 위치

- HTTP 요청·응답: `app/api/v1/endpoints`
- Pydantic 스키마: `app/schemas`
- 유스케이스·상태 규칙: `app/services`
- Upstage·모두싸인·Supabase: `app/adapters`
- DB 접근 계약: `app/repositories`

라우터에서 외부 API를 직접 호출하거나 계약 상태를 직접 변경하지 않습니다.

## 문서 업로드·원문 접근·이해조건·분석 mock 모드

기본 `SUPABASE_MODE=mock`은 외부 Supabase 없이 4.1 문서 업로드와 4.2 원문 임시
접근, 4.3 이해조건 저장, 4.4 분석 시작을 확인하기 위한 로컬 전용 모드입니다. `.env.example`의
데모 owner·contract와 Bearer 토큰이 메모리에 시드되며 production에서는 mock 모드로
기동할 수 없습니다.

```bash
curl -X POST \
  http://localhost:8000/api/v1/contracts/00000000-0000-4000-8000-000000000041/documents \
  -H "Authorization: Bearer local-demo-owner-token" \
  -F "type=CONTRACT" \
  -F "file=@sample.pdf;type=application/pdf"
```

업로드 응답의 `data.id`를 아래 `{document_id}`에 넣습니다.

```bash
curl -i \
  "http://localhost:8000/api/v1/contracts/00000000-0000-4000-8000-000000000041/documents/{document_id}/access?source_page=1" \
  -H "Authorization: Bearer local-demo-owner-token"
```

4.3 이해조건 5문항도 같은 데모 계약에 저장할 수 있습니다.

```bash
curl -X PUT \
  http://localhost:8000/api/v1/contracts/00000000-0000-4000-8000-000000000041/understood-terms \
  -H "Authorization: Bearer local-demo-owner-token" \
  -H "Content-Type: application/json" \
  -d '{
    "duration_text": "1년",
    "monthly_amount": 500000,
    "total_amount": 6000000,
    "refund_text": "중도해지 시 일부 환불",
    "termination_text": "중도해지 가능",
    "source_type": "USER_MEMORY"
  }'
```

- mock 모드에서 이해조건은 API 프로세스 메모리에 계약당 한 건으로 저장되며 재시작하면
  초기화됨
- live 모드에서는 `save_understood_term_with_audit` RPC로 소유권 확인·upsert·감사
  이벤트를 원자적으로 처리
- 3.6 재계약 의사는 D-30 만료, D-14 해지 통보기한, D-7 자동갱신 검토 구간에서만
  저장할 수 있으며 동일 선택 재시도는 기존 `decided_at`을 유지함
- live 모드에서는 `save_renewal_decision_with_audit` RPC가 선택 변경과
  `RENEWAL_DECISION_SAVED` 감사 이벤트를 원자적으로 저장함
- `RENEW_WITH_CHANGES`는 이전 거절·원안 유지 검토 항목 ID만 반환하며 선택만으로 계약
  상태, 새 계약·문서·조정·서명을 자동 변경하거나 생성하지 않음
- 4.2 응답에는 `Cache-Control: no-store`, 300초 유효 `access_url`,
  `expires_at`, 요청한 `source_page`가 포함됨
- mock `access_url`은 같은 API 프로세스의 메모리 원문을 실제로 반환하며 프로세스
  재시작 또는 300초 경과 후에는 404
- `SUPABASE_MOCK_STORAGE_ACCESS_BASE_URL`은 브라우저에서 API에 접근하는 로컬 base
  URL에 맞춰 설정
- 기본 업로드 제한: 파일당 20 MiB, PDF 100페이지
- 계약서·제안서·견적서: PDF
- 메시지 선택 자료: PDF, PNG, JPEG, UTF-8 text
- live 모드: `SUPABASE_MODE=live`와 서버 전용 Supabase URL·service-role key가
  필요하며 Supabase private bucket의 실제 signed URL을 발급
- 원본은 private bucket에 저장하며 응답과 로그에 Storage 경로를 노출하지 않음

이해조건 저장 후 업로드 응답의 문서 ID와 새 UUID 멱등 키로 분석을 시작합니다.

```bash
curl -X POST \
  http://localhost:8000/api/v1/contracts/00000000-0000-4000-8000-000000000041/analysis \
  -H "Authorization: Bearer local-demo-owner-token" \
  -H "Idempotency-Key: 10000000-0000-4000-8000-000000000001" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "{document_id}",
    "supporting_document_ids": []
  }'
```

최초 응답은 `202 QUEUED`이며 백그라운드 작업이 Document Parse, 구조화 추출,
최대 2회의 Evaluator Loop, 원문 근거 검증, Solar 항목별 설명·3종 문구 생성을
수행합니다. 같은 멱등 키와 같은 요청은 최초 `202` 응답을 재생하고, 다른 요청은
`409 IDEMPOTENCY_CONFLICT`로 거부합니다. mock 분석 결과도 `source_page`,
`source_text`, `confidence` 필드를 유지하며 찾지 못한 값의 원문 필드는 `null`입니다.

## Upstage live 모드

`UPSTAGE_MODE=live`와 서버 전용 `UPSTAGE_API_KEY`를 설정하면 다음 API를 사용합니다.

- Document Parse: `/v1/document-digitization`
- Universal Extraction: `/v1/information-extraction/chat/completions`
- Solar Chat: `/v1/chat/completions`

PDF는 문서 항목 하나로 보내고 Universal Extraction의 location 좌표를 Document Parse
요소에 다시 연결해 `source_page`와 `source_text`를 검증합니다. Upstage의 `high`,
`low` confidence는 각각 `0.9`, `0.4`로 정규화하며 `low`는 근거를 보존한
`NEEDS_CHECK`로 처리합니다. 이 값은 확률 보정값으로 해석하지 않습니다. 원문 위치를
검증하지 못한 값은 `MISSING_EVIDENCE`로 저장합니다.

Solar는 서버 규칙이 만든 누락·불일치·불명확 후보에 항목별 쉬운 설명과
원안 수용·절충·요청 문구만 붙입니다. 기본 모델은
`UPSTAGE_SOLAR_MODEL=solar-pro3`, timeout은
`UPSTAGE_SOLAR_TIMEOUT_SECONDS=120`입니다. 응답은 strict JSON Schema와
Pydantic으로 검증하며 잘못된 응답은 고정 문구로 대체하지 않고
`FAILED/ANALYSIS_SCHEMA_INVALID`로 처리합니다. mock의 Solar 문구는 실제 API
응답이 아닙니다.

## Modusign embedded-draft mode (C-7 API change)

The default `MODUSIGN_MODE=mock` never calls Modusign and is used by automated tests.
To enable a real no-template embedded draft, set `MODUSIGN_MODE=live` together with
`MODUSIGN_ACCOUNT_EMAIL` and `MODUSIGN_API_KEY` in the server-only `.env` file.
Set `MODUSIGN_EMBEDDED_REDIRECT_URL` to an HTTPS frontend URL only when users should return
there after final sending. The API creates an in-memory agreement PDF and calls
`POST /embedded-drafts`; it returns a short-lived editor URL but never sends a signing request.
The user must place signature fields and press send in the Modusign editor. Set
`AGREEMENT_PDF_FONT_PATH` to a Korean TTF font in non-Windows deployments. Do not commit the
`.env` file or log signer contact values, agreement contents, or the embedded editor URL.

## Supabase live 준비

`SUPABASE_MODE=live`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`는 실행 중인 API의
Auth·DB·Storage 접근에 사용합니다. service-role key만으로 DDL 마이그레이션을 실행할
수는 없으므로 새 원격 프로젝트는 먼저 `supabase/migrations`를 날짜 순서로 적용해야
합니다.

live 소유자 API의 Bearer 값은 Supabase Auth가 발급한 실제 사용자 access token이어야
합니다. `DEMO_BEARER_TOKEN`과 `DEMO_OWNER_ID`는 mock 전용이며 live에서 계약의
`owner_id`로 사용할 수 없습니다.

Supabase CLI를 사용하는 경우 저장소 루트에서 프로젝트를 로그인·연결한 뒤 적용합니다.

```bash
supabase login
supabase link --project-ref <project-ref>
supabase db push
```

4.4에는 `20260730200000_add_analysis_pipeline.sql`이 추가되며 `AnalysisTask`,
`ExtractedTerm`, `ReviewItem`, 대표 `Obligation`과 분석 시작·완료·실패 감사
트랜잭션을 생성합니다.
4.5의 `GET /api/v1/contracts/{contract_id}/analysis`는 추가 상태 변경 없이 소유자
계약에서 가장 최근에 생성된 `AnalysisTask` 한 건을 반환합니다. 진행 중 작업은
`result=null`, 완료 작업은 원문 근거가 포함된 `Analysis`, 실패 작업은 허용된
`error_code`를 반환합니다.
4.6의 `PATCH /api/v1/contracts/{contract_id}/review-items/{item_id}`는
`UNREVIEWED`·`SELECTED` 항목에서만 사용자 선택을 저장합니다. `ACCEPT`는
`RESOLVED`, `COMPROMISE`·`REQUEST`는 `SELECTED`로 바꾸며, 같은 선택의 반복 저장은
감사 이벤트를 중복 생성하지 않습니다. `SENT` 이후 항목은 수정할 수 없습니다.
원본 bucket은 `contracts`, `public=false`여야 합니다.
