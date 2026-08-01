# 향후 작업

브랜치 `backend`(40757f5) 기준. 백엔드 담당자 외 팀원도 읽을 수 있게 정리했다.

---

## 1. 원격 Supabase에 마이그레이션 2건 적용 — 지금 막혀 있음 🔴

### 적용해야 할 마이그레이션 (타임스탬프 순)

| 순서 | 파일 | 무엇을 만드나 | git 상태 | 재실행 |
|---|---|---|---|---|
| ① | `20260802010000_add_user_selected_adjustment_items.sql` | `review_items`에 `origin`·`document_clause_id` 컬럼 추가, 조정 요청 RPC 교체 | `backend`에 커밋됨 | 안전 |
| ② | `20260802020000_delete_discardable_contracts.sql` | `contract_deletion_records` 테이블, 계약 삭제 RPC 2개 | `feat/116/계약상태-삭제-백엔드-구현` | ⚠️ 위험 |

두 파일은 **서로 의존하지 않는다.** ②는 ①이 추가한 컬럼(`origin`, `document_clause_id`)을
참조하지 않으므로 순서가 뒤바뀌어도 실패하지 않는다. 다만 관례대로 타임스탬프 순으로
적용하는 것을 권한다.

### ① 조정 요청 — 지금 기능이 깨져 있는 원인

**증상.** 소상공인 화면에서 `대행사 전달 링크 만들기`가 실패한다. 화면에는
"요청을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."만 뜬다.

**원인.** `POST /api/v1/contracts/{id}/adjustment-requests`가 500으로 떨어지고,
서버 로그의 실제 원인은 다음과 같다.

```
PGRST202: Could not find the function
  public.create_adjustment_draft_with_audit(..., p_items, p_manual_items, ...)
hint: Perhaps you meant ... (..., p_owner_id, p_review_item_ids)
```

즉 **코드와 DB의 RPC 시그니처가 어긋났다.**

| | 파라미터 |
|---|---|
| `backend` 브랜치 코드가 호출하는 것 | `p_items`, `p_manual_items` (신) |
| 원격 DB에 실제로 있는 것 | `p_review_item_ids` (구) |

원격 `review_items`를 조회해 보면 `origin`·`document_clause_id` 두 컬럼이 모두 없다.
그 앞의 마이그레이션(성과 리포트 테이블 등)은 전부 적용되어 있다.

> **"나는 잘 되던데?"** 라고 느낀 사람은 옛 코드 + 옛 DB 조합이라 짝이 맞았던 것이다.
> 최신 `backend` 코드를 받은 사람만 이 오류를 만난다.

**사전 점검 결과 (확인 완료).**

- `add column if not exists`, `create unique index if not exists`,
  `drop function if exists`를 쓰므로 **중복 실행해도 깨지지 않는다.**
- 새 CHECK 제약이 추가되며 이는 **기존 행 전부에 적용된다.** 기존 행은
  `origin='ANALYSIS'` 기본값을 받으므로
  `cardinality(related_extracted_term_ids) between 1 and 11`을 만족해야 한다.
  현재 원격 데이터는 아래와 같아 **위반 행이 없다.**

  | 전체 행 | cardinality 1 | cardinality 2 | 위반 |
  |---|---|---|---|
  | 114 | 106 | 8 | **0건** |

  (이 확인을 건너뛰면 제약 추가에서 실패해 마이그레이션 전체가 롤백될 수 있다.)

**⚠️ 코드와 DB를 동시에 올려야 한다.** 이 마이그레이션은 옛 RPC 시그니처를 삭제한다.

```sql
drop function if exists public.create_adjustment_draft_with_audit(
  uuid, uuid, uuid, integer, uuid[], timestamptz   -- 옛 시그니처
);
```

따라서 적용하는 순간 **아직 옛 코드를 돌리는 사람은 똑같은 500 오류를 겪는다**
(방향만 반대). 팀 전체가 `backend` 최신 코드로 올라온 뒤 시점을 맞춰 적용한다.

### ② 계약 삭제 — 병행 작업이 추가한 마이그레이션

소상공인이 **외부로 나간 적 없는 계약**(`DRAFT`/`ANALYZING`/`REVIEW_REQUIRED`/
`NEGOTIATING`)만 완전 삭제할 수 있게 하는 기능이다. 가드와 하위 행 삭제를 한
트랜잭션으로 묶기 위해 RPC가 유일한 쓰기 경로다.

