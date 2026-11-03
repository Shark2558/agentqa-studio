/** A stand-in for the browser's WebSocket in component and hook tests: every socket the code opens is kept in
 *  `FakeSocket.all`, and a test plays the server with `deliver` (opens it and sends frames) or `drop` (closes it). */
import { act } from "@testing-library/react";

export class FakeSocket {
  static all: FakeSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }

  close() {}

  deliver(frames: unknown[], open = true) {
    act(() => {
      if (open) this.onopen?.();
      for (const f of frames) this.onmessage?.({ data: JSON.stringify(f) });
    });
  }

  drop(code: number) {
    act(() => this.onclose?.({ code }));
  }
}
