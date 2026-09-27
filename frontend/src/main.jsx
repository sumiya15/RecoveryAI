import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ClipboardCheck, Loader2, Radio, Rocket, Send, ShieldAlert, Wand2 } from "lucide-react";
import "./styles.css";

const starter = {
  product_brief:
    "Launch Desk helps engineering teams turn rough release ideas into practical launch plans, readiness checks, risks, owner checklists, and launch copy.",
  audience: "Engineering managers and product-minded tech leads",
  launch_date: "2026-09-30",
  constraints: "Two-week timeline, limited design support, API docs must be ready",
  available_assets: "Beta notes, product screenshots, draft changelog",
};

function App() {
  const [form, setForm] = useState(starter);
  const [events, setEvents] = useState([]);
  const [answer, setAnswer] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const progress = useMemo(() => events.filter((event) => event.type !== "text_delta"), [events]);

  async function submit(event) {
    event.preventDefault();
    setRunning(true);
    setError("");
    setEvents([]);
    setAnswer("");

    try {
      const response = await fetch("http://127.0.0.1:8000/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      if (!response.ok || !response.body) {
        throw new Error(await response.text());
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";

        for (const chunk of chunks) {
          const line = chunk.split("\n").find((item) => item.startsWith("data: "));
          if (!line) continue;
          const parsed = JSON.parse(line.slice(6));
          if (parsed.type === "text_delta") {
            setAnswer((current) => current + parsed.delta);
          } else if (parsed.type === "error") {
            setError(parsed.message);
          } else {
            setEvents((current) => [...current, parsed]);
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setRunning(false);
    }
  }

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  return (
    <main className="shell">
      <section className="topbar">
        <div className="brand">
          <span className="brandMark"><Rocket size={22} /></span>
          <div>
            <h1>Launch Desk</h1>
            <p>Agentic release planning for engineering teams</p>
          </div>
        </div>
        <div className="statusPill">
          <Radio size={16} />
          Agents SDK streaming
        </div>
      </section>

      <section className="workspace">
        <form className="intake" onSubmit={submit}>
          <div className="panelHeader">
            <Wand2 size={20} />
            <h2>Launch intake</h2>
          </div>

          <label>
            Product brief
            <textarea value={form.product_brief} onChange={(e) => update("product_brief", e.target.value)} />
          </label>

          <div className="two">
            <label>
              Audience
              <input value={form.audience} onChange={(e) => update("audience", e.target.value)} />
            </label>
            <label>
              Launch date
              <input type="date" value={form.launch_date} onChange={(e) => update("launch_date", e.target.value)} />
            </label>
          </div>

          <label>
            Constraints
            <textarea className="short" value={form.constraints} onChange={(e) => update("constraints", e.target.value)} />
          </label>

          <label>
            Available assets
            <textarea className="short" value={form.available_assets} onChange={(e) => update("available_assets", e.target.value)} />
          </label>

          <button disabled={running} className="primary">
            {running ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
            {running ? "Planning..." : "Generate release plan"}
          </button>
        </form>

        <section className="output">
          <div className="panelHeader">
            <ClipboardCheck size={20} />
            <h2>Agent run</h2>
          </div>

          <div className="progressRail">
            {progress.length === 0 && <span className="muted">Progress events will appear here.</span>}
            {progress.map((event, index) => (
              <div className="progressItem" key={`${event.type}-${index}`}>
                <ShieldAlert size={15} />
                <span>{event.message || `${event.tool} ${event.status}`}</span>
              </div>
            ))}
          </div>

          {error && <div className="error">{error}</div>}

          <article className="answer">
            {answer ? <pre>{answer}</pre> : <span className="muted">The launch plan will stream in progressively.</span>}
          </article>
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
