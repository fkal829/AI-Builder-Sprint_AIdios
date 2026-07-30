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

## 문서 업로드·원문 접근·이해조건 mock 모드

기본 `SUPABASE_MODE=mock`은 외부 Supabase 없이 4.1 문서 업로드와 4.2 원문 임시
접근, 4.3 이해조건 저장을 확인하기 위한 로컬 전용 모드입니다. `.env.example`의
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
