import { CaseScreen } from "@/components/case-screen";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CaseScreen caseId={id} />;
}
