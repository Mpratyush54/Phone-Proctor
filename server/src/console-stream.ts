import { randomUUID } from "node:crypto";

type ConsoleChange = {
  op: "upsert" | "remove" | "heartbeat" | "event";
  session_id?: string;
  patch?: Record<string, unknown>;
  event_seq?: number;
};

type ConsoleDelta = ConsoleChange & { exam_id: string; stream_seq: number };

export class ConsoleStream {
  readonly id = randomUUID();
  private readonly exams = new Map<string, { head: number; first: number; rows: Map<number, ConsoleDelta> }>();
  private readonly retained: ConsoleDelta[] = [];
  private tail = 0;

  constructor(private readonly capacity = 20_000, private readonly batchSize = 500) {}

  get size() {
    return this.retained.length;
  }

  head(examId: string) {
    return this.exams.get(examId)?.head ?? 0;
  }

  append(examId: string, change: ConsoleChange) {
    let exam = this.exams.get(examId);
    if (!exam) {
      exam = { head: 0, first: 1, rows: new Map() };
      this.exams.set(examId, exam);
    }
    const seq = ++exam.head;
    const row = { ...change, exam_id: examId, stream_seq: seq };
    exam.rows.set(seq, row);
    const oldest = this.retained[this.tail];
    if (oldest) {
      const history = this.exams.get(oldest.exam_id)!;
      history.rows.delete(oldest.stream_seq);
      history.first = oldest.stream_seq + 1;
    }
    this.retained[this.tail] = row;
    this.tail = (this.tail + 1) % this.capacity;
    return seq;
  }

  since(examId: string, after: number, streamId?: string) {
    const history = this.exams.get(examId);
    const head = history?.head ?? 0;
    const resnapshot =
      (streamId !== undefined && streamId !== this.id) ||
      !Number.isSafeInteger(after) ||
      after < (history?.first ?? 1) - 1 ||
      after > head;
    const items: ConsoleDelta[] = [];
    if (!resnapshot && history) {
      const end = Math.min(head, after + this.batchSize);
      for (let seq = after + 1; seq <= end; seq++) items.push(history.rows.get(seq)!);
    }
    return { stream_id: this.id, stream_seq: head, resnapshot, items };
  }
}
