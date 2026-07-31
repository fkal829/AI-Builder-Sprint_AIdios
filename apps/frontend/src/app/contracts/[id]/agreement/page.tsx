import { redirect } from "next/navigation";

/** Legacy route retained so old bookmarks enter the revised-contract flow. */
export default async function LegacyAgreementPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/contracts/${id}/revision`);
}
