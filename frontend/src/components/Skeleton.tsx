type Props = {
  /** How many placeholder cards to draw while the real ones load. */
  cards?: number;
};

/** Placeholder agent cards that keep the layout while the run list loads; they pulse only inside an aria-busy region. */
export function SkeletonCards({ cards = 3 }: Props) {
  return (
    <div className="agents one-col" aria-hidden="true">
      {Array.from({ length: cards }, (_, i) => (
        <div key={i} className="agent idle">
          <div className="skel" style={{ width: "55%" }} />
          <div className="skel" style={{ width: "80%", marginTop: 8 }} />
          <div className="skel" style={{ width: "30%", marginTop: 10, minHeight: 10 }} />
        </div>
      ))}
    </div>
  );
}
