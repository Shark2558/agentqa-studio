import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle, FileText, Trash, UploadSimple, Warning, XCircle } from "@phosphor-icons/react";
import { ApiError, api, upload, type ChatResult, type DocumentInfo } from "../../lib/api";
import { RequirementChat } from "./RequirementChat";

const ACCEPT = ".docx,.doc,.pdf,.xlsx,.xlsm,.xls,.csv,.html,.htm,.json,.md,.txt,.png,.jpg,.jpeg";
const VERDICT = {
  read: { label: "read in full", pill: "ok", icon: <CheckCircle aria-hidden="true" /> },
  partly: { label: "partly read", pill: "warn", icon: <Warning aria-hidden="true" /> },
  unread: { label: "not read", pill: "bad", icon: <XCircle aria-hidden="true" /> },
} as const;

type Props = {
  slug: string;
  documents: DocumentInfo[];
  typed: string;
  chat: ChatResult | null;
  answers: Record<string, string>;
  confirmed: boolean;
  onDocument: (doc: DocumentInfo) => void;
  onRemoveDocument: (name: string) => void;
  onTyped: (value: string) => void;
  onChat: (chat: ChatResult) => void;
  onAnswer: (id: string, answer: string) => void;
  onConfirm: () => void;
};

/** Step 2: documents (with upload progress and the reader's verdict) and/or typed requirements with the chat. */
export function StepRequirements(p: Props) {
  const [progress, setProgress] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const sheet = useRef<HTMLInputElement>(null);

  async function send(files: FileList | null, folder: "documents" | "imports") {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setProgress(0);
    try {
      const saved = await upload(api.uploadUrl(p.slug, folder), Array.from(files), setProgress);
      if (folder === "documents") saved.forEach(p.onDocument);
    } catch (e) {
      setUploadError(e instanceof ApiError ? e.message : "The upload failed");
    } finally {
      setProgress(null);
    }
  }

  const remove = useMutation({
    mutationFn: (name: string) => api.deleteDocument(p.slug, name),
    onSuccess: (_, name) => p.onRemoveDocument(name),
  });
  const ask = useMutation({
    mutationFn: () => api.typedRequirements(p.slug, p.typed),
    onSuccess: p.onChat,
  });
  const confirm = useMutation({
    mutationFn: () =>
      api.typedRequirements(
        p.slug,
        p.typed,
        (p.chat?.questions ?? []).map((q) => ({ question: q.question, answer: p.answers[q.id] ?? "", topic: q.topic })),
        (p.chat?.items ?? []).map((i) => i.text),        // the list as confirmed, AI-proposed or not
      ),
    onSuccess: p.onConfirm,
  });
  const chatError = [ask.error, confirm.error].find((e) => e instanceof ApiError) as ApiError | undefined;
  const removeError = remove.error instanceof ApiError ? remove.error.message : remove.error ? "The document could not be removed" : null;

  return (
    <div className="grid g-two">
      <section aria-labelledby="h-docs">
        <h2 id="h-docs">Documents</h2>
        <div
          className={`drop ${dragging ? "over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            void send(e.dataTransfer.files, "documents");
          }}
        >
          <UploadSimple aria-hidden="true" />
          <p>Drop SRS, PRD, user manuals or screenshots here</p>
          <p className="muted small">Word, PDF (scanned too), Excel, CSV, HTML, JSON, Markdown, text, images · up to 50 MB each</p>
          <button className="btn" type="button" onClick={() => picker.current?.click()} disabled={progress !== null}>
            Choose files
          </button>
          <input ref={picker} type="file" multiple accept={ACCEPT} hidden onChange={(e) => void send(e.target.files, "documents")} />
        </div>
        {progress !== null && (
          <progress className="upload" value={progress} max={1} aria-label="Upload progress">
            {Math.round(progress * 100)}%
          </progress>
        )}
        {(uploadError ?? removeError) && (
          <p className="notice bad" role="alert">
            {uploadError ?? removeError}
          </p>
        )}
        <ul className="list docs">
          {p.documents.map((d) => {
            const v = VERDICT[d.status];
            return (
              <li key={d.name} className="list-row static">
                <span>
                  <FileText aria-hidden="true" />
                  <b>{d.name}</b>
                  <span className="muted small">
                    {d.segments} piece{d.segments === 1 ? "" : "s"} of text{d.detail ? ` · ${d.detail}` : ""}
                  </span>
                </span>
                <span className="row">
                  <span className={`pill ${v.pill}`}>
                    {v.icon}
                    {v.label}
                  </span>
                  <button className="btn sm" type="button" aria-label={`Remove ${d.name}`} onClick={() => remove.mutate(d.name)}>
                    <Trash aria-hidden="true" />
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
        <details className="mt-4">
          <summary>Already have a manual test sheet?</summary>
          <p className="muted small">An Excel or CSV sheet of existing test cases is imported alongside the generated ones.</p>
          <button className="btn sm" type="button" onClick={() => sheet.current?.click()} disabled={progress !== null}>
            Add a test sheet
          </button>
          <input ref={sheet} type="file" accept=".xlsx,.xls,.csv" hidden onChange={(e) => void send(e.target.files, "imports")} />
        </details>
      </section>

      <section aria-labelledby="h-typed">
        <h2 id="h-typed">Or describe what the application must do</h2>
        <textarea
          id="w-typed"
          aria-label="Typed requirements"
          rows={10}
          placeholder={"One idea per line works best, for example:\n- Citizens apply for a birth certificate online.\n- A clerk must verify each application within 2 working days.\n- The portal sends an SMS when the certificate is ready."}
          value={p.typed}
          onChange={(e) => p.onTyped(e.target.value)}
        />
        <div className="row-end">
          <button className="btn" type="button" onClick={() => ask.mutate()} disabled={p.typed.trim().length === 0 || ask.isPending}>
            {ask.isPending ? "Reading…" : "Check my text"}
          </button>
        </div>
        {chatError && (
          <p className="notice bad" role="alert">
            {chatError.message}
          </p>
        )}
        {p.chat && (
          <RequirementChat chat={p.chat} answers={p.answers} confirmed={p.confirmed} isSaving={confirm.isPending} onAnswer={p.onAnswer} onConfirm={() => confirm.mutate()} />
        )}
      </section>
    </div>
  );
}
