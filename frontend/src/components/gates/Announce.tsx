/** A page's one polite live region, always in the page so screen readers hear every change put into it ("Answer
 *  saved.", "The test plan is approved."); a region added at the moment of the news is announced unreliably. */
export function Announce({ text }: { text: string }) {
  return <p className="sr-only" role="status" aria-label="Updates">{text}</p>;
}
