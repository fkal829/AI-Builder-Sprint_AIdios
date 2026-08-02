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
  isUsingMock,
  type ContractPerformance,
  type LiveObligation,
  type PerformanceConfirmedPayload,
  type PerformanceFlag,
  type PerformanceMetricKey,
  type PerformanceReport,
} from "@/lib/adapter";

type MetricField = {
  key: keyof PerformanceConfirmedPayload;
  extractedKey?: PerformanceMetricKey;
  label: string;
  required?: boolean;
  signed?: boolean;
};

const METRIC_FIELDS: MetricField[] = [
  { key: "impressions", extractedKey: "impressions", label: "노출", required: true },
  { key: "likes", extractedKey: "likes", label: "좋아요", required: true },
  { key: "comments", extractedKey: "comments", label: "댓글", required: true },
  { key: "reach", extractedKey: "reach", label: "도달" },
  { key: "saves", extractedKey: "saves", label: "저장" },
  { key: "shares", extractedKey: "shares", label: "공유" },
  {
    key: "followerNetChange",
    extractedKey: "followerNetChange",
    label: "팔로워 순증",
    signed: true,
  },
  {
    key: "publishedContentCount",
    extractedKey: "publishedContentCount",
    label: "게시물 수",
  },
  { key: "inquiries", label: "문의" },
  { key: "reservations", label: "예약" },
  { key: "purchases", label: "구매" },
];

type MetricForm = Record<keyof PerformanceConfirmedPayload, string>;
type WorkingAction = "loading" | "uploading" | "extracting" | "saving" | null;

function emptyMetricForm(): MetricForm {
  return Object.fromEntries(METRIC_FIELDS.map((field) => [field.key, ""])) as MetricForm;
}

function formFromReport(report: PerformanceReport): MetricForm {
  if (report.currentRevision) {
    return Object.fromEntries(
      METRIC_FIELDS.map((field) => {
        const value = report.currentRevision!.confirmedPayload[field.key];
        return [field.key, value === null ? "" : String(value)];
      }),
    ) as MetricForm;
  }
  return Object.fromEntries(
    METRIC_FIELDS.map((field) => {
      const value = field.extractedKey
        ? report.extractedPayload?.[field.extractedKey].value ?? null
        : null;
      return [field.key, value === null ? "" : String(value)];
    }),
  ) as MetricForm;
}

