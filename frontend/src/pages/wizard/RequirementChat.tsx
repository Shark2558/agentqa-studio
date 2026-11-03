import { ChatCircleDots, Robot } from "@phosphor-icons/react";
import type { ChatResult } from "../../lib/api";

type Props = {
  chat: ChatResult;
  answers: Record<string, string>;
  confirmed: boolean;
  isSaving: boolean;
  onAnswer: (id: string, answer: string) => void;
  onConfirm: () => void;
};

/** The Requirement Chat agent's reply: the list it read, and up to five questions back. */
export function RequirementChat({ chat, answers, confirmed, isSaving, onAnswer, onConfirm }: Props) {
  const fromAi = chat.source === "ai";
  return (
    <section className="card flat chat" aria-labelledby="h-chat">
      <h2 id="h-chat">
        {fromAi ? <Robot aria-hidden="true" /> : <ChatCircleDots aria-hidden="true" />}
        What I understood
        {fromAi && <span className="pill info">proposed by AI — please confirm</span>}
      </h2>
      {chat.items.length === 0 && <p className="muted">I could not find a requirement in that text yet. Try one sentence per line, starting with what the application must do.</p>}
      <ol className="req-list">
        {chat.items.map((item) => (
          <li key={item.id}>
            <span className="mono small muted">{item.id}</span>
            <span>
              {item.text}
              {item.flags.map((f) => (
                <span key={f.word} className="pill warn" title={f.why}>
                  “{f.word}” — {f.why}
                </span>
              ))}
            </span>
          </li>
        ))}
      </ol>
      {chat.questions.length > 0 && (
        <>
          <h3>A few questions before the agents start</h3>
          {chat.questions.map((q) => (
            <div key={q.id} className="chat-q">
              <label htmlFor={`answer-${q.id}`}>{q.question}</label>
              <input
                id={`answer-${q.id}`}
                value={answers[q.id] ?? ""}
                placeholder="Your answer (you may leave it blank)"
                onChange={(e) => onAnswer(q.id, e.target.value)}
              />
            </div>
          ))}
        </>
      )}
      <div className="row-end">
        {confirmed ? (
          <span className="pill ok">Confirmed and saved</span>
        ) : (
          <button className="btn primary" type="button" onClick={onConfirm} disabled={isSaving || chat.items.length === 0}>
            {isSaving ? "Saving…" : "Looks right"}
          </button>
        )}
      </div>
    </section>
  );
}
