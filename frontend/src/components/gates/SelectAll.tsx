import { useEffect, useRef } from "react";
import type { Selection } from "../../lib/gates";

type Props = {
  ids: readonly string[];
  selected: Selection;
  /** What is listed: [one, many], e.g. ["defect", "defects"]. */
  noun: readonly [string, string];
  onToggleAll: (ids: readonly string[], on: boolean) => void;
};

/** "Select the N <nouns> shown": one labelled box above a list. The count is in the name, so a list that shows the first
 *  50 of 120 is not read as all of them. Ticked when every item shown is selected, part-ticked when some are (React has
 *  no prop for `indeterminate`); a click from part-ticked selects them all. It shows at every width. */
export function SelectAll({ ids, selected, noun, onToggleAll }: Props) {
  const box = useRef<HTMLInputElement>(null);
  const count = ids.filter((id) => selected.has(id)).length;
  const allOn = ids.length > 0 && count === ids.length;
  useEffect(() => {
    if (box.current) box.current.indeterminate = count > 0 && !allOn;
  }, [count, allOn]);
  if (ids.length === 0) return null;
  return (
    <label className="check select-all">
      <input ref={box} type="checkbox" checked={allOn} onChange={() => onToggleAll(ids, !allOn)} />
      Select the {ids.length} {ids.length === 1 ? noun[0] : noun[1]} shown
    </label>
  );
}
