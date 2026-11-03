import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { AiKey, LocalRow } from "../../lib/ai";
import { LocalDetect } from "./LocalDetect";

afterEach(cleanup);

const row = (over: Partial<LocalRow>): LocalRow => ({ provider: "ollama", name: "Ollama (local)", url: "http://127.0.0.1:11434/api/tags", base_url: "http://127.0.0.1:11434", running: false, models: [], model: null, fix: "Ollama is not running on this computer. Install it from https://ollama.com, start it, then come back here.", ms: null, ...over });
const key: AiKey = { id: "k9", provider: "ollama", label: "Ollama", masked: "(none)", model: "qwen3:4b", priority: 10, status: "active", scope: "local", state: {}, base_url: "http://127.0.0.1:11434" };

describe("LocalDetect", () => {
  it("offers 'Use it' only for a running server with a model, and hands back that row", () => {
    const onUse = vi.fn();
    const running = row({ running: true, models: ["qwen3:4b", "llava"], model: "qwen3:4b", fix: null, ms: 9 });
    render(<LocalDetect rows={[running, row({ provider: "lmstudio", name: "LM Studio (local)", fix: "LM Studio is not running." })]} keys={[]} onUse={onUse} busy={false} />);
    expect(screen.getByText("qwen3:4b, llava")).toBeInTheDocument();
    expect(screen.getByText("LM Studio is not running.")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /Use it/ });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onUse).toHaveBeenCalledWith(running);
  });

  it("repeats the fix when a server runs without a model, and says when the key already exists", () => {
    const noModel = row({ running: true, fix: "Ollama is running but no model is pulled. Open a terminal and run: ollama pull qwen3:4b" });
    render(<LocalDetect rows={[noModel]} keys={[]} onUse={vi.fn()} busy={false} />);
    expect(screen.getByText(/ollama pull qwen3:4b/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Use it/ })).toBeNull();
    cleanup();
    render(<LocalDetect rows={[row({ running: true, models: ["qwen3:4b"], model: "qwen3:4b", fix: null })]} keys={[key]} onUse={vi.fn()} busy={false} />);
    expect(screen.getByText("Added")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Use it/ })).toBeNull();
  });

  it("says it is looking while the probe runs", () => {
    render(<LocalDetect rows={undefined} keys={[]} onUse={vi.fn()} busy={false} />);
    expect(screen.getByRole("status")).toHaveTextContent(/Looking for Ollama and LM Studio/);
  });
});
