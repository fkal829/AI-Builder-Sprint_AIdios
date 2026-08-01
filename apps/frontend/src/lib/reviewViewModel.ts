import type {
  LiveContractReview,
  LiveDocumentClause,
  LiveReviewItem,
} from "./adapter";
import { displayText } from "./displayText";
import { SIGNAL_META } from "./status";
import type { ClauseCard, ContractDetail, DocClause } from "./types";

export type ReviewDashboardData = Pick<
  ContractDetail,
  "understood" | "document" | "clauses"
> & {
  hasCompleteDocumentClauses?: boolean;
};

const riskFor = (item: LiveReviewItem): DocClause["risk"] => {
  if (item.severity === "IMPORTANT") return "high";
  if (item.severity === "CHECK") return "mid";
  return "low";
};

export function liveReviewItemToClause(
  item: LiveReviewItem,
  docClauseId?: string,
): ClauseCard {
  return {
    id: item.id,
    title: SIGNAL_META[item.type],
    state: item.userChoice === "ACCEPT"
      ? "ACCEPT_SELECTED"
      : item.userChoice === "COMPROMISE"
        ? "COMPROMISE_SELECTED"
        : item.userChoice === "REQUEST"
          ? "REQUEST_SELECTED"
          : "UNREVIEWED",
    signal: item.type,
    original: {
      page: item.sourcePage ?? 0,
      text: item.sourceText
        ? displayText(item.sourceText)
        : "원문 근거를 찾지 못했습니다.",
    },
    understood: null,
    aiExplanation: item.plainExplanation,
    confidence: item.sourceConfidence ?? 0,
    officialBasis: item.basisText,
    suggestions: [
      { choice: "ACCEPT", label: "원안 수용", text: item.suggestionAccept },
      { choice: "COMPROMISE", label: "절충안", text: item.suggestionCompromise },
      { choice: "REQUEST", label: "요청안", text: item.suggestionRequest },
    ],
    userChoice: item.userChoice,
    agencyResponse: null,
    docClauseId,
  };
}

const normalized = (value: string) => value.replace(/\s+/g, "").trim();

function findDocumentClause(
  item: LiveReviewItem,
  clauses: LiveDocumentClause[],
): LiveDocumentClause | undefined {
  if (item.sourcePage == null || !item.sourceText) return undefined;
  const candidates = clauses.filter((clause) => clause.sourcePage === item.sourcePage);
  if (candidates.length === 0) return undefined;
  const evidence = normalized(item.sourceText);
  const direct = candidates.find((clause) => {
    const source = normalized(clause.sourceText);
    return source.includes(evidence) || evidence.includes(source);
  });
  if (direct) return direct;

  const evidenceTokens = item.sourceText.split(/\s+/).filter((token) => token.length >= 2);
  const best = candidates
    .map((clause) => ({
      clause,
      score: evidenceTokens.filter((token) => clause.sourceText.includes(token)).length,
    }))
    .sort((a, b) => b.score - a.score)[0];
  return best && best.score > 0 ? best.clause : undefined;
}

export function liveReviewToDashboard(review: LiveContractReview): ReviewDashboardData {
  const understood = {
    durationText: review.understood?.durationText || "잘 기억 안 나요",
    monthlyAmount: review.understood?.monthlyAmount == null
      ? "잘 기억 안 나요"
      : `${review.understood.monthlyAmount.toLocaleString()}원`,
    totalAmount: review.understood?.totalAmount == null
      ? "잘 기억 안 나요"
      : `${review.understood.totalAmount.toLocaleString()}원`,
    refundText: review.understood?.refundText || "잘 기억 안 나요",
    terminationText: review.understood?.terminationText || "잘 기억 안 나요",
    sourceType: "USER_MEMORY" as const,
  };
  const linkedClauses = new Map(
    review.items.map((item) => [item.id, findDocumentClause(item, review.documentClauses)]),
  );
  const legacyDocumentClauses: DocClause[] = review.items.map((item, index) => ({
    id: item.id,
    no: item.sourcePage ? `${item.sourcePage}쪽` : `확인 ${index + 1}`,
    title: SIGNAL_META[item.type],
    body: item.sourceText
      ? displayText(item.sourceText)
      : "계약서에서 직접 연결할 원문 근거를 찾지 못했습니다.",
    sourcePage: item.sourcePage ?? undefined,
    confidence: item.sourceConfidence,
    risk: riskFor(item),
    note: item.plainExplanation,
  }));
  const documentClauses: DocClause[] = review.documentClauses.length > 0
    ? review.documentClauses.map((clause) => {
        const related = review.items.filter(
          (item) => linkedClauses.get(item.id)?.id === clause.id,
        );
        const risk = related.reduce<DocClause["risk"]>(
          (current, item) => {
            const candidate = riskFor(item);
            if (candidate === "high" || (candidate === "mid" && current === "low")) {
              return candidate;
            }
            return current;
          },
          "low",
        );
        return {
          id: clause.id,
          no: clause.heading,
          title: displayText(clause.title),
          body: displayText(clause.sourceText),
          sourcePage: clause.sourcePage,
          confidence: clause.confidence,
          risk,
          note: related.map((item) => item.plainExplanation).join(" ") || undefined,
        };
      })
    : legacyDocumentClauses;
  const pageCount = Math.max(
    1,
    ...documentClauses.map((clause) => clause.sourcePage ?? 1),
    ...review.items.map((item) => item.sourcePage ?? 1),
  );

  return {
    hasCompleteDocumentClauses: review.documentClauses.length > 0,
    understood,
    document: {
      title: review.title,
      parties: review.counterpartyName,
      pageCount,
      pdfUrl: review.documentAccessUrl ?? "",
      clauses: documentClauses,
    },
    clauses: review.items.map((item) =>
      liveReviewItemToClause(
        item,
        review.documentClauses.length > 0 ? linkedClauses.get(item.id)?.id : item.id,
      ),
    ),
  };
}
