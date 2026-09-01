/**
 * Generated from contracts/v1 console JSON Schema.
 * Do not edit by hand — run `python tools/generate_console_types.py`.
 */

export interface ConsoleSession {
  session_id: string;
  display_name?: string;
  lifecycle: string;
  connectivity: string;
  attention?: string;
  heartbeat_age_ms?: number;
  claim_owner?: string | null;
  thumbnail_available?: boolean;
  [key: string]: unknown;
}

export interface ConsoleSnapshot {
  exam_id: string;
  stream_seq: number;
  readiness?: "Incident" | "Blocked" | "Degraded" | "Ready";
  sessions: ConsoleSession[];
  [key: string]: unknown;
}

export interface ConsoleDelta {
  exam_id: string;
  stream_seq: number;
  op: "upsert" | "remove" | "heartbeat" | "event";
  session_id?: string;
  patch?: {
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export type ConsoleReadiness = ConsoleSnapshot["readiness"];
export type ConsoleDeltaOp = ConsoleDelta["op"];
