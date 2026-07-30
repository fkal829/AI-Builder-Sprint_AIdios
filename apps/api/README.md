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

## 문서 업로드 mock 모드

기본 `SUPABASE_MODE=mock`은 외부 Supabase 없이 4.1 문서 업로드를 확인하기 위한
로컬 전용 모드입니다. `.env.example`의 데모 owner·contract와 Bearer 토큰이 메모리에
시드되며 production에서는 mock 모드로 기동할 수 없습니다.

```bash
curl -X POST \
  http://localhost:8000/api/v1/contracts/00000000-0000-4000-8000-000000000041/documents \
  -H "Authorization: Bearer local-demo-owner-token" \
  -F "type=CONTRACT" \
  -F "file=@sample.pdf;type=application/pdf"
```

- 기본 업로드 제한: 파일당 20 MiB, PDF 100페이지
- 계약서·제안서·견적서: PDF
- 메시지 선택 자료: PDF, PNG, JPEG, UTF-8 text
- live 모드: `SUPABASE_MODE=live`와 서버 전용 Supabase URL·service-role key 필요
- 원본은 private bucket에 저장하며 응답과 로그에 Storage 경로를 노출하지 않음
