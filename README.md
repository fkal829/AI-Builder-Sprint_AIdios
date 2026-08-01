# 단디계약

부산 관광상권 소상공인을 위한 AI 광고대행 계약 CLM입니다.

> 읽지 못한 계약을 읽어주고, 하지 못한 말을 대신해준다.

## MVP 흐름

`계약서 업로드 → 조건 추출 → 불일치·누락 검토 → 조정 요청 → 상대방 응답 → 수정 계약서 업로드·대조 → 모두싸인 → 산출물 증빙 → 광고효과 기록·대조 → 만료·재계약 확인`

광고효과 기록·대조(기획안 6.14)는 P2입니다. 백엔드 16.2 리포트 업로드, 16.3
Upstage·Solar 지표 추출, 16.4 사용자 확정·정정, 16.5 계약 대조·조회까지 구현했습니다.
로컬 FastAPI 실제 TCP·live Supabase Auth/Storage/PostgreSQL·Upstage Parse·
Solar를 함께 거친 16.2~16.5 수직 E2E도 통과했습니다. 배포 환경 검증은 별도입니다.

## 저장소 구조

```text
.
├── apps/
│   ├── frontend/            # 소상공인·대행사 반응형 웹
│   └── api/                 # 계약·AI·전자서명 FastAPI
├── packages/
│   └── contracts/           # 프런트/백엔드가 공유할 API·JSON 스키마
├── supabase/
│   └── migrations/          # PostgreSQL 스키마 변경 이력
├── fixtures/
│   ├── demo/                # 발표용 가상 데이터
│   └── evaluation/          # AI 고정 평가 데이터 10건
└── docs/                    # 제품 범위·아키텍처·대회 안내
```

세부 경계와 파일 배치 원칙은 [docs/architecture.md](docs/architecture.md), 공통 HTTP·데이터
규칙은 [docs/api-data-contract.md](docs/api-data-contract.md)를 참고하세요.

## 로컬 실행

요구 사항:

- Node.js 22.13 이상
- Python 3.12 이상

웹:

```bash
cd apps/frontend
cp .env.example .env.local
npm install
npm run dev
```

API:

```bash
cd apps/api
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

기본 주소:

- 웹: `http://localhost:3000`
- API 문서: `http://localhost:8000/docs`
- 상태 확인: `http://localhost:8000/api/v1/health`

## 개발 원칙

- 원문 근거가 없는 AI 결과는 확정값으로 표시하지 않습니다.
- 금액·기간·위약금·상태 전환은 일반 코드로 검증합니다.
- 외부 API는 Adapter 뒤에 두고 `mock`과 `live`를 환경변수로 구분합니다.
- 발송·조정 결과·수정 계약서 대조·서명·이행 승인은 항상 사용자가 최종 확인합니다.
- 데모 데이터에는 실제 개인정보를 넣지 않습니다.

대회 공통 안내는 [docs/hackathon-guide.md](docs/hackathon-guide.md)에 보관했습니다.
