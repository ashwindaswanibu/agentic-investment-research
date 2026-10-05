import { ResearchScreen } from "@/components/research-screen";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string }>;
}) {
  const { workspace } = await searchParams;
  return <ResearchScreen workspaceId={workspace} />;
}
