# 가상 광고효과 리포트

16.2 리포트 업로드와 16.3 Upstage·Solar 지표 추출 흐름을 검증하기 위한 가상 대행사
월간 리포트입니다. 실제 업체·인물·연락처·계정 데이터는 포함하지 않습니다.

## 파일

- `브릿지웨이브_7월_광고리포트.pdf`: API에 업로드할 검색 가능한 PDF
- `expected-extraction.json`: 기대 추출값, 확인 payload, 서버 파생값
- `generate_report.py`: 동일한 PDF를 다시 만드는 생성기
- `assets/`: 가상 게시물에 사용하는 AI 생성 카페 이미지 2장

샘플은 프론트엔드 광고효과 화면과 같은 `2026-07` 값을 사용합니다. 추출 대상은
`impressions`, `likes`, `comments`, `reach`, `saves`, `shares`,
`follower_net_change`, `published_content_count` 8개뿐입니다. 문의·예약·구매 수는
소유자가 직접 확인해 입력하며, 반응률은 서버가 확인된 원본 정수로 계산합니다.

PDF는 실제 대행사 클라이언트 보고서에서 자주 쓰는 16:9 가로형 6쪽 덱으로 구성했습니다.

1. 브랜드 표지와 보고 기간
2. 8개 월간 KPI 및 전월 대비 요약
3. 콘텐츠별 노출과 반응 구성
4. 게시물 이미지와 콘텐츠별 성과
5. 운영 메모와 다음 달 제안
6. 데이터 범위·지표 정의·가상 데이터 고지

2쪽을 추출 기준 페이지로 사용합니다. 다른 페이지의 게시물별 숫자는 2쪽 월간 총계와
일치하며, 성과 판정·전환율·CPA·ROAS·매출 기여도는 포함하지 않습니다.

## 구성 참고 자료

- [Meta Instagram Insights](https://www.facebook.com/help/instagram/788388387972460):
  조회, 도달, 반응 및 콘텐츠 단위 인사이트 정의
- [AgencyAnalytics Social Media Report Template](https://agencyanalytics.com/templates/reports/social-media):
  브랜드 표지, 요약, 추이, 상위 콘텐츠, 제안으로 이어지는 클라이언트 보고서 구조
- [Sprout Social Reporting Guide](https://sproutsocial.com/insights/social-media-reporting/):
  기간별 KPI, 콘텐츠 성과, 인사이트와 다음 액션 구성
- [SC Digital Monthly Report](https://scdigital.com/wp-content/uploads/2020/12/Monthly-Digital-Report.pdf):
  실제 다페이지 대행사 리포트의 KPI·차트·상위 게시물 배치 사례

## 재생성

저장소 루트에서 실행합니다.

```bash
apps/api/.venv/bin/python fixtures/demo/performance-reports/generate_report.py
```

기본 글꼴은 Windows의 맑은 고딕을 사용합니다. 다른 환경에서는 아래 환경 변수로
한글 TTF/TTC 글꼴 경로를 지정할 수 있습니다.

```bash
DANDI_KOREAN_FONT_REGULAR=/path/to/regular.ttf \
DANDI_KOREAN_FONT_BOLD=/path/to/bold.ttf \
apps/api/.venv/bin/python fixtures/demo/performance-reports/generate_report.py
```

## API 사용 순서

1. `period=2026-07`, `file=@브릿지웨이브_7월_광고리포트.pdf`로 16.2 업로드 API를 호출합니다.
2. 응답의 `report_id`로 16.3 추출 API를 호출합니다.
3. 응답 후보를 `expected-extraction.json`의 8개 값 및 근거 문구와 비교합니다.
4. 소유자 확인 단계에서 `expected_confirmation_payload`를 기준으로 값을 확인합니다.
5. 계약에 `월 4건` 근거가 `VERIFIED`로 존재할 때만 게시물 2건 부족 신호를 확인합니다.


> 로컬 `mock` Upstage 어댑터는 업로드한 PDF 본문을 실제로 파싱하지 않습니다. 이 PDF의
> 본문 기반 종단 추출은 `live` Upstage 모드에서 검증해야 합니다.
