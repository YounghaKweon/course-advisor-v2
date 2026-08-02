import { useEffect, useState } from "react";
import { TICKER_LINES } from "./tickerLines";

// Two of these are real questions from the v1 conversation logs —
// including the one v1 couldn't answer.
const EXAMPLES = [
  "I want to take AI related classes",
  "I want a CS class in the afternoon",
  "Who teaches Nutrition this fall?",
];

type Status = "idle" | "loading" | "done" | "error";

export default function App() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [tickerIndex, setTickerIndex] = useState(0);
  const [ambientIndex, setAmbientIndex] = useState(0);
  const [ambientVisible, setAmbientVisible] = useState(true);

  // Fast ticker while Gemini reads the catalog
  useEffect(() => {
    if (status !== "loading") return;
    const id = setInterval(() => {
      setTickerIndex((i) => (i + 1) % TICKER_LINES.length);
    }, 350);
    return () => clearInterval(id);
  }, [status]);

  // Slow ambient pulse of the catalog when not loading
  useEffect(() => {
    if (status === "loading") return;
    const id = setInterval(() => {
      setAmbientVisible(false);
      setTimeout(() => {
        setAmbientIndex((i) => (i + 1) % TICKER_LINES.length);
        setAmbientVisible(true);
      }, 400);
    }, 4000);
    return () => clearInterval(id);
  }, [status]);

  async function ask(q: string) {
    const trimmed = q.trim();
    if (!trimmed || status === "loading") return;
    setQuestion(trimmed);
    setAnswer("");
    setStatus("loading");
    try {
      const res = await fetch(
        `${import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"}/ask`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: trimmed }),
        },
      );
      if (!res.ok) throw new Error(`server responded ${res.status}`);
      const data = await res.json();
      setAnswer(data.answer);
      setStatus("done");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="ledger-paper min-h-screen font-body text-ink">
      <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 px-6 py-14">
        <header className="double-rule pb-8">
          <p className="font-mono text-xs font-medium uppercase tracking-[0.25em] text-maroon">
            Calvin University · Fall 2025
          </p>
          <h1 className="mt-3 font-display text-6xl font-bold tracking-tight">
            Course Advisor
          </h1>
        </header>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="flex gap-3"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="ask about fall 2025 courses"
            aria-label="Your question about Fall 2025 courses"
            className="flex-1 rounded-md border border-rule bg-white px-4 py-3.5 font-mono text-sm outline-none focus-visible:outline-2 focus-visible:outline-gold"
          />
          <button
            type="submit"
            disabled={status === "loading"}
            className="rounded-md bg-maroon px-7 py-3.5 text-sm font-semibold text-white transition-colors hover:bg-maroon/90 focus-visible:outline-2 focus-visible:outline-gold disabled:opacity-60"
          >
            Ask
          </button>
        </form>

        {status === "idle" && (
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => ask(ex)}
                className="rounded-full border border-rule bg-white px-4 py-2 font-mono text-xs text-ink/80 transition-colors hover:border-maroon hover:text-maroon focus-visible:outline-2 focus-visible:outline-gold"
              >
                {ex}
              </button>
            ))}
          </div>
        )}

        {status === "loading" && (
          <div className="rounded-md border border-rule bg-white p-5">
            <p className="font-mono text-xs text-ink/50">
              reading the catalog…
            </p>
            <p className="mt-2 truncate font-mono text-sm text-maroon">
              {TICKER_LINES[tickerIndex]}
            </p>
          </div>
        )}

        {status === "done" && (
          <article className="answer-enter rounded-md border border-l-4 border-rule border-l-maroon bg-white p-6">
            <p className="whitespace-pre-wrap text-sm leading-relaxed">
              {answer}
            </p>
          </article>
        )}

        {status === "error" && (
          <div className="rounded-md border border-l-4 border-maroon/40 border-l-maroon bg-white p-5">
            <p className="text-sm">
              Couldn't reach the advisor service. Check that the backend is
              running on port 8000, then ask again.
            </p>
          </div>
        )}

        <footer className="mt-auto border-t border-rule pt-4">
          <p className="font-mono text-[11px] uppercase tracking-widest text-ink/40">
            1,021 sections on file
          </p>
          <p
            className={`ambient-line mt-1 truncate font-mono text-xs text-ink/50 ${
              ambientVisible ? "opacity-100" : "opacity-0"
            }`}
          >
            {TICKER_LINES[ambientIndex]}
          </p>
        </footer>
      </main>
    </div>
  );
}
