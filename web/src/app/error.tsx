"use client";
import { ErrorNotice } from "@/components/ui";
export default function ErrorPage({
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <div className="page">
      <h1>This view could not be loaded.</h1>
      <ErrorNotice onRetry={reset}>
        Your recorded research is unchanged. Try loading this view again.
      </ErrorNotice>
    </div>
  );
}
