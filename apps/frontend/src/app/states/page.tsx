import Link from "next/link";
import { EmptyState } from "@/components/EmptyState";
import { CTAButton } from "@/components/AppScreen";
import { DEMO_CONTRACT_ID, DEMO_TOKEN } from "@/lib/mock";

/* 실패·빈 상태 갤러리 (설계 원칙 #7) — 각 상태를 폰 프레임 카드로 전시. */
export default function StatesPage() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-8 flex items-baseline justify-between border-b-2 border-ink pb-4">
        <div>
          <h1 className="text-2xl font-black text-ink">실패 · 빈 상태</h1>
          <p className="mt-1 text-[13px] text-neutral500">
            판정색(빨강) 없이 중립적으로 안내. 응답이 없는 것도 정보로 다룸.
          </p>
        </div>
        <Link
          href="/demo"
          className="text-[13px] font-bold text-brand700 underline underline-offset-2"
        >
          ← 런처
        </Link>
      </header>

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <Frame caption="대행사 무응답 (가장 흔함)">
          <EmptyState
            title="아직 답변이 없어요"
            big="D+6"
            body="응답이 없는 것도 중요한 정보예요. 대행사에 다시 알림을 보내거나, 직접 연락해보실 수 있어요."
            actions={<CTAButton variant="secondary">알림 다시 보내기</CTAButton>}
          />
        </Frame>

        <Frame caption="전부 거절됨">
          <EmptyState
            title="요청하신 3건이 모두 원안으로 유지돼요"
            body="대행사가 조정에 동의하지 않았어요. 원안대로 서명할지, 여기서 멈출지 결정하실 수 있어요."
            actions={
              <div className="flex gap-2">
                <button className="h-11 flex-1 rounded-lg border-2 border-ink bg-white text-[12px] font-bold text-ink">
                  여기서 멈출게요
                </button>
                <button className="h-11 flex-1 rounded-lg border border-neutral300 bg-white text-[12px] font-bold text-neutral500">
                  원안대로 진행
                </button>
              </div>
            }
          />
        </Frame>

        <Frame caption="불일치 0건 — 정상 계약">
          <EmptyState
            title="이해하신 내용과 계약서가 같아요"
            big="0건"
            bigEmphasis
            body="확인이 필요한 부분을 찾지 못했어요. 그대로 서명하셔도 좋아요."
            actions={
              <CTAButton href={`/contracts/${DEMO_CONTRACT_ID}/signature`}>
                그대로 서명 진행
              </CTAButton>
            }
          />
        </Frame>

        <Frame caption="PDF 파싱 실패">
          <EmptyState
            title="PDF를 읽지 못했어요"
            code="DOCUMENT_PARSE_FAILED"
            body="파일이 손상됐거나 스캔 화질이 낮을 수 있어요. 다시 업로드해주시겠어요?"
            actions={<CTAButton href="/contracts/new">다시 업로드하기</CTAButton>}
          />
        </Frame>

        <Frame caption="첫 사용자 — 계약 0건">
          <EmptyState
            title="아직 등록한 계약이 없어요"
            code="첫 계약서 PDF를 올려보세요"
            body="내가 이해한 조건과 계약서를 대조해서, 다른 부분만 짚어드려요."
            actions={<CTAButton href="/contracts/new">계약서 업로드하기</CTAButton>}
          />
        </Frame>

        <Frame caption="대행사 링크 만료">
          <EmptyState
            title="링크가 만료됐어요"
            code="ADJUSTMENT_LINK_EXPIRED"
            body="이 조정 요청 링크는 만료되었거나 유효하지 않아요. 요청하신 사장님께 새 링크를 부탁해 주세요."
            actions={
              <CTAButton href={`/r/${DEMO_TOKEN}`} variant="secondary">
                데모 링크 다시 열기
              </CTAButton>
            }
          />
        </Frame>
      </div>
    </div>
  );
}

function Frame({
  caption,
  children,
}: {
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 text-[12px] font-bold text-neutral700">{caption}</div>
      <div className="rounded-[24px] border-2 border-ink bg-white p-5">
        {children}
      </div>
    </div>
  );
}
