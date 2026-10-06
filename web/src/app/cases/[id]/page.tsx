import { CaseScreen } from "@/components/case-screen";
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { id } = await params;
  const { tab } = await searchParams;
  return (
    <CaseScreen
      caseId={id}
      initialTab={tab === "forecasts" ? "forecasts" : "research"}
    />
  );
}
