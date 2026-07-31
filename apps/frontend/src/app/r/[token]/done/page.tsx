import { AgencyShell } from "@/components/AgencyShell";

/* 대행사 ③ 응답 완료 — 계정 유도 없음(무가입 토큰 접근이 핵심 포지션). */
export default function AgencyDonePage() {
  return (
    <AgencyShell>
      <div className="rounded-xl border-2 border-ink bg-white p-6">
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand50 text-2xl text-brand700">
          ✓
        </div>
        <h1 className="text-base font-black text-ink">응답을 모두 보냈어요</h1>
        <p className="mt-2 text-[13px] leading-relaxed text-neutral700">
          조정 요청자에게 결과가 전달됐어요. 합의가 확정되면 서명 요청 링크를 다시
          보내드릴게요.
        </p>

        <div className="mt-5 rounded-lg bg-subtle px-4 py-3">
          <div className="text-[12px] font-bold text-ink">
            산출물 등록도 필요하신가요?
          </div>
          <p className="mt-1 text-[11px] text-neutral500">
            합의·서명 이후 계약 요청자가 증빙 제출 전용 링크를 새로 보내드려요.
            조정 요청 링크로는 증빙을 제출할 수 없습니다.
          </p>
        </div>
      </div>
    </AgencyShell>
  );
}
