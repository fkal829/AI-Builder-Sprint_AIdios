import Image from "next/image";

/* Dandi 로고 락업 — 로고 가이드 규격.
   심볼 24px + 워드마크 23px, 간격 11px, 자간 0.01em, 색 #10365a(brand800).
   최소 크기: 심볼 단독 15px, 워드마크 조합 20px. */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <span className="flex items-center gap-[11px]">
      <Image
        src="/assets/dandi-mark.svg"
        alt="Dandi"
        width={Math.round((size * 73.6) / 46)}
        height={size}
        priority
      />
      <span
        className="font-bold tracking-[0.01em] text-brand800"
        style={{ fontSize: size - 1 }}
      >
        Dandi
      </span>
    </span>
  );
}