만드는 것:

- 테이블 `contract_deletion_records` — 삭제 이력(이전 상태, Storage 경로, 삭제 시각).
  RLS 켜고 `anon`·`authenticated` 권한 회수, `service_role`에만 부여.
- 함수 `delete_discardable_contract(p_owner_id, p_contract_id, p_deleted_at)`
- 함수 `mark_contract_storage_cleaned(p_owner_id, p_contract_id, p_cleaned_at)`

**사전 점검 결과 (확인 완료).**

- 이 RPC가 정리하는 하위 테이블 17개(`adjustment_requests`, `documents`,
  `review_items`, `audit_events`, `public_tokens`, `idempotency_records` 등)는
  **전부 원격에 이미 존재한다.**
- `contract_deletion_records`는 원격에 **없다** → 미적용 확정.
- 코드가 호출하는 파라미터와 함수 시그니처가 **일치한다.** (①과 같은 PGRST202 재발 없음)

**⚠️ ②는 재실행하면 실패한다.** ①과 달리 `create table`(`if not exists` 없음),
`create function`(`or replace` 없음)을 쓴다. 이미 적용된 DB에 다시 실행하면
`relation already exists` / `function already exists`로 멈춘다. 중간 실패로 부분 적용이
남지 않도록 **트랜잭션으로 감싸서 실행**하는 것을 권한다.

```sql
begin;
-- 20260802020000_delete_discardable_contracts.sql 내용 전체
commit;
```

**②는 `feat/116/계약상태-삭제-백엔드-구현` 브랜치에 있다.** 이 브랜치가 병합된 뒤에
DB에 적용해야 팀 전체의 코드와 DB가 같이 움직인다.

### 누가 실행해야 하나

이 DB(`mmtscaupxsaigqzhvvim`)의 **소유자가 실행해야 한다.** service-role 키만으로는
DDL을 실행할 수 없고(PostgREST는 스키마 변경을 지원하지 않음), DB 비밀번호는
저장소에 없다. Supabase 대시보드 → SQL Editor에 파일 내용을 붙여넣고 실행하면 된다.

### 함정: 링크된 프로젝트가 다르다

Supabase CLI로 `db push` 할 계획이라면 **먼저 link 대상을 확인해야 한다.**

| | 프로젝트 ref |
|---|---|
| `supabase/.temp/linked-project.json` (CLI가 링크한 곳) | `uvwmhrlbgfxkpyjarsij` |
| `apps/api/.env`의 `SUPABASE_URL` (앱이 실제 쓰는 곳) | **`mmtscaupxsaigqzhvvim`** |

이 상태로 `supabase db push` 하면 **엉뚱한 DB에 적용된다.** 반드시 재link 후 실행한다.

### 적용 후 검증

- [ ] `review_items`에 `origin`, `document_clause_id` 컬럼이 생겼는지 (①)
- [ ] `contract_deletion_records` 테이블이 생겼는지 (②)
- [ ] `대행사 전달 링크 만들기`가 링크를 반환하는지 (500이 사라졌는지)
- [ ] 계약 삭제가 동작하고, 발송·서명 이후 계약은 삭제가 거부되는지
- [ ] 서버 로그에 `PGRST202`가 더 이상 없는지

---

## 2. 프런트: 계약 삭제 버튼 구현 요청 (프런트 담당) 🙏

백엔드는 `feat/116/계약상태-삭제-백엔드-구현`에서 삭제 API를 구현했다. **화면에 붙이는
작업이 남았다.**

### API 계약

```
DELETE /api/v1/contracts/{contract_id}
→ 200 { "data": { "contract_id": "...", "deleted": true } }
```

- 인증: 소유자 Bearer 토큰(기존 소유자 API와 동일)
- 성공하면 계약과 하위 데이터(문서·분석·검토항목·조정요청·감사 이벤트 등)가
  **한 트랜잭션으로 완전히 삭제**된다. 되돌릴 수 없다.

### 삭제 가능한 계약만 버튼을 노출한다

외부로 나간 적 없는 계약만 삭제할 수 있다.

| 상태 | 삭제 |
|---|---|
| `DRAFT`, `ANALYZING`, `REVIEW_REQUIRED`, `NEGOTIATING` | ✅ 가능 |
| `READY_TO_SIGN`, `SIGNING`, `SIGNED`, `IN_PROGRESS`, `COMPLETED`, `RENEWAL_DUE` | ❌ 불가 |

