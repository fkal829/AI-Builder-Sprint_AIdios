import { redirect } from "next/navigation";

/** 산출물 증빙은 이행·광고효과 관리 화면으로 통합됐다. */
export default async function LegacyObligationsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/contracts/${id}/performance`);
}
