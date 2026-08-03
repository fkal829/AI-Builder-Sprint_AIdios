# 가상 광고성과 리포트

16.2 리포트 업로드와 16.3 Upstage·Solar 지표 추출 흐름을 검증하기 위한 현재 형식의
가상 대행사 월간 리포트입니다. 문서 안의 업체·인물·연락처·URL·성과 수치는 모두
시연용이며 실제 개인정보나 운영 데이터가 아닙니다.

## 파일

- `브릿지웨이브_2026-07_광고성과리포트.pdf`: API에 업로드할 검색 가능한 3페이지 PDF
- `expected-extraction.json`: 현재 10개 후보의 기대값·근거 범위·확인 payload

PDF SHA-256은
`4ba0dbc5d1c2283b21feb81e668a098e1f0a0c5fff65c8c7943a9362ea255f3f`입니다.

## 리포트 구성

1. 광고주·대행사·기간, 총괄 6개 KPI, 광고비 집행 내역
2. 매체별 광고비·노출·클릭과 반응 지표, 게시물별 성과
3. 나머지 게시물, 플랫폼별 도달·팔로워 순증, 운영 메모와 데이터 기준

현재 `performance-report-metrics-v3`의 10개 후보를 기준으로 검토합니다.

- 카드에 라벨과 값이 함께 있는 `ad_spend`, `impressions`, `clicks`,
  `published_content_count`는 직접 근거가 있는 기대값입니다.
- `likes`, `comments`, `saves`, `shares`는 표의 합계 행, `reach`는 Instagram 행에
  있습니다. 라벨과 값이 같은 짧은 원문 조각에 붙어 있지 않으므로 원문 행만 보존하고
  후보 값은 `null`, 상태는 `NEEDS_CHECK`로 두어 사용자가 직접 입력합니다.
- `follower_net_change`는 플랫폼별 값만 있고 전 매체 합계가 명시되지 않았습니다.
  세 값을 합산하거나 한 플랫폼을 전체 값으로 선택하지 않고 `NOT_FOUND`로 둡니다.
- CTR·CPC·반응률은 추출값을 신뢰하지 않고 확인된 원본 정수로 서버가 계산합니다.

## API 사용 순서

1. `period=2026-07`, `file=@브릿지웨이브_2026-07_광고성과리포트.pdf`로 16.2 업로드
   API를 호출합니다.
2. 응답의 `report_id`로 16.3 추출 API를 호출합니다.
3. 응답 후보를 `expected-extraction.json`의 10개 후보와 비교합니다.
4. `NEEDS_CHECK`와 `NOT_FOUND` 범위를 포함해 소유자가 원문을 확인합니다.
5. 확인값을 저장한 뒤 계약 근거와 월별 추이를 결정적 코드로 대조합니다.

> 로컬 `mock` Upstage Adapter는 업로드한 PDF 본문을 직접 파싱하지 않습니다. 새 PDF의
> 실제 Document Parse·Solar 결과는 명시적 live 실행 전까지 검증됐다고 기록하지 않습니다.
