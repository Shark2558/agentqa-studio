/** The Live View fixtures: a trimmed real demo recording as the API serves it (447 events, each with its phase), the
 *  board the server sends for it, and the final picture counted independently from the raw events by a script over
 *  the backend copy of the recording (not by the code under test). */
import demo from "./live-demo.json";
import boardJson from "./live-board.json";
import expected from "./live-expected-summary.json";
import type { BoardDef } from "../lib/live/board";

export const demoEvents: unknown[] = demo.events;
export const demoSession: string = demo.session;
export const demoBoard = boardJson as unknown as BoardDef;
export const expectedSummary = expected;