function parseMetricForm(form: MetricForm): PerformanceConfirmedPayload {
  const parsed = Object.fromEntries(
    METRIC_FIELDS.map((field) => {
      const raw = form[field.key].trim();
      if (!raw) {
        if (field.required) throw new Error(`${field.label} 값을 입력해주세요.`);
        return [field.key, null];
      }
      if (!/^-?\d+$/.test(raw)) throw new Error(`${field.label}은 정수로 입력해주세요.`);
      const value = Number(raw);
      if (!Number.isSafeInteger(value)) throw new Error(`${field.label} 값이 너무 큽니다.`);
      if (!field.signed && value < 0) throw new Error(`${field.label}은 0 이상이어야 합니다.`);
      return [field.key, value];
    }),
  );
  return parsed as PerformanceConfirmedPayload;
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
      right={
        <span className="rounded bg-brand100 px-2 py-1 text-[10px] font-bold text-brand800">
          {isUsingMock ? "데모 데이터 모드" : "실 API 연결"}
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <p className="text-[13px] leading-relaxed text-neutral700">
          대행사에게 받은 광고 리포트를 올려두면, 계약에서 약속한 조건대로 진행되고
          있는지 한눈에 확인하고 산출물 증빙까지 마무리할 수 있어요.
        </p>

        <Card>
          <p className="text-[12px] leading-relaxed text-neutral700">
            <b className="text-ink">계약서를 기준으로 확인해요.</b> 리포트에서 읽은 숫자는
            사장님이 직접 확인한 뒤에만 계약 조건과 전월 기록에 대조합니다.
          </p>
          <p className="mt-1.5 text-[11px] leading-relaxed text-neutral500">
            원문 근거를 찾지 못한 값은 자동으로 확정하지 않고 확인이 필요한 값으로
            남겨둡니다.
          </p>
          <div className="mt-2.5">
            <a
              href={`/contracts/${id}`}
              className="rounded-lg border border-neutral300 bg-white px-3 py-1.5 text-[12px] font-bold text-ink hover:bg-subtle"
            >
              계약서에서 보기 →
            </a>
          </div>
        </Card>

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

        {activeReport?.status === "UPLOADED" && (
          <Card>
            <p className="text-[13px] font-bold text-ink">
              {activeReport.period} 리포트가 업로드됐지만 숫자 추출이 끝나지 않았어요.
            </p>
            <button
              type="button"
              onClick={retryExtraction}
              disabled={Boolean(working)}
              className="mt-3 h-10 rounded-lg bg-ink px-4 text-[13px] font-bold text-white disabled:opacity-40"
            >
              {working === "extracting" ? "숫자 읽는 중…" : "지표 추출 다시 시도"}
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
  return (
    <section className="flex flex-col gap-2">
      <SectionTitle>
        ② {correcting ? `${report.period} 확정값 정정` : "읽은 숫자와 원문 확인"}
      </SectionTitle>
      <Card>
        {report.extractedPayload && !correcting && (
          <div className="mb-4 grid gap-2 lg:grid-cols-2">
            {METRIC_FIELDS.filter((field) => field.extractedKey).map((field) => {
              const candidate = report.extractedPayload![field.extractedKey!];
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

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {METRIC_FIELDS.map((field) => (
            <label key={field.key} className="text-[11px] font-bold text-neutral700">
              {field.label}{field.required ? " *" : ""}
              <input
                inputMode="numeric"
                value={form[field.key]}
                onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
                placeholder={field.required ? "필수" : "없으면 비워두기"}
                disabled={working}
                className="mt-1 h-10 w-full rounded-lg border border-neutral300 px-3 text-[13px] font-bold text-ink disabled:opacity-50"
              />
            </label>
          ))}
        </div>

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
    const result = performance.confirmedSeries.reduce(
      (sum, point) => ({
        impressions: sum.impressions + point.confirmedPayload.impressions,
        reactions: sum.reactions
          + point.confirmedPayload.likes
          + point.confirmedPayload.comments
          + (point.confirmedPayload.saves ?? 0)
          + (point.confirmedPayload.shares ?? 0),
        posts: sum.posts + (point.confirmedPayload.publishedContentCount ?? 0),
      }),
      { impressions: 0, reactions: 0, posts: 0 },
    );
    return {
      ...result,
      rate: result.impressions === 0 ? null : result.reactions / result.impressions,
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
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <StatTile size="lg" value={totals.impressions.toLocaleString()} label="누적 노출" />
              <StatTile size="lg" value={totals.reactions.toLocaleString()} label="누적 반응" />
              <StatTile
                size="lg"
                value={totals.rate === null ? "—" : `${(totals.rate * 100).toFixed(2)}%`}
                label="전체 반응률"
              />
              <StatTile size="lg" value={`${totals.posts.toLocaleString()}건`} label="누적 게시물" />
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
  const max = Math.max(...points.map((point) => point.confirmedPayload.impressions), 1);
  return (
    <div className="flex min-h-40 items-end gap-3 overflow-x-auto pb-1">
      {points.map((point) => (
        <div key={point.reportId} className="flex min-w-24 flex-1 flex-col items-center gap-1.5">
          <span className="text-[11px] font-bold text-ink">
            {point.confirmedPayload.impressions.toLocaleString()}
          </span>
          <div className="flex h-28 w-full items-end">
            <div
              className={`w-full rounded-t-lg ${point.status === "FLAGGED" ? "bg-brand400" : "bg-neutral200"}`}
              style={{ height: `${Math.max((point.confirmedPayload.impressions / max) * 100, 2)}%` }}
            />
          </div>
          <span className="text-[11px] font-medium text-neutral700">{point.period.slice(2)}</span>
          <span className="text-[10px] text-neutral500">
            게시 {point.confirmedPayload.publishedContentCount ?? "—"}건 · 반응률{
              point.engagementRate === null ? " —" : ` ${(point.engagementRate * 100).toFixed(2)}%`
            }
          </span>
        </div>
      ))}
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
