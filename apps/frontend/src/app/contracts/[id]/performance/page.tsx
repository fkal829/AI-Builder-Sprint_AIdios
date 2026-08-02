"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AppScreen } from "@/components/AppScreen";
import { Card, Disclaimer, SectionTitle } from "@/components/Bits";
import { LayerBlock } from "@/components/LayerBlock";
import { PublicLinkCard } from "@/components/PublicLinkCard";
import { StatTile } from "@/components/StatTile";
import { useAsync } from "@/lib/hooks";
import {
  adapter,
  calculatePerformanceCpc,
  calculatePerformanceCtr,
  createPerformanceBaseMetricItems,
  performanceMetricValue,
  PERFORMANCE_BASE_METRICS,
  type ContractPerformance,
  type LiveObligation,
  type PerformanceCanonicalMetricKey,
  type PerformanceConfirmedPayload,
  type PerformanceFlag,
  type PerformanceMetricItem,
  type PerformanceMetricKey,
  type PerformanceMetricUnit,
  type PerformanceReport,
} from "@/lib/adapter";

type EvidenceMetricField = {
  key: string;
  extractedKey: PerformanceMetricKey;
  label: string;
};

const EVIDENCE_METRIC_FIELDS: EvidenceMetricField[] = [
  { key: "ad_spend", extractedKey: "adSpend", label: "집행 광고비" },
  { key: "impressions", extractedKey: "impressions", label: "노출 수" },
  { key: "clicks", extractedKey: "clicks", label: "클릭 수" },
  {
    key: "published_content_count",
    extractedKey: "publishedContentCount",
    label: "게시물 수",
  },
];

type MetricFormItem = Omit<PerformanceMetricItem, "value"> & { value: string };
type MetricForm = MetricFormItem[];
type WorkingAction = "loading" | "uploading" | "extracting" | "saving" | null;

const CANONICAL_UNITS = new Map<string, PerformanceMetricUnit>(
  PERFORMANCE_BASE_METRICS.map((metric) => [metric.key, metric.unit] as const),
);
const DERIVED_METRIC_KEYS = new Set(["ctr", "cpc"]);
const METRIC_UNIT_LABELS = {
  KRW: "원",
  COUNT: "개수",
  PERCENT: "%",
  NUMBER: "숫자",
} satisfies Record<PerformanceMetricUnit, string>;
const METRIC_UNIT_OPTIONS = Object.entries(METRIC_UNIT_LABELS) as [
  PerformanceMetricUnit,
  string,
][];

function toFormItems(items: readonly PerformanceMetricItem[]): MetricForm {
  return applyDerivedMetrics(items.map((item): MetricFormItem => ({
    ...item,
    unit: CANONICAL_UNITS.get(item.key) ?? item.unit,
    value: item.value === null ? "" : String(item.value),
  })));
}

function emptyMetricForm(): MetricForm {
  return toFormItems(createPerformanceBaseMetricItems());
}

