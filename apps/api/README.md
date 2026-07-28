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
