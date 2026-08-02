import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (relativePath) =>
  readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("performance adapter covers upload, extraction, confirmation, correction, and aggregate read", async () => {
  const adapter = await source("src/lib/adapter.ts");
  const apiAdapter = adapter.slice(adapter.indexOf("class ApiAdapter"));

  for (const method of [
    "getContractPerformance",
    "uploadPerformanceReport",
    "extractPerformanceReport",
    "confirmPerformanceReport",
  ]) {
    assert.match(apiAdapter, new RegExp(`async ${method}\\(`), `${method} must use ApiAdapter`);
  }

  assert.match(apiAdapter, /\/performance-reports`/);
  assert.match(apiAdapter, /encodeURIComponent\(reportId\)\}\/extract/);
  assert.match(apiAdapter, /expected_revision: input\.expectedRevision/);
  assert.match(apiAdapter, /correction_reason: input\.correctionReason/);
  assert.match(apiAdapter, /"Idempotency-Key": crypto\.randomUUID\(\)/);
  assert.match(adapter, /adSpend: data\.ad_spend/);
  assert.match(adapter, /clicks: data\.clicks/);
  assert.match(adapter, /missingPerformanceCandidate\(\)/);
  assert.match(adapter, /metric_items: data\.metricItems\.map/);
  assert.match(adapter, /Array\.isArray\(data\.metric_items\) && data\.metric_items\.length > 0/);
  assert.match(adapter, /await sha256Hex\(file\) === DEMO_PERFORMANCE_REPORT_SHA256/);
  assert.match(adapter, /데모 모드에서는.*샘플만 분석할 수 있어요/);
});

test("mock performance extraction only accepts the exact fictitious demo report", async () => {
  const [adapter, fixture] = await Promise.all([
    source("src/lib/adapter.ts"),
    readFile(new URL(
      "../../../fixtures/demo/performance-reports/브릿지웨이브_7월_광고리포트.pdf",
      import.meta.url,
    )),
  ]);
  const expectedHash = createHash("sha256").update(fixture).digest("hex");

  assert.match(adapter, new RegExp(`DEMO_PERFORMANCE_REPORT_SHA256[^]*${expectedHash}`));
  assert.match(adapter, /throw new PublicApiError\(\s*422,\s*"VALIDATION_ERROR"/);
});

test("performance page uses evidence-backed API data and keeps inquiry delivery manual", async () => {
  const page = await source("src/app/contracts/[id]/performance/page.tsx");

  assert.match(page, /adapter\.getContractPerformance/);
  assert.match(page, /adapter\.uploadPerformanceReport/);
  assert.match(page, /adapter\.extractPerformanceReport/);
  assert.match(page, /adapter\.confirmPerformanceReport/);
  assert.match(page, /candidate\.sourcePage/);
  assert.match(page, /candidate\.sourceText/);
  assert.match(page, /candidate\.confidence/);
  // QA 결과 '계약서를 기준으로 확인해요' 안내 카드는 중복이라 삭제했다(재추가 방지).
  assert.doesNotMatch(page, /계약서를 기준으로 확인해요/);
  assert.match(page, /border-2 border-dashed border-neutral300/);
  assert.match(page, /① 대행사 리포트 올리기/);
  assert.match(page, /광고 성과와 관련 없는 파일은 분석하지 않습니다/);
  assert.match(page, /데모 모드에서는 \{DEMO_PERFORMANCE_REPORT_FILE_NAME\} 샘플만 분석합니다/);
  assert.match(page, /setCorrectionReason/);
  assert.match(page, /oldestUnfinishedReport\(data\.reports\)/);
  assert.match(page, /sort\(\(left, right\) => left\.period\.localeCompare\(right\.period\)\)/);
  assert.match(page, /suggestedUploadPeriod\(data\.reports\)/);
  assert.match(page, /!activeReport \|\| working === "uploading" \|\| working === "extracting"/);
  assert.match(page, /Boolean\(working\) \|\| !period \|\| !file/);
  assert.match(page, /working === "uploading"[^]*"리포트 올리는 중…"/);
  assert.match(page, /working === "extracting"[^]*"숫자 읽는 중…"/);
  assert.match(page, /activeReport\?\.status === "UPLOADED" && !working/);
  assert.match(page, /리포트 확인을 마치면 다음 월을 등록할 수 있어요/);
  assert.match(page, /기존 기록을\s*덮어쓰지 않고 새 버전으로 남습니다/);
  assert.match(page, /문의 문안은 자동 발송되지/);
  assert.match(page, /id="obligation"/);
  assert.match(page, /id="reports"/);
  assert.ok(page.indexOf('id="obligation"') < page.indexOf('id="reports"'));
  assert.match(page, /function ManagementAccordion/);
  assert.match(page, /aria-expanded=\{open\}/);
  assert.match(page, /openSections\.obligation/);
  assert.match(page, /openSections\.reports/);
  assert.match(page, /\[section\]: !openSections\[section\]/);
  assert.match(page, /\.\.\.current, \[targetId\]: true/);
  assert.match(page, /obligation\.status === "PENDING" \|\| obligation\.status === "SUBMITTED"/);
  assert.match(page, /if \(activeReport\) setOpenSections/);
  assert.doesNotMatch(page, /바로가기 ↓/);
  assert.match(page, /window\.location\.hash\.slice\(1\)/);
  assert.match(page, /openSectionsFromUrl/);
  assert.match(page, /syncOpenSectionsToUrl\(nextSections\)/);
  assert.match(page, /openIds\.join\(","\)/);
  assert.match(page, /hidden=\{!open\}/);
  assert.match(page, /onRetry=\{retryObligationLoad\}/);
  assert.match(page, /onClick=\{retryPerformanceLoad\}/);
  assert.match(page, /const single = points\.length === 1/);
  assert.match(page, /single \? "justify-center"/);
  assert.match(page, /new MutationObserver/);
  assert.match(page, /<ConfirmModal/);
  assert.match(page, /setPendingDecision\("APPROVED"\)/);
  assert.match(page, /setPendingDecision\("DISPUTED"\)/);
  assert.match(page, /이후 화면에서 되돌릴 수 없어요/);
  assert.match(page, /hasInquiry=\{Boolean\(performance\?\.inquiryDrafts\.length\)\}/);
  assert.doesNotMatch(page.slice(page.indexOf("function StepFlow")), /"증빙 확인"/);
  assert.doesNotMatch(page, /화면 목업 · 개발 예정/);
  assert.doesNotMatch(page, /const JULY_POSTS/);
});

test("performance metric editor keeps six defaults, dynamic rows, and deterministic derived values", async () => {
  const [page, adapter] = await Promise.all([
    source("src/app/contracts/[id]/performance/page.tsx"),
    source("src/lib/adapter.ts"),
  ]);
  const definitions = adapter.slice(
    adapter.indexOf("export const PERFORMANCE_BASE_METRICS"),
    adapter.indexOf("export function calculatePerformanceCtr"),
  );
  let previous = -1;
  for (const definition of [
    'key: "ad_spend", label: "집행 광고비", unit: "KRW"',
    'key: "impressions", label: "노출 수", unit: "COUNT"',
    'key: "clicks", label: "클릭 수", unit: "COUNT"',
    'key: "ctr", label: "CTR", unit: "PERCENT"',
    'key: "cpc", label: "CPC", unit: "KRW"',
    'key: "published_content_count", label: "게시물 수", unit: "COUNT"',
  ]) {
    const index = definitions.indexOf(definition);
    assert.ok(index > previous, `${definition} must keep its default order`);
    previous = index;
  }

  assert.match(page, /type MetricForm = MetricFormItem\[\]/);
  assert.match(page, /const updateMetric =/);
  assert.match(page, /const removeMetric =/);
  assert.match(page, /const addMetric =/);
  assert.match(page, /\+ 지표 추가/);
  assert.match(page, /replaceAll\("-", "_"\)/);
  assert.match(page, /maxLength=\{50\}/);
  assert.match(page, /readOnly=\{derived\}/);
  assert.match(page, /verificationStatus === "NOT_FOUND"/);
  assert.match(page, /리포트에서 읽지 못한 값 \{manualEntryKeys\.size\}개/);
  assert.match(page, /requiresManualEntry[^]*"직접 입력해주세요"/);
  assert.match(page, /METRIC_UNIT_OPTIONS\.map/);
  assert.match(page, /form\.length === 0/);
  assert.match(page, /seenKeys/);
  assert.match(page, /seenLabels/);
  assert.match(page, /unit === "KRW" \|\| unit === "COUNT"/);
  assert.match(page, /if \(value < 0\)/);
  assert.match(page, /likes: 0/);
  assert.match(page, /comments: 0/);
  assert.match(page, /metricItems,/);
  assert.match(adapter, /Math\.round\(\(clicks \/ impressions\) \* 10_000\) \/ 100/);
  assert.match(adapter, /Math\.round\(adSpend \/ clicks\)/);
  assert.match(adapter, /createPerformanceBaseMetricItems\(\{/);
  assert.match(adapter, /contractId !== DEMO_CONTRACT_ID/);
  assert.match(adapter, /obligationByContract/);
  assert.match(adapter, /간판 최종 시안과 설치 사진/);
  assert.doesNotMatch(page, /label: "좋아요"|label: "댓글"|label: "저장"/);
});

test("aggregate performance and integrated obligation use live adapter data", async () => {
  const [aggregate, contractPage, format, statTile] = await Promise.all([
    source("src/app/performance/page.tsx"),
    source("src/app/contracts/[id]/performance/page.tsx"),
    source("src/lib/format.ts"),
    source("src/components/StatTile.tsx"),
  ]);

  assert.match(aggregate, /adapter\.getDashboard/);
  assert.match(aggregate, /adapter\.getContractPerformance/);
  assert.match(aggregate, /월별 광고효과 추이 — 전체 계약 합계/);
  assert.match(aggregate, /<MonthlyChart months=\{months\}/);
  assert.match(aggregate, /총 광고비/);
  assert.match(aggregate, /총 노출/);
  assert.match(aggregate, /총 클릭/);
  assert.match(aggregate, /전체 CTR/);
  assert.match(aggregate, /전체 CPC/);
  assert.match(aggregate, /총 게시물/);
  assert.match(aggregate, /<SectionTitle>계약별 성과<\/SectionTitle>/);
  assert.match(aggregate, /<SectionTitle>짚어볼 점<\/SectionTitle>/);
  assert.doesNotMatch(aggregate, /const CONTRACTS|화면 목업 · 개발 예정|reportDemo/);
  assert.match(contractPage, /누적 광고비/);
  assert.match(contractPage, /누적 노출/);
  assert.match(contractPage, /누적 클릭/);
  assert.match(contractPage, /전체 CTR/);
  assert.match(contractPage, /전체 CPC/);
  assert.match(contractPage, /누적 게시물/);
  assert.match(contractPage, /compactWon\(totals\.adSpend\)/);
  assert.match(contractPage, /compactCount\(totals\.impressions\)/);
  assert.match(contractPage, /compactCount\(totals\.posts, "건"\)/);
  const summaryCards = contractPage.slice(
    contractPage.indexOf("③ 확인한 광고효과 한눈에 보기"),
    contractPage.indexOf("월별 노출 추이"),
  );
  assert.equal(summaryCards.match(/fitValue/g)?.length, 6);
  assert.match(format, /100_000_000/);
  assert.match(format, /10_000/);
  assert.match(format, /unit: "억"/);
  assert.match(format, /unit: "만"/);
  assert.match(statTile, /card min-w-0/);
  assert.match(statTile, /whitespace-nowrap/);
  assert.match(statTile, /if \(length >= 10\) return "text-lg"/);
  assert.doesNotMatch(contractPage, /누적 반응|전체 반응률/);
  assert.match(contractPage, /adapter\.getObligation/);
  assert.doesNotMatch(contractPage, /adapter\.createObligationEvidenceLink/);
  assert.match(contractPage, /adapter\.reviewObligation/);
  assert.match(contractPage, /사장님 이행 체크/);
  assert.match(contractPage, /증빙 URL은 선택 사항/);
  assert.match(contractPage, /obligation\.status === "SUBMITTED"/);
  assert.match(contractPage, /\["PENDING", "SUBMITTED"\]\.includes/);
});
