import { useRef, type MouseEvent } from "react";

/** A dialog's backdrop closes it only for a click that began on the backdrop too: a drag that starts in a box of the
 *  dialog (selecting typed text) and ends outside it is not a click on the backdrop, and must not lose what was typed.
 *  Spread the result on the backdrop element. */
export function useBackdropClose(onClose: () => void) {
  const pressedOnBackdrop = useRef(false);
  return {
    onMouseDown: (e: MouseEvent<HTMLElement>) => {
      pressedOnBackdrop.current = e.target === e.currentTarget;
    },
    onClick: (e: MouseEvent<HTMLElement>) => {
      const whole = pressedOnBackdrop.current && e.target === e.currentTarget;
      pressedOnBackdrop.current = false;
      if (whole) onClose();
    },
  };
}
