import { useState } from "react";

type Props = { src: string; alt: string; width: number; height: number; href?: string };

export const MISSING = "The picture file is missing or could not be loaded";

/** A picture from a guarded file route (evidence, a visual-review screen). When it fails to load (its file is gone, or
 *  the server could not send it) it says so in words instead of a broken-image icon, and offers no link to it. */
export function Picture({ src, alt, width, height, href }: Props) {
  const [broken, setBroken] = useState<string | null>(null);
  if (broken === src) {
    return <span className="pic-missing"><span className="sr-only">{alt}: </span>{MISSING}</span>;
  }
  const img = <img src={src} alt={alt} width={width} height={height} loading="lazy" onError={() => setBroken(src)} />;
  return href ? <a href={href} target="_blank" rel="noopener noreferrer">{img}</a> : img;
}
