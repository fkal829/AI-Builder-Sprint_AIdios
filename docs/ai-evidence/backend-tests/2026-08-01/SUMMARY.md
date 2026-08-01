# 2026-08-01 백엔드 테스트 검증 결과

## 결론

2026-08-01 기준 백엔드 전체 자동 검증은 **통과**했다. 전체 `pytest` 719건과 Ruff 정적
검사가 성공했고, 고정 가상 계약 10건 오프라인 평가도 선언된 목표를 모두 충족했다.

이번 실행은 `AUTOMATED_OFFLINE` 증빙이다. 실제 Upstage·Solar·Supabase 연동을 이번
명령에서 다시 호출한 결과가 아니며, 기존 live 결과는
[live-integration-summary.md](live-integration-summary.md)에서 별도로 확인한다.

## 실행 정보

| 항목 | 값 |
| --- | --- |
| 실행 시각 | 2026-08-01 18:20 KST |
| Git branch | `backend` |
| 검증 대상 commit | `5007bf1b80d5c1a529b8fd1965c2b34d471b30fa` |
| Python | `3.12.3` |
| pytest | `8.4.2` |
| Ruff | `0.16.0` |
| 외부 Adapter | `SUPABASE_MODE=mock`, `UPSTAGE_MODE=mock`, `MODUSIGN_MODE=mock` |
| 로컬 `.env` | 읽지 않음 (`env -i`, 저장소 루트 실행) |
| 생성 전 source worktree | clean |

## 자동 검증 결과

| 검증 | 결과 | 종료 코드 | 산출물 |
| --- | --- | ---: | --- |
| Ruff 전체 정적 검사 | 진단 0건 | 0 | [ruff-check.json](ruff-check.json) |
| 백엔드 전체 pytest | 719 passed, 0 failed, 0 errors, 0 skipped | 0 | [pytest-full.txt](pytest-full.txt), [pytest-junit.xml](pytest-junit.xml) |
| 고정 계약 10건 평가 | 모든 목표 통과 | 0 | [offline-evaluation.json](offline-evaluation.json) |

JUnit에 기록된 테스트 실행 시간은 39.253초이고, pytest 전체 명령의 보고 시간은
39.26초다. 제출 산출물에서 로컬 장치명은 `redacted`로 치환했으며 테스트 내용과 결과는
변경하지 않았다.

산출물 무결성은 [SHA256SUMS.txt](SHA256SUMS.txt)로 확인할 수 있다.

## B 담당 기능 검증 범위

전체 회귀 테스트 안에서 다음 B 담당 경계를 함께 검증했다.

- FastAPI 공통 응답·오류·request ID, 인증과 멱등성
- 계약 문서 업로드·private 접근·이해조건 5문항
- Upstage Parse·Extract 스키마, 최대 2회 Evaluator Loop, 원문 근거 연결
- Solar 쉬운 설명·3종 문구·역제안 비교와 안전 문구
- 대표 이행 항목, 증빙 링크·공개 제출·소유자 검토
- 광고효과 16.2 업로드, 16.3 추출, attempt 복구·감사·보안 경계
- OpenAPI·공유 JSON Schema·Pydantic·migration 정합성
- 고정 계약 10건의 오프라인 AI 평가

`pytest-junit.xml`에는 719개 테스트 케이스의 이름과 개별 실행 시간이 들어 있어 위 범위를
파일 단위로 추적할 수 있다.

## 고정 계약 10건 평가

| 지표 | 결과 | 목표 | 판정 |
| --- | ---: | ---: | --- |
| 핵심 필드 추출 정확도 | 96.67% (58/60) | 90% 이상 | 통과 |
| 근거 페이지 연결 정확도 | 96.36% (53/55) | 90% 이상 | 통과 |
| 필수 JSON 스키마 성공률 | 100.00% (10/10) | 100% | 통과 |
| 기간·총액 불일치 탐지율 | 100.00% (3/3) | 100% | 통과 |
| 근거 없는 확정 경고 | 0건 | 0건 | 통과 |
| 전체 기대 확인 신호 재현율 | 100.00% (16/16) | 참고값 | 재현 |

이 평가는 사람이 작성한 가상 계약과 오프라인 추출 snapshot의 회귀 결과다. 실제 모델
정확도나 운영 성능으로 해석하지 않는다.

## 재현 명령

```bash
# 저장소 루트에서 실행: 로컬 .env를 읽지 않도록 환경을 비운다.
env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PYTHONPATH=apps/api \
  PYTHONDONTWRITEBYTECODE=1 APP_ENV=local SUPABASE_MODE=mock \
  UPSTAGE_MODE=mock MODUSIGN_MODE=mock \
  apps/api/.venv/bin/python -m pytest \
  -c apps/api/pyproject.toml apps/api/tests --strict-config \
  -p no:cacheprovider -q --tb=short --color=no \
  --junitxml=docs/ai-evidence/backend-tests/2026-08-01/pytest-junit.xml

cd apps/api
.venv/bin/python -m ruff check . --no-cache --output-format=json \
  --output-file ../../docs/ai-evidence/backend-tests/2026-08-01/ruff-check.json

cd ../..
env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PYTHONPATH=apps/api \
  PYTHONDONTWRITEBYTECODE=1 APP_ENV=local SUPABASE_MODE=mock \
  UPSTAGE_MODE=mock MODUSIGN_MODE=mock \
  apps/api/.venv/bin/python -m evaluation --format json
```

## 제한사항

- 이번 실행에서는 외부 네트워크와 유료 API를 호출하지 않았다.
- 실제 PostgreSQL에 migration을 새로 적용하는 검증과 배포 FastAPI E2E는 포함하지 않았다.
- live 결과의 시점·모델·프롬프트·cleanup은 연결된 기존 live 증빙 문서 기준이다.
- 테스트 fixture는 모두 가상 데이터이며 실제 개인정보를 사용하지 않는다.
