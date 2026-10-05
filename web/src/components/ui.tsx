"use client";
import { useEffect, useRef, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  Circle,
  Clock3,
  Copy,
  Download,
  FlaskConical,
  LoaderCircle,
  X,
} from "lucide-react";
import type { Json } from "@/lib/contracts";
import { displayJson, label, scalar } from "@/lib/format";

export function Status({ value }: { value: string }) {
  const state = value.toLowerCase();
  const tone = [
    "completed",
    "approved",
    "approve",
    "accepted",
    "accept",
    "pass",
    "passed",
    "ready",
  ].includes(state)
    ? "success"
    : ["failed", "rejected", "reject", "fail", "error"].includes(state)
      ? "danger"
      : ["running", "queued", "waiting"].includes(state)
        ? "active"
        : ["blocked", "revise", "needs_revision", "changes_requested"].includes(
              state,
            )
          ? "warning"
          : "neutral";
  const Icon =
    tone === "success"
      ? Check
      : state === "running"
        ? LoaderCircle
        : state === "queued"
          ? Clock3
          : tone === "danger"
            ? X
            : Circle;
  return (
    <span className={`status status-${tone}`}>
      <Icon size={12} className={state === "running" ? "spin" : ""} />
      {label(value)}
    </span>
  );
}
export function ErrorNotice({
  children,
  onRetry,
  stale = false,
}: {
  children: ReactNode;
  onRetry?: () => void;
  stale?: boolean;
}) {
  return (
    <div className="error-notice" role="alert">
      <AlertCircle size={17} />
      <div>
        {stale && <strong>Showing the last available data. </strong>}
        {children}
      </div>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        {icon || <FlaskConical size={25} strokeWidth={1.4} />}
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Loading({
  label: text = "Loading research…",
}: {
  label?: string;
}) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={20} />
      <span>{text}</span>
    </div>
  );
}
export function JsonDetails({
  title = "Inspect structured data",
  value,
  open = false,
}: {
  title?: string;
  value: unknown;
  open?: boolean;
}) {
  const text = displayJson(value);
  return (
    <details className="json-details" open={open || undefined}>
      <summary>{title}</summary>
      <pre>
        {text.length > 60_000
          ? `${text.slice(0, 60_000)}\n\nPreview limited to 60,000 characters. Download the artifact for its full contents.`
          : text}
      </pre>
    </details>
  );
}
export function StructuredValues({
  value,
  max = 12,
}: {
  value: Record<string, Json>;
  max?: number;
}) {
  const entries = Object.entries(value)
    .filter(
      ([, v]) =>
        v === null || ["string", "number", "boolean"].includes(typeof v),
    )
    .slice(0, max);
  return (
    <dl className="structured-values">
      {entries.map(([key, v]) => (
        <div key={key}>
          <dt>{label(key)}</dt>
          <dd>{scalar(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = dialog.current;
    el?.showModal();
    return () => el?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`modal ${wide ? "modal-wide" : ""}`}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close dialog"
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function SourceLink({
  url,
  children,
}: {
  url: string;
  children?: ReactNode;
}) {
  let valid = false;
  try {
    valid = ["https:", "http:"].includes(new URL(url).protocol);
  } catch {
    /* Not a web link. */
  }
  return valid ? (
    <a
      className="source-link"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children || url}
      <ArrowUpRight size={13} />
    </a>
  ) : (
    <span className="muted">{url}</span>
  );
}
export function DownloadButton({
  name,
  value,
}: {
  name: string;
  value: unknown;
}) {
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <button className="button button-secondary button-small" onClick={download}>
      <Download size={14} />
      Download artifact
    </button>
  );
}
export function CopyButton({ value }: { value: string }) {
  return (
    <button
      className="icon-button"
      onClick={() => void navigator.clipboard.writeText(value)}
      aria-label="Copy to clipboard"
    >
      <Copy size={15} />
    </button>
  );
}
