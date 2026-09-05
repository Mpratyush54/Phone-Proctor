import React from "react";
import { api } from "../api/client";

interface Bank {
  id: string;
  name: string;
  groups: {
    id: string;
    position: number;
    title: string;
    marks: number;
    variants: { id: string; stem: string; qtype: string; deprecated: boolean; options: { id: string; label: string }[] }[];
  }[];
  versions: { id: string; version: number }[];
}

export function Questions() {
  const [banks, setBanks] = React.useState<Bank[]>([]);
  const [bankName, setBankName] = React.useState("General Knowledge");
  const [groupTitle, setGroupTitle] = React.useState("");
  const [stem, setStem] = React.useState("");
  const [optText, setOptText] = React.useState("Option A\nOption B\nOption C\nOption D");
  const [correctIdx, setCorrectIdx] = React.useState("0");
  const [selBank, setSelBank] = React.useState("");
  const [selGroup, setSelGroup] = React.useState("");
  const [examId, setExamId] = React.useState("");
  const [selVersion, setSelVersion] = React.useState("");
  const [allowBack, setAllowBack] = React.useState(false);
  const [duration, setDuration] = React.useState("1800");
  const [enrollmentId, setEnrollmentId] = React.useState("");
  const [out, setOut] = React.useState("");
  const [err, setErr] = React.useState("");

  async function refresh() {
    setErr("");
    try {
      const data = await api("/api/v1/banks");
      setBanks(data.items);
      if (!selBank && data.items.length) setSelBank(data.items[0].id);
    } catch (e) {
      setErr(JSON.stringify(e));
    }
  }

  React.useEffect(() => {
    refresh().catch(() => undefined);
  }, []);

  async function run<T>(fn: () => Promise<T>, label: string) {
    setErr("");
    setOut("");
    try {
      const res = await fn();
      setOut(`${label}: ${JSON.stringify(res)}`);
      await refresh();
    } catch (e) {
      setErr(`${label}: ${JSON.stringify(e)}`);
    }
  }

  const bank = banks.find((b) => b.id === selBank);
  const group = bank?.groups.find((g) => g.id === selGroup) || bank?.groups[0];

  return (
    <main>
      <h1>Question banks</h1>
      <section>
        <input value={bankName} onChange={(e) => setBankName(e.target.value)} placeholder="Bank name" />
        <button onClick={() => run(() => api("/api/v1/banks", { method: "POST", body: JSON.stringify({ name: bankName }) }), "create bank")}>
          Create bank
        </button>
      </section>

      <section>
        <h2>Banks</h2>
        <select value={selBank} onChange={(e) => { setSelBank(e.target.value); setSelGroup(""); setSelVersion(""); }}>
          {banks.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
        <button onClick={() => refresh()}>Refresh</button>
        {bank && (
          <div>
            <h3>Add group to {bank.name}</h3>
            <input value={groupTitle} onChange={(e) => setGroupTitle(e.target.value)} placeholder="Group title (e.g. Algebra)" />
            <button
              onClick={() =>
                run(() => api(`/api/v1/banks/${bank.id}/groups`, { method: "POST", body: JSON.stringify({ title: groupTitle }) }), "add group")
              }
            >
              Add group
            </button>
            <h3>Add variant (framing) to group</h3>
            <select value={selGroup} onChange={(e) => setSelGroup(e.target.value)}>
              {bank.groups.map((g) => (
                <option key={g.id} value={g.id}>{g.title}</option>
              ))}
            </select>
            <br />
            <textarea value={stem} onChange={(e) => setStem(e.target.value)} rows={3} cols={60} placeholder="Question stem" />
            <br />
            <textarea value={optText} onChange={(e) => setOptText(e.target.value)} rows={4} cols={60} placeholder="One option per line" />
            <br />
            <label>
              Correct option index (0-based):{" "}
              <input value={correctIdx} onChange={(e) => setCorrectIdx(e.target.value)} style={{ width: 60 }} />
            </label>{" "}
            <button
              onClick={() => {
                const options = optText.split("\n").map((s) => s.trim()).filter(Boolean).map((label, i) => ({
                  label,
                  correct: i === Number(correctIdx),
                }));
                run(
                  () => api(`/api/v1/groups/${group?.id}/variants`, { method: "POST", body: JSON.stringify({ stem, qtype: "mcq_single", options }) }),
                  "add variant",
                );
              }}
            >
              Add variant
            </button>
            <h3>Publish</h3>
            <button onClick={() => run(() => api(`/api/v1/banks/${bank.id}/publish`, { method: "POST", body: "{}" }), "publish")}>
              Publish new version
            </button>
            <p>Versions: {bank.versions.map((v) => `v${v.version}`).join(", ") || "none yet"}</p>
          </div>
        )}
      </section>

      <section>
        <h2>Bind content to exam</h2>
        <input value={examId} onChange={(e) => setExamId(e.target.value)} placeholder="Exam id" size={40} />
        <select value={selVersion} onChange={(e) => setSelVersion(e.target.value)}>
          <option value="">Select version</option>
          {(bank?.versions || []).map((v) => (
            <option key={v.id} value={v.id}>v{v.version}</option>
          ))}
        </select>
        <label>
          <input type="checkbox" checked={allowBack} onChange={(e) => setAllowBack(e.target.checked)} /> allow back-navigation
        </label>
        <input value={duration} onChange={(e) => setDuration(e.target.value)} placeholder="Duration (s)" style={{ width: 120 }} />
        <button
          onClick={() =>
            run(
              () => api(`/api/v1/exams/${examId}/content`, { method: "PATCH", body: JSON.stringify({ content_version_id: selVersion, allow_back_navigation: allowBack, duration_s: Number(duration) || null }) }),
              "bind content",
            )
          }
        >
          Bind
        </button>
      </section>

      <section>
        <h2>Candidate login codes</h2>
        <input value={enrollmentId} onChange={(e) => setEnrollmentId(e.target.value)} placeholder="Enrollment id" size={40} />
        <button onClick={() => run(() => api(`/api/v1/enrollments/${enrollmentId}/candidate-code`, { method: "POST", body: "{}" }), "issue code")}>
          Issue code (shown once — copy it)
        </button>
        <button
          onClick={() => run(() => api(`/api/v1/enrollments/${enrollmentId}/candidate-codes`), "code status")}
        >
          Code status
        </button>
      </section>

      {out && <pre>{out}</pre>}
      {err && <pre style={{ color: "crimson" }}>{err}</pre>}
    </main>
  );
}
