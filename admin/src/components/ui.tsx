import type { ReactNode } from "react";
import { AlertCircle, Inbox, LoaderCircle, type LucideIcon } from "lucide-react";
import { describeError } from "../api/client";

export function Brand() {
  return <div className="brand"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><span>Phone-Proctor</span></div>;
}

export function PageHeading({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="actions">{actions}</div>}</div>;
}

export function State({ title, children, kind = "empty", icon }: { title: string; children?: ReactNode; kind?: "empty" | "loading" | "error"; icon?: LucideIcon }) {
  const Icon = icon ?? (kind === "error" ? AlertCircle : kind === "loading" ? LoaderCircle : Inbox);
  return <div className={`state state-${kind}`} role={kind === "error" ? "alert" : "status"}>
    <span className="state-icon"><Icon size={21} className={kind === "loading" ? "spin" : ""} aria-hidden="true" /></span>
    <strong>{title}</strong>{children && <div className="state-detail">{children}</div>}
  </div>;
}

export function Failure({ error, retry, title = "Something went wrong" }: { error: unknown; retry?: () => void; title?: string }) {
  return <State title={title} kind="error"><p>{describeError(error)}</p>{retry && <button onClick={retry}>Try again</button>}</State>;
}

export function Badge({ value }: { value?: string | null }) {
  const label = value?.replace(/_/g, " ") || "Unknown";
  const normalized = label.toLowerCase();
  const tone = ["ready", "online", "open", "in exam", "acked", "verified", "ok", "accepted", "confirmed"].includes(normalized) ? "green"
    : ["blocked", "incident", "failed", "down", "offline", "expired", "camera check required"].includes(normalized) ? "red"
    : ["degraded", "paused", "stale", "pending", "connecting", "dispatched"].includes(normalized) ? "amber" : "neutral";
  return <span className={`badge tone-${tone}`}><i aria-hidden="true" />{label}</span>;
}

export function Feedback({ error, message }: { error?: unknown; message?: string }) {
  if (error) return <p className="feedback error" role="alert">{describeError(error)}</p>;
  return message ? <p className="feedback" role="status">{message}</p> : null;
}
