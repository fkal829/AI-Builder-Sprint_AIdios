# 아키텍처와 파일 배치

## 런타임 경계

```text
사용자 브라우저
    ↓
apps/frontend (Next.js)
    ↓ HTTP / JSON
apps/api (FastAPI)
    ├─ Upstage Adapter
    ├─ Solar Review Service
    ├─ Modusign Adapter
    └─ Supabase Repository / Storage
```

웹은 화면 상태와 사용자 확인을 담당하고, 계약 상태 전환·계산·외부 API 호출은 API가 담당합니다.

## 웹

```text
apps/frontend/
├── app/
│   ├── (owner)/             # 소상공인 전용 화면
│   ├── public/              # 토큰 기반 대행사 무가입 화면
│   ├── globals.css
│   ├── layout.tsx
│   └── page.tsx
├── components/
│   ├── features/            # 계약·검토·조율·서명·이행 단위 UI
│   └── ui/                  # 제품 의미가 없는 공용 UI
├── lib/
│   ├── api/                 # FastAPI 클라이언트
│   └── contracts/           # 상태 표시와 프런트 전용 규칙
└── types/                   # 프런트 소비 타입
```

페이지에서 직접 외부 서비스를 호출하지 않습니다. 공개 페이지는 URL 토큰만 API에 전달하고 개인정보를 보관하지 않습니다.

## API

```text
apps/api/app/
├── api/v1/                  # HTTP 라우터
├── adapters/                # Upstage·Modusign·Supabase 구현
├── core/                    # 설정·enum·공통 오류
├── repositories/           # 영속성 인터페이스
├── schemas/                 # Pydantic 입출력 스키마
├── services/                # 분석·검토·조율·서명 유스케이스
└── main.py
```

라우터는 입력 검증과 응답 변환만 담당합니다. 외부 응답을 제품 상태로 변환하는 로직은 Adapter 또는 Service에 둡니다.

## 구현 순서

1. 대표 PDF와 정답 JSON을 고정합니다.
2. 업로드 → 추출 → 원문 근거 표시의 수직 흐름을 완성합니다.
3. 검토 규칙과 조항 카드를 추가합니다.
4. 공개 조정 응답과 합의서를 연결합니다.
5. 모두싸인, 타임라인, 이행 한 건, 만료 계산을 연결합니다.

현재 골격은 경계를 먼저 고정한 상태입니다. 실제 테이블과 공개 API가 바뀌면 `packages/contracts`와 이 문서를 함께 갱신합니다.