조정 요청을 이미 발송했거나 서명 단계로 넘어간 계약은 서버가 거부한다. 프런트에서도
해당 상태에서는 버튼을 아예 보여주지 않는 편이 좋다.

### 화면 요구사항

- [ ] 대시보드 또는 계약 상세에 삭제 진입점 추가 (위 상태에서만 노출)
- [ ] **비가역 행동이므로 확인 모달 필수** — 기존 `components/ConfirmModal.tsx` 사용
      (설계 원칙 #5). 무엇이 함께 지워지는지 문구로 알린다.
- [ ] 삭제 후 대시보드로 이동하고 목록을 갱신
- [ ] 실패 시 오류 메시지 표시 (판정하지 않는 중립적 문구, 설계 원칙 #1)
- [ ] `lib/adapter.ts`의 `DataAdapter`에 `deleteContract` 추가 —
      `MockAdapter`/`ApiAdapter` 양쪽 구현

---

## 3. 재발 방지: 코드–DB 스키마 불일치 점검

위 문제는 "코드는 최신인데 DB만 뒤처진" 전형적인 사례다. 같은 일이 반복되기 쉽다.

- [ ] 마이그레이션을 추가한 PR에는 **원격 적용 여부**를 본문에 명시한다.
- [ ] 브랜치를 새로 받은 뒤 기능이 500으로 죽으면, 먼저 서버 로그에서 `PGRST202`
      (함수 없음) / `PGRST204`(컬럼 없음)를 확인한다. 이 두 코드는 거의 항상
      "마이그레이션 미적용"을 뜻한다.
- [ ] RPC 시그니처를 바꾸는 마이그레이션은 옛 함수를 drop하므로, 배포 순서를
      정해서 공지한다.

---

## 4. 대행사가 다른 기기에서 조정 링크를 열 수 있게 하기

### 남은 문제는 하나뿐

원래 외부 노출이 필요한 이유는 두 가지였는데, 그중 하나는 이미 해결됐다.

| 항목 | 상태 |
|---|---|
| 모두싸인 서명 상태·타임라인 갱신 | ✅ **해결됨** — 아래 5번의 조회 시점 동기화로 웹훅 없이도 갱신된다 |
| 대행사가 조정 요청 링크 열기 | ❌ 남음 — 링크가 `http://localhost:3000/...`이라 상대 기기에서 안 열린다 |

링크 주소는 `apps/api/.env`의 `PUBLIC_APP_BASE_URL`(기본값 `http://localhost:3000`)로
만들어진다. 그리고 대행사용 공개 페이지(`/r/[token]`)는 `"use client"`라
**대행사 브라우저가 API(8000)도 직접 호출**한다. 즉 프런트만 열어서는 부족하다.

### 선택지

| 방법 | 상대 위치 | 외부 노출 | 작업량 |
|---|---|---|---|
| A. 같은 Wi-Fi (LAN IP) | 같은 공간 | 없음(내부망만) | 설정 3곳 |
| B. Next `rewrites` 프록시 | A·D와 조합 | **포트 1개만** | config 추가 |
| C. 실제 배포(Vercel 등) | 어디든 | 공개 | 큼 |
| D. 터널(`cloudflared`) | 어디든 | 공개 | 중간 |

**B를 먼저 넣어두면 나머지가 전부 쉬워진다.** `next.config.ts`에 `/api/*`를 내부
`127.0.0.1:8000`으로 넘기는 rewrite를 두면, 대행사 브라우저는 **3000 하나만** 보면 된다.
API를 외부에 직접 노출하지 않아도 되고 CORS 설정도 필요 없어진다.

참고로 `next dev`는 이미 LAN에 바인딩되어 있으나(`Network: http://192.168.x.x:3000`),
`uvicorn`은 `127.0.0.1`만 바인딩한다. B 없이 A로 가려면 `--host 0.0.0.0`과
`CORS_ORIGINS` 추가가 필요하다.

### 터널(D)로 갈 경우 체크리스트

- [ ] `cloudflared tunnel --url http://localhost:3000` (B 적용 시 이것 하나면 충분)
- [ ] `apps/api/.env` → `PUBLIC_APP_BASE_URL`, `CORS_ORIGINS`
- [ ] `apps/frontend/.env.local` → `NEXT_PUBLIC_API_BASE_URL`
- [ ] 두 서버 재시작 (`NEXT_PUBLIC_*`는 빌드 시 인라인되므로 재시작 필수)
- [ ] 무료 터널은 **재시작마다 주소가 바뀐다.** 바뀌면 위 설정을 다시 맞춘다.
- [ ] 데모가 끝나면 터널을 닫는다. 주소를 아는 사람은 누구나 접근할 수 있다.

> 모두싸인 웹훅 등록은 이제 **필수가 아니다.** 등록하면 실시간성이 좋아질 뿐이고,
> 등록하려면 URL은 `{API 공개 주소}/api/v1/webhooks/modusign`, 커스텀 헤더
> `X-Modusign-Webhook-Secret`에 `MODUSIGN_WEBHOOK_SECRET` 값을 넣는다.
> 비었거나 다르면 `401`로 거부하며, 서명 없는 웹훅은 절대 수락하지 않는다.

---

## 5. 참고: 서명 상태 동기화 동작 방식

웹훅이 도달하지 못해도 화면이 영구히 멈추지 않도록 **조회 시점 보정**이 들어가 있다.

- `app/services/signature_reconciliation.py`의 `SignatureReconciler`가, 서명이 종결
  상태(`COMPLETED`/`ABORTED`/`FAILED`)가 아니면 모두싸인에 현재 상태를 조회해
  웹훅과 **동일한 멱등 RPC** `apply_modusign_document_status`로 반영한다.
  멱등이므로 반복 호출해도 감사 이벤트가 중복 생성되지 않는다.
- 적용 지점: `GET /contracts/{id}/signature`, `GET /contracts`(목록).
  목록에도 걸려 있어 **어떤 계약이 서명 완료됐는지 몰라도 대시보드만 새로고침하면**
  반영된다. 프런트 서명 화면은 진행 중일 때 4초 간격으로 재조회한다.

### 알아둘 점: 초안 ID ≠ 문서 ID

모두싸인의 embedded draft ID와, 그 초안을 발송해 만들어진 document ID는 **서로 다른
값이다.** 초안 ID로 `/documents/{id}`를 조회하면 403이 난다.

| | 값 예시 | 형식 |
|---|---|---|
| draft ID | `01KYZ1RCJ5SCBQ62HFTKWM26MF` | ULID |
| document ID | `dd655b70-8dcf-11f1-812b-d19927853d2e` | UUID |

document ID는 원래 웹훅만 알려준다. 그래서 웹훅이 없을 때는 초안 생성 시 붙여 둔
metadata(`aidos_signature_id` + HMAC `aidos_signature_proof`)로 최근 문서 목록에서
우리 서명을 되찾는다. 매칭은 ID 일치만으로는 인정하지 않고 **웹훅과 동일한 HMAC 검증**을
통과해야 한다.

---

## 6. 개발 환경 메모 — 반영이 안 되는 것 같을 때

`.claude/skills/dev-servers`의 `start.sh` / `stop.sh`로 두 서버를 함께 켜고 끈다.

**이 환경에서는 `--reload`를 믿지 말고, 코드를 고치면 서버를 재시작한다.**
같은 뿌리의 사고가 세 번 있었고 모두 "옛 코드를 서빙 중"이 원인이었다.

1. `uvicorn --reload`의 워커가 고아 프로세스로 남아 포트를 점유 → 옛 코드 서빙
2. 프런트가 `--reload` 없이 띄운 다른 포트(8001)의 서버를 바라봄 → 옛 코드 서빙
3. WatchFiles가 변경을 감지하지 못함(저장소 경로에 한글이 섞여 있음) → 옛 코드 서빙

세 경우 모두 **헬스체크는 200으로 정상**이라 알아채기 어렵다.

### 의심될 때 확인하는 법

파일이 아니라 **실행 중인 서버에 직접 묻는다.**

```bash
curl -s localhost:8000/openapi.json | grep -o "adjustment-copy/polish"
```

기대하는 라우트가 없으면 서버가 옛 코드다. 프런트가 어느 API를 보는지도 함께 확인한다
(`apps/frontend/.env.local`의 `NEXT_PUBLIC_API_BASE_URL`).

현재 스크립트는 이 사고들을 막도록 고쳐져 있다.

- `stop.sh`는 포트 점유 프로세스를 **트리째**(`taskkill //F //T`) 종료한다.
- `start.sh`는 포트가 이미 사용 중이면 **시작을 거부한다.**
  (예전에는 그냥 진행해서, 옛 서버가 헬스체크에 200을 답해 정상으로 보였다.)
