/* 감사 타임라인 (기획안 §6.10) — 계약 생애 전체를 시간순으로. */
import type { AuditEvent } from "@/lib/types";

export function Timeline({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="flex flex-col">
      {events.map((e, i) => {
        const last = i === events.length - 1;
        return (
          <li key={e.id} className="flex gap-3">
            {/* 도트 + 연결선 */}
            <div className="flex flex-none flex-col items-center">
              <span
                className={
                  e.state === "current"
                    ? "mt-1 h-2.5 w-2.5 rounded-full border-2 border-amber700"
                    : e.state === "done"
                      ? "mt-1 h-2.5 w-2.5 rounded-full bg-amber700"
                      : "mt-1 h-2.5 w-2.5 rounded-full bg-gray300"
                }
              />
              {!last && (
                <span
                  className={`w-0.5 flex-1 ${
                    e.state === "done" ? "bg-amber400" : "bg-gray200"
                  }`}
                />
              )}
            </div>
            {/* 내용 */}
            <div className={`pb-4 ${last ? "pb-0" : ""}`}>
              <div
                className={`text-[13px] ${
                  e.state === "current"
                    ? "font-bold text-amber700"
                    : e.state === "upcoming"
                      ? "text-gray500"
                      : "text-ink"
                }`}
              >
                {e.label}
              </div>
              {e.date && <div className="text-[11px] text-gray500">{e.date}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