function rawMetricValue(form: MetricForm, key: string): number | null {
  const raw = form.find((item) => item.key === key)?.value.trim() ?? "";
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function applyDerivedMetrics(form: MetricForm): MetricForm {
  const ctr = calculatePerformanceCtr(
    rawMetricValue(form, "clicks"),
    rawMetricValue(form, "impressions"),
  );
  const cpc = calculatePerformanceCpc(
    rawMetricValue(form, "ad_spend"),
    rawMetricValue(form, "clicks"),
  );
  return form.map((item): MetricFormItem => {
    if (item.key === "ctr") {
      return { ...item, unit: "PERCENT", value: ctr === null ? "" : ctr.toFixed(2) };
    }
    if (item.key === "cpc") {
      return { ...item, unit: "KRW", value: cpc === null ? "" : String(cpc) };
    }
    return item;
  });
}

function formFromReport(report: PerformanceReport): MetricForm {
  if (report.currentRevision) {
    return toFormItems(report.currentRevision.confirmedPayload.metricItems);
  }
  return toFormItems(createPerformanceBaseMetricItems({
    ad_spend: report.extractedPayload?.adSpend.value ?? null,
    impressions: report.extractedPayload?.impressions.value ?? null,
    clicks: report.extractedPayload?.clicks.value ?? null,
    published_content_count: report.extractedPayload?.publishedContentCount.value ?? null,
  }));
}

function parseMetricForm(form: MetricForm): PerformanceConfirmedPayload {
  if (form.length === 0) throw new Error("하나 이상의 지표를 추가해주세요.");
  const seenKeys = new Set<string>();
  const seenLabels = new Set<string>();
  const metricItems = applyDerivedMetrics(form).map((item): PerformanceMetricItem => {
    const normalizedKey = item.key.trim().toLowerCase();
    if (seenKeys.has(normalizedKey)) throw new Error("지표 key는 중복될 수 없습니다.");
    seenKeys.add(normalizedKey);
    const label = item.label.trim();
    if (!label) throw new Error("지표 이름을 입력해주세요.");
    if (label.length > 50) throw new Error("지표 이름은 50자 이하로 입력해주세요.");
    const normalizedLabel = label.toLocaleLowerCase();
    if (seenLabels.has(normalizedLabel)) throw new Error("지표 이름은 중복될 수 없습니다.");
    seenLabels.add(normalizedLabel);
    const unit = CANONICAL_UNITS.get(item.key) ?? item.unit;
    const raw = item.value.trim();
    if (!raw) return { ...item, label, unit, value: null };
    const value = Number(raw);
    if (!Number.isFinite(value)) throw new Error(`${label} 값을 숫자로 입력해주세요.`);
    if ((unit === "KRW" || unit === "COUNT") && !Number.isSafeInteger(value)) {
      throw new Error(`${label}은 정수로 입력해주세요.`);
    }
    if (value < 0) {
      throw new Error(`${label}은 0 이상이어야 합니다.`);
    }
    return {
      ...item,
      label,
      unit,
      value,
    };
  });
  const impressions = performanceMetricValue(metricItems, "impressions");
  const publishedContentCount = performanceMetricValue(metricItems, "published_content_count");
  return {
    impressions: impressions ?? 0,
    likes: 0,
    comments: 0,
    reach: null,
    saves: null,
    shares: null,
    followerNetChange: null,
    publishedContentCount,
    inquiries: null,
    reservations: null,
    purchases: null,
    metricItems,
  };
}

function sumConfirmedMetric(
  points: ContractPerformance["confirmedSeries"],
  key: PerformanceCanonicalMetricKey,
): number | null {
  return points.reduce<number | null>((sum, point) => {
    const value = performanceMetricValue(point.confirmedPayload.metricItems, key);
    return sum === null || value === null ? null : sum + value;
  }, 0);
}

function defaultPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function PerformancePage() {
  const { id } = useParams<{ id: string }>();
  const [performance, setPerformance] = useState<ContractPerformance | null>(null);
  const [activeReport, setActiveReport] = useState<PerformanceReport | null>(null);
  const [form, setForm] = useState<MetricForm>(emptyMetricForm);
  const [period, setPeriod] = useState(defaultPeriod);
  const [file, setFile] = useState<File | null>(null);
  const [hasIssue, setHasIssue] = useState(false);
  const [issueNote, setIssueNote] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [working, setWorking] = useState<WorkingAction>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    adapter.getContractPerformance(id)
      .then((data) => {
        if (!alive) return;
        setPerformance(data);
        const unfinished = oldestUnfinishedReport(data.reports);
        if (unfinished) {
          setActiveReport(unfinished);
          setForm(formFromReport(unfinished));
        } else {
          setPeriod(suggestedUploadPeriod(data.reports));
        }
      })
      .catch((cause: unknown) => {
        if (alive) setError(errorMessage(cause, "광고효과 기록을 불러오지 못했습니다."));
      })
      .finally(() => {
        if (alive) setWorking(null);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  const reload = async () => {
    const data = await adapter.getContractPerformance(id);
    setPerformance(data);
    return data;
  };

  const uploadAndExtract = async () => {
    if (!file || working) {
      if (!file) setError("분석할 PDF 또는 이미지 파일을 선택해주세요.");
      return;
    }
    setError(null);
    try {
      setWorking("uploading");
      const uploaded = await adapter.uploadPerformanceReport(id, period, file);
      setActiveReport(uploaded);
      await reload();
      setWorking("extracting");
      const extracted = await adapter.extractPerformanceReport(id, uploaded.id);
      setActiveReport(extracted);
      setForm(formFromReport(extracted));
      await reload();
    } catch (cause) {
      setError(errorMessage(cause, "리포트를 분석하지 못했습니다."));
    } finally {
      setWorking(null);
    }
  };

  const retryExtraction = async () => {
    if (!activeReport || activeReport.status !== "UPLOADED" || working) return;
    setWorking("extracting");
    setError(null);
    try {
      const extracted = await adapter.extractPerformanceReport(id, activeReport.id);
      setActiveReport(extracted);
      setForm(formFromReport(extracted));
      await reload();
    } catch (cause) {
      setError(errorMessage(cause, "리포트 지표를 다시 추출하지 못했습니다."));
    } finally {
      setWorking(null);
    }
  };

  const saveConfirmation = async () => {
    if (!activeReport || working) return;
    setError(null);
    try {
      if (hasIssue && !issueNote.trim()) throw new Error("이상 있다고 기록할 내용을 적어주세요.");
      if (activeReport.revisionCount > 0 && !correctionReason.trim()) {
        throw new Error("정정 사유를 적어주세요.");
      }
      const confirmedPayload = parseMetricForm(form);
      setWorking("saving");
      await adapter.confirmPerformanceReport(id, activeReport.id, {
        expectedRevision: activeReport.revisionCount,
        confirmedPayload,
        hasIssue,
        issueNote: hasIssue ? issueNote.trim() : null,
        correctionReason: activeReport.revisionCount > 0 ? correctionReason.trim() : null,
      });
      const refreshed = await reload();
      const nextUnfinished = oldestUnfinishedReport(refreshed.reports);
      setActiveReport(nextUnfinished);
      setForm(nextUnfinished ? formFromReport(nextUnfinished) : emptyMetricForm());
      if (!nextUnfinished) setPeriod(suggestedUploadPeriod(refreshed.reports));
      setHasIssue(false);
      setIssueNote("");
      setCorrectionReason("");
      setFile(null);
    } catch (cause) {
      setError(errorMessage(cause, "확인한 지표를 저장하지 못했습니다."));
    } finally {
      setWorking(null);
    }
  };

  const startCorrection = (report: PerformanceReport) => {
    setActiveReport(report);
    setForm(formFromReport(report));
    setHasIssue(report.currentRevision?.flags.some(
      (flag) => flag.flagType === "OWNER_REPORTED_ISSUE",
    ) ?? false);
    setIssueNote(report.currentRevision?.flags.find(
      (flag) => flag.flagType === "OWNER_REPORTED_ISSUE",
    )?.issueNote ?? "");
    setCorrectionReason("");
    setError(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const latestConfirmedReportId = performance?.confirmedSeries.at(-1)?.reportId ?? null;

  return (
    <AppScreen
      title="이행·광고효과 관리"
      size="wide"
      backHref="/manage"
    >
      <div className="flex flex-col gap-5">
        <p className="text-[13px] leading-relaxed text-neutral700">
          대행사에게 받은 광고 리포트를 올려두면, 계약에서 약속한 조건대로 진행되고
          있는지 한눈에 확인하고 산출물 증빙까지 마무리할 수 있어요.
        </p>

        <StepFlow activeReport={activeReport} hasConfirmed={Boolean(performance?.confirmedSeries.length)} />

        <section className="flex flex-col gap-2">
          <SectionTitle>① 대행사 리포트 올리기</SectionTitle>
          <Card>
            <div className="flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-neutral300 bg-subtle px-6 py-8 text-center">
              <span className="text-3xl">📄</span>
              <div>
                <div className="text-[13px] font-bold text-ink">
                  월간 리포트나 인사이트 화면을 올려주세요
                </div>
                <div className="mt-1 text-[11px] text-neutral500">
                  PDF · 이미지 캡처 모두 괜찮아요
                </div>
              </div>
              <div className="grid w-full max-w-xl gap-3 sm:grid-cols-[150px_1fr]">
                <label className="text-left text-[11px] font-bold text-neutral700">
                  대상 월
                  <input
                    type="month"
                    value={period}
                    onChange={(event) => setPeriod(event.target.value)}
                    disabled={Boolean(working) || Boolean(activeReport)}
                    className="mt-1 block h-10 w-full rounded-lg border border-neutral300 bg-white px-3 text-[13px] text-ink disabled:opacity-50"
                  />
                </label>
                <label className="text-left text-[11px] font-bold text-neutral700">
                  PDF 또는 이미지
                  <input
                    type="file"
                    accept="application/pdf,image/png,image/jpeg"
                    onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                    disabled={Boolean(working) || Boolean(activeReport)}
                    className="mt-1 block h-10 w-full rounded-lg border border-neutral300 bg-white px-3 py-2 text-[12px] text-neutral700 file:mr-3 file:border-0 file:bg-transparent file:font-bold"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={uploadAndExtract}
                disabled={Boolean(working) || Boolean(activeReport) || !period || !file}
                className="h-10 rounded-lg bg-ink px-4 text-[13px] font-bold text-white hover:bg-ink/90 disabled:opacity-40"
              >
                {working === "uploading"
                  ? "업로드 중…"
                  : working === "extracting"
                    ? "숫자 읽는 중…"
                    : "리포트 올리고 숫자 읽기"}
              </button>
              {file && <p className="text-[11px] font-bold text-neutral700">선택됨 · {file.name}</p>}
              {activeReport && (
                <p className="text-[11px] font-bold text-brand800">
                  먼저 {activeReport.period} 리포트 확인을 마치면 다음 월을 등록할 수 있어요.
                </p>
              )}
            </div>
            <p className="mt-2 text-[11px] text-neutral500">
              원본은 비공개로 저장되며 월마다 한 건만 등록할 수 있어요. 분석 시작은 버튼을
              누른 뒤에만 실행됩니다.
            </p>
          </Card>
        </section>

        {/* 업로드·추출이 진행 중일 때는 위 카드의 버튼과 겹치므로, 추출이 실제로
            멈춰 있을 때(working이 없을 때)만 다시 시도 안내를 보여준다. */}
        {activeReport?.status === "UPLOADED" && !working && (
          <Card>
            <p className="text-[13px] font-bold text-ink">
              {activeReport.period} 리포트가 업로드됐지만 숫자 추출이 끝나지 않았어요.
            </p>
            <button
              type="button"
              onClick={retryExtraction}
              className="mt-3 h-10 rounded-lg bg-ink px-4 text-[13px] font-bold text-white"
            >
              지표 추출 다시 시도
            </button>
          </Card>
        )}

        {activeReport && activeReport.status !== "UPLOADED" && (
          <MetricConfirmation
            report={activeReport}
            form={form}
            setForm={setForm}
            hasIssue={hasIssue}
            setHasIssue={setHasIssue}
            issueNote={issueNote}
            setIssueNote={setIssueNote}
            correctionReason={correctionReason}
            setCorrectionReason={setCorrectionReason}
            working={working === "saving"}
            onSave={saveConfirmation}
            onCancel={activeReport.revisionCount > 0 ? () => setActiveReport(null) : undefined}
          />
        )}

        {working === "loading" && (
          <p className="py-8 text-center text-sm text-neutral500">광고효과 기록을 불러오는 중…</p>
        )}
        {error && (
          <p role="alert" className="rounded-lg border border-brand300 bg-brand50 px-4 py-3 text-[12px] font-bold text-brand800">
            {error}
          </p>
        )}

        {performance && (
          <PerformanceDashboard
            performance={performance}
            latestConfirmedReportId={latestConfirmedReportId}
            onCorrect={startCorrection}
          />
        )}

        <section className="flex flex-col gap-2">
          <SectionTitle>⑤ 산출물 증빙 확인</SectionTitle>
          <ObligationPanel contractId={id} />
        </section>

        <Disclaimer>
          확인 신호는 법률 판단이나 광고 성과 보장이 아닙니다. 문의 문안은 자동 발송되지
          않으며 사장님이 내용을 확인한 뒤 기존 메신저나 이메일로 직접 전달합니다.
        </Disclaimer>
      </div>
    </AppScreen>
  );
}

function MetricConfirmation({
  report,
  form,
  setForm,
  hasIssue,
  setHasIssue,
  issueNote,
  setIssueNote,
  correctionReason,
  setCorrectionReason,
  working,
  onSave,
  onCancel,
}: {
  report: PerformanceReport;
  form: MetricForm;
  setForm: (value: MetricForm) => void;
  hasIssue: boolean;
  setHasIssue: (value: boolean) => void;
  issueNote: string;
  setIssueNote: (value: string) => void;
  correctionReason: string;
  setCorrectionReason: (value: string) => void;
  working: boolean;
  onSave: () => void;
  onCancel?: () => void;
}) {
  const correcting = report.revisionCount > 0;
  const updateMetric = (
    key: string,
    patch: Partial<Pick<MetricFormItem, "label" | "value" | "unit">>,
  ) => {
    setForm(applyDerivedMetrics(form.map((item) => (
      item.key === key ? { ...item, ...patch } : item
    ))));
  };
  const removeMetric = (key: string) => {
    setForm(applyDerivedMetrics(form.filter((item) => item.key !== key)));
  };
  const addMetric = () => {
    setForm(applyDerivedMetrics([
      ...form,
      {
        key: `custom_${crypto.randomUUID().replaceAll("-", "_")}`,
        label: "새 지표",
        value: "",
        unit: "NUMBER",
      },
    ]));
  };
  return (
    <section className="flex flex-col gap-2">
      <SectionTitle>
        ② {correcting ? `${report.period} 확정값 정정` : "읽은 숫자와 원문 확인"}
      </SectionTitle>
      <Card>
        {report.extractedPayload && !correcting && (
          <div className="mb-4 grid gap-2 lg:grid-cols-2">
            {EVIDENCE_METRIC_FIELDS.map((field) => {
              const candidate = report.extractedPayload![field.extractedKey];
              return (
                <div key={field.key} className="rounded-lg border border-neutral200 bg-subtle p-3">
                  <div className="flex items-center justify-between gap-3">
                    <b className="text-[12px] text-ink">{field.label}</b>
                    <span className="text-[10px] font-bold text-brand700">
                      {candidate.verificationStatus === "NOT_FOUND"
                        ? "근거를 찾지 못함"
                        : `${candidate.verificationStatus === "NEEDS_CHECK" ? "확인 필요 · " : "근거 확인 · "}${Math.round(candidate.confidence * 100)}%`}
                    </span>
                  </div>
                  {candidate.sourceText ? (
                    <p className="mt-1 text-[11px] leading-relaxed text-neutral600">
                      {candidate.sourcePage}쪽 “{candidate.sourceText}”
                    </p>
                  ) : (
                    <p className="mt-1 text-[11px] text-neutral500">리포트 원문에서 확인하지 못했어요.</p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {form.map((item) => {
            const canonicalUnit = CANONICAL_UNITS.get(item.key);
            const derived = DERIVED_METRIC_KEYS.has(item.key);
            return (
              <div key={item.key} className="rounded-lg border border-neutral200 bg-white p-3">
                <div className="flex items-start gap-2">
                  <label className="min-w-0 flex-1 text-[10px] font-bold text-neutral500">
                    지표 이름
                    <input
                      value={item.label}
                      onChange={(event) => updateMetric(item.key, { label: event.target.value })}
                      maxLength={50}
                      disabled={working}
                      className="mt-1 h-9 w-full rounded-lg border border-neutral300 px-2.5 text-[12px] font-bold text-ink disabled:opacity-50"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => removeMetric(item.key)}
                    disabled={working}
                    className="mt-5 h-9 rounded-lg border border-neutral300 px-2.5 text-[11px] font-bold text-neutral500 disabled:opacity-40"
                  >
                    삭제
                  </button>
                </div>
                <div className="mt-2 grid grid-cols-[minmax(0,1fr)_5rem] gap-2">
                  <label className="text-[10px] font-bold text-neutral500">
                    값
                    <input
                      inputMode="decimal"
                      value={item.value}
                      onChange={(event) => updateMetric(item.key, { value: event.target.value })}
                      placeholder={derived ? "자동 계산" : "없으면 비워두기"}
                      readOnly={derived}
                      disabled={working}
                      className="mt-1 h-9 w-full rounded-lg border border-neutral300 px-2.5 text-[12px] font-bold text-ink read-only:bg-subtle disabled:opacity-50"
                    />
                  </label>
                  {canonicalUnit ? (
                    <div className="text-[10px] font-bold text-neutral500">
                      단위
                      <div className="mt-1 flex h-9 items-center rounded-lg border border-neutral200 bg-subtle px-2.5 text-[11px] text-neutral700">
                        {METRIC_UNIT_LABELS[canonicalUnit]}
                      </div>
                    </div>
                  ) : (
                    <label className="text-[10px] font-bold text-neutral500">
                      단위
                      <select
                        value={item.unit}
                        onChange={(event) => updateMetric(item.key, {
                          unit: event.target.value as PerformanceMetricUnit,
                        })}
                        disabled={working}
                        className="mt-1 h-9 w-full rounded-lg border border-neutral300 bg-white px-2 text-[11px] text-ink disabled:opacity-50"
                      >
                        {METRIC_UNIT_OPTIONS.map(([unit, label]) => (
                          <option key={unit} value={unit}>{label}</option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                {derived && (
                  <p className="mt-1.5 text-[10px] text-neutral500">
                    {item.key === "ctr"
                      ? "클릭 수 ÷ 노출 수 × 100을 소수 둘째 자리로 계산해요."
                      : "집행 광고비 ÷ 클릭 수를 1원 단위로 반올림해요."}
                  </p>
                )}
              </div>
            );
          })}
        </div>
        <button
          type="button"
          onClick={addMetric}
          disabled={working}
          className="mt-3 h-10 w-full rounded-lg border border-dashed border-brand400 bg-brand50 text-[12px] font-bold text-brand800 disabled:opacity-40"
        >
          + 지표 추가
        </button>

        <label className="mt-4 flex items-center gap-2 text-[12px] font-bold text-neutral700">
          <input
            type="checkbox"
            checked={hasIssue}
            onChange={(event) => setHasIssue(event.target.checked)}
            disabled={working}
          />
          숫자 외에도 대행사에 확인할 내용이 있어요
        </label>
        {hasIssue && (
          <textarea
            value={issueNote}
            onChange={(event) => setIssueNote(event.target.value)}
            maxLength={500}
            rows={3}
            placeholder="확인할 내용과 이유를 적어주세요."
            disabled={working}
            className="mt-2 w-full rounded-lg border border-neutral300 p-3 text-[12px] leading-relaxed text-ink disabled:opacity-50"
          />
        )}
        {correcting && (
          <label className="mt-4 block text-[11px] font-bold text-neutral700">
            정정 사유 *
            <input
              value={correctionReason}
              onChange={(event) => setCorrectionReason(event.target.value)}
              maxLength={500}
              placeholder="예: 리포트 원문을 다시 확인해 게시물 수를 바로잡음"
              disabled={working}
              className="mt-1 h-10 w-full rounded-lg border border-neutral300 px-3 text-[12px] text-ink disabled:opacity-50"
            />
          </label>
        )}
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={onSave}
            disabled={working}
            className="h-11 flex-1 rounded-lg bg-ink text-[13px] font-bold text-white disabled:opacity-40"
          >
            {working ? "저장 중…" : correcting ? "정정값 저장" : "확인한 값 저장"}
          </button>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              disabled={working}
              className="h-11 rounded-lg border border-neutral300 bg-white px-5 text-[13px] font-bold text-neutral700 disabled:opacity-40"
            >
              취소
            </button>
          )}
        </div>
        <p className="mt-2 text-[11px] text-neutral500">
          AI가 읽은 값은 저장 전 자유롭게 고칠 수 있어요. 저장 후 정정은 기존 기록을
          덮어쓰지 않고 새 버전으로 남습니다.
        </p>
      </Card>
    </section>
  );
}

function PerformanceDashboard({
  performance,
  latestConfirmedReportId,
  onCorrect,
}: {
  performance: ContractPerformance;
  latestConfirmedReportId: string | null;
  onCorrect: (report: PerformanceReport) => void;
}) {
  const totals = useMemo(() => {
    const result = {
      adSpend: sumConfirmedMetric(performance.confirmedSeries, "ad_spend"),
      impressions: sumConfirmedMetric(performance.confirmedSeries, "impressions"),
      clicks: sumConfirmedMetric(performance.confirmedSeries, "clicks"),
      posts: sumConfirmedMetric(performance.confirmedSeries, "published_content_count"),
    };
    return {
      ...result,
      ctr: calculatePerformanceCtr(result.clicks, result.impressions),
      cpc: calculatePerformanceCpc(result.adSpend, result.clicks),
    };
  }, [performance.confirmedSeries]);

  return (
    <>
      <section className="flex flex-col gap-2">
        <SectionTitle>③ 확인한 광고효과 한눈에 보기</SectionTitle>
        {performance.confirmedSeries.length === 0 ? (
          <Card>
            <p className="text-center text-[12px] text-neutral500">
              아직 확인해 저장한 월별 광고효과가 없어요.
            </p>
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
              <StatTile
                size="lg"
                value={totals.adSpend === null ? "—" : `${totals.adSpend.toLocaleString()}원`}
                label="누적 광고비"
              />
              <StatTile
                size="lg"
                value={totals.impressions?.toLocaleString() ?? "—"}
                label="누적 노출"
              />
              <StatTile
                size="lg"
                value={totals.clicks?.toLocaleString() ?? "—"}
                label="누적 클릭"
              />
              <StatTile
                size="lg"
                value={totals.ctr === null ? "—" : `${totals.ctr.toFixed(2)}%`}
                label="전체 CTR"
              />
              <StatTile size="lg" value={totals.cpc === null ? "—" : `${totals.cpc.toLocaleString()}원`} label="전체 CPC" />
              <StatTile
                size="lg"
                value={totals.posts === null ? "—" : `${totals.posts.toLocaleString()}건`}
                label="누적 게시물"
              />
            </div>
            <Card>
              <div className="mb-3 text-[12px] font-bold text-neutral700">월별 노출 추이</div>
              <MonthlyChart points={performance.confirmedSeries} />
            </Card>
          </>
        )}

        <Card>
          <div className="mb-2 text-[12px] font-bold text-neutral700">월별 저장 기록</div>
          <div className="divide-y divide-neutral100">
            {[...performance.reports].reverse().map((report) => (
              <div key={report.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <b className="text-[13px] text-ink">{report.period}</b>
                  <span className="ml-2 text-[11px] text-neutral500">
                    {reportStatusLabel(report.status)} · 버전 {report.revisionCount}
                  </span>
                  {report.currentRevision?.correctionReason && (
                    <p className="mt-1 text-[10px] text-neutral500">
                      최근 정정: {report.currentRevision.correctionReason}
                    </p>
                  )}
                </div>
                {report.id === latestConfirmedReportId && report.currentRevision && (
                  <button
                    type="button"
                    onClick={() => onCorrect(report)}
                    className="rounded-lg border border-neutral300 bg-white px-3 py-1.5 text-[11px] font-bold text-neutral700"
                  >
                    최신 값 정정
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section className="flex flex-col gap-2">
        <SectionTitle>④ 계약·전월 대조 결과와 문의 문안</SectionTitle>
        {performance.flags.length === 0 ? (
          <Card>
            <p className="text-center text-[12px] text-neutral500">
              현재 확정값에서 별도로 확인할 신호가 없어요.
            </p>
          </Card>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {performance.flags.map((flag) => (
              <FlagCard
                key={flag.id}
                flag={flag}
                inquiry={performance.inquiryDrafts.find((draft) => draft.flagId === flag.id)?.text ?? null}
              />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function MonthlyChart({ points }: { points: ContractPerformance["confirmedSeries"] }) {
  const max = Math.max(
    ...points.map((point) => (
      performanceMetricValue(point.confirmedPayload.metricItems, "impressions") ?? 0
    )),
    1,
  );
  // 리포트가 한 건뿐이면 flex-1이 막대를 카드 전체 폭으로 늘려 읽기 어렵다.
  // 이때만 폭을 절반으로 묶고, 두 건부터는 원래대로 균등 분할한다.
  const single = points.length === 1;
  return (
    <div className="flex min-h-40 items-end gap-3 overflow-x-auto pb-1">
      {points.map((point) => {
        const items = point.confirmedPayload.metricItems;
        const adSpend = performanceMetricValue(items, "ad_spend");
        const impressions = performanceMetricValue(items, "impressions") ?? 0;
        const clicks = performanceMetricValue(items, "clicks");
        const ctr = calculatePerformanceCtr(clicks, impressions);
        const cpc = calculatePerformanceCpc(adSpend, clicks);
        const posts = performanceMetricValue(items, "published_content_count");
        return (
          <div
            key={point.reportId}
            className={`flex min-w-36 flex-col items-center gap-1.5 ${single ? "w-1/2 flex-none" : "flex-1"}`}
          >
            <span className="text-[11px] font-bold text-ink">{impressions.toLocaleString()}</span>
            <div className="flex h-28 w-full items-end">
              <div
                className={`w-full rounded-t-lg ${point.status === "FLAGGED" ? "bg-brand400" : "bg-neutral200"}`}
                style={{ height: `${Math.max((impressions / max) * 100, 2)}%` }}
              />
            </div>
            <span className="text-[11px] font-medium text-neutral700">{point.period.slice(2)}</span>
            <span className="text-center text-[10px] leading-relaxed text-neutral500">
              광고비 {adSpend === null ? "—" : `${adSpend.toLocaleString()}원`} · 클릭 {clicks ?? "—"}
              <br />
              CTR {ctr === null ? "—" : `${ctr.toFixed(2)}%`} · CPC {cpc === null ? "—" : `${cpc.toLocaleString()}원`} · 게시 {posts ?? "—"}건
            </span>
          </div>
        );
      })}
    </div>
  );
}

function FlagCard({ flag, inquiry }: { flag: PerformanceFlag; inquiry: string | null }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!inquiry) return;
    await navigator.clipboard?.writeText(inquiry);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Card>
      <div className="rounded-lg border border-brand300 bg-brand50 p-3">
        <div className="text-[13px] font-bold text-brand800">{flagTitle(flag)}</div>
        <p className="mt-1 text-[12px] leading-relaxed text-neutral700">{flagDescription(flag)}</p>
      </div>
      {flag.basisSnapshots.map((basis) => (
        <p key={`${basis.sourcePage}-${basis.sourceText}`} className="mt-2 text-[10px] leading-relaxed text-neutral500">
          계약서 {basis.sourcePage}쪽 “{basis.sourceText}” · 근거 확신도 {Math.round(basis.confidence * 100)}%
        </p>
      ))}
      {inquiry && (
        <div className="mt-3">
          <LayerBlock layer="request" label="대행사에 보낼 문의 문안 · 미발송">
            {inquiry}
          </LayerBlock>
          <button
            type="button"
            onClick={copy}
            className="mt-2 h-9 w-full rounded-lg bg-ink text-[12px] font-bold text-white"
          >
            {copied ? "복사됐어요" : "문안 복사하기"}
          </button>
        </div>
      )}
    </Card>
  );
}

function StepFlow({
  activeReport,
  hasConfirmed,
}: {
  activeReport: PerformanceReport | null;
  hasConfirmed: boolean;
}) {
  const steps = ["리포트 올리기", "읽은 내용 확인", "대시보드", "문의하기", "증빙 확인"];
  const reached = activeReport?.status === "EXTRACTED"
    ? 2
    : activeReport?.status === "UPLOADED"
      ? 1
      : hasConfirmed
        ? 4
        : 0;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((step, index) => (
        <span key={step} className="flex items-center gap-1.5">
          <span className={`rounded-lg px-2.5 py-1 text-[11px] font-bold ${index < reached ? "bg-brand100 text-brand800" : "bg-neutral100 text-neutral500"}`}>
            {index + 1}. {step}
          </span>
          {index < steps.length - 1 && <span className="text-neutral300">›</span>}
        </span>
      ))}
    </div>
  );
}

function ObligationPanel({ contractId }: { contractId: string }) {
  const state = useAsync(() => adapter.getObligation(contractId), [contractId]);
  const [updated, setUpdated] = useState<LiveObligation | null>(null);
  const [publicLink, setPublicLink] = useState<{ publicUrl: string; expiresAt: string } | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const obligation = updated ?? (state.status === "ready" ? state.data : null);

  const createEvidenceLink = async () => {
    if (!obligation || working) return;
    setWorking(true);
    setError(null);
    try {
      const link = await adapter.createObligationEvidenceLink(contractId, obligation.id);
      setPublicLink({ publicUrl: link.publicUrl, expiresAt: link.expiresAt });
    } catch (cause) {
      setError(errorMessage(cause, "증빙 제출 링크를 만들지 못했습니다."));
    } finally {
      setWorking(false);
    }
  };

  const review = async (decision: "APPROVED" | "DISPUTED") => {
    if (!obligation || obligation.status !== "SUBMITTED" || working) return;
    setWorking(true);
    setError(null);
    try {
      setUpdated(await adapter.reviewObligation(contractId, obligation.id, decision));
    } catch (cause) {
      setError(errorMessage(cause, "증빙 검토 결과를 저장하지 못했습니다."));
    } finally {
      setWorking(false);
    }
  };

  if (state.status === "loading") {
    return <p className="py-6 text-center text-sm text-neutral500">불러오는 중…</p>;
  }
  if (state.status === "error") {
    return <p className="py-6 text-center text-sm font-bold text-brand800">⚠ {state.error}</p>;
  }
  if (!obligation) {
    return (
      <Card>
        <p className="text-[12px] leading-relaxed text-neutral500">
          원문 근거로 확인된 대표 산출물이 아직 없어요. 계약서 분석이 끝나면 이곳에서
          증빙 제출 링크를 만들 수 있어요.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <div className="text-[13px] font-black text-ink">{obligation.title}</div>
      <div className="mt-2 rounded-lg bg-subtle p-3.5">
        <div className="text-[11px] text-neutral500">기한 {obligation.dueDate}</div>
        <p className="mt-2 text-[12px] leading-relaxed text-neutral700">
          계약서 {obligation.sourcePage}쪽: “{obligation.sourceText}”
        </p>
        <div className="mt-1 text-[10px] text-neutral500">
          원문 근거 확신도 {Math.round(obligation.confidence * 100)}%
        </div>
        {obligation.evidenceUrl && (
          <a
            href={obligation.evidenceUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block text-[11px] text-brand700 underline underline-offset-2"
          >
            제출된 증빙 URL 보기 →
          </a>
        )}
      </div>

      {obligation.status === "PENDING" && (
        <div className="mt-3 rounded-xl border border-neutral200 bg-white p-4">
          <h3 className="text-sm font-black text-ink">대행사 증빙 제출 링크</h3>
          <p className="mt-1 text-[11px] leading-relaxed text-neutral500">
            링크를 만든 뒤 복사해 기존 이메일이나 메신저로 직접 전달해주세요.
          </p>
          {publicLink ? (
            <div className="mt-3">
              <PublicLinkCard
                link={publicLink}
                title="증빙 제출 링크"
                note="아직 자동 발송되지 않았습니다. 사장님이 직접 전달해주세요."
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => void createEvidenceLink()}
              disabled={working}
              className="mt-3 h-11 w-full rounded-lg bg-ink text-[13px] font-bold text-white disabled:opacity-40"
            >
              {working ? "링크 만드는 중…" : "증빙 제출 링크 만들기"}
            </button>
          )}
        </div>
      )}

      {obligation.status === "SUBMITTED" && (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            disabled={working}
            onClick={() => void review("APPROVED")}
            className="h-11 flex-1 rounded-lg bg-ink text-[13px] font-bold text-white disabled:opacity-40"
          >
            {working ? "저장 중…" : "확인 완료"}
          </button>
          <button
            type="button"
            disabled={working}
            onClick={() => void review("DISPUTED")}
            className="h-11 flex-1 rounded-lg border border-neutral300 bg-white text-[13px] font-bold text-neutral500 disabled:opacity-40"
          >
            이의 있어요
          </button>
        </div>
      )}

      {obligation.status === "APPROVED" && (
        <p className="mt-3 text-[13px] font-bold text-brand700">✓ 지급 조건 충족으로 표시했어요</p>
      )}
      {obligation.status === "DISPUTED" && (
        <p className="mt-3 text-[13px] font-bold text-neutral700">! 이의 있음으로 기록했어요</p>
      )}
      {error && <p className="mt-2 text-xs font-bold text-brand800">{error}</p>}
      <p className="mt-2 text-[11px] leading-relaxed text-neutral500">
        확인 완료는 계약상 지급 조건 충족 표시이며 실제 송금·결제를 실행하지 않습니다.
      </p>
    </Card>
  );
}

function flagTitle(flag: PerformanceFlag): string {
  if (flag.flagType === "DELIVERABLE_COUNT_SHORTFALL") return "계약보다 게시물 수가 적어요";
  if (flag.flagType === "ENGAGEMENT_RATE_DROP") return "전월보다 반응률이 낮아졌어요";
  return "사장님이 확인이 필요하다고 기록했어요";
}

function flagDescription(flag: PerformanceFlag): string {
  if (flag.flagType === "DELIVERABLE_COUNT_SHORTFALL") {
    return `계약에서 확인한 월 ${flag.expectedContentCount}건과 리포트의 ${flag.actualContentCount}건이 다릅니다.`;
  }
  if (flag.flagType === "ENGAGEMENT_RATE_DROP") {
    return `반응률이 ${((flag.previousEngagementRate ?? 0) * 100).toFixed(2)}%에서 ${((flag.currentEngagementRate ?? 0) * 100).toFixed(2)}%로 낮아졌습니다.`;
  }
  return flag.issueNote ?? "확인할 내용이 기록되어 있습니다.";
}

function reportStatusLabel(status: PerformanceReport["status"]): string {
  const labels = {
    UPLOADED: "업로드됨",
    EXTRACTED: "숫자 확인 필요",
    CONFIRMED: "확인 완료",
    FLAGGED: "확인 신호 있음",
  } satisfies Record<PerformanceReport["status"], string>;
  return labels[status];
}

function oldestUnfinishedReport(reports: PerformanceReport[]): PerformanceReport | null {
  return [...reports]
    .filter((report) => report.status === "UPLOADED" || report.status === "EXTRACTED")
    .sort((left, right) => left.period.localeCompare(right.period))[0] ?? null;
}

function suggestedUploadPeriod(reports: PerformanceReport[]): string {
  const latest = [...reports]
    .sort((left, right) => left.period.localeCompare(right.period))
    .at(-1);
  if (!latest) return defaultPeriod();
  const [year, month] = latest.period.split("-").map(Number);
  return month === 12
    ? `${String(year + 1).padStart(4, "0")}-01`
    : `${String(year).padStart(4, "0")}-${String(month + 1).padStart(2, "0")}`;
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}
