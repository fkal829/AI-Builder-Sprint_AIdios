import { toneStyle, type BadgeTone } from "@/lib/status";

export function Badge({
  label,
  tone,
  icon,
  size = "md",
}: {
  label: string;
  tone: BadgeTone;
  icon?: string;
  size?: "sm" | "md";
}) {
  const s = toneStyle(tone);
  const pad = size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-bold whitespace-nowrap ${pad} ${s.chip}`}
    >
      {icon && <span aria-hidden>{icon}</span>}
      {label}
    </span>
  );
}
