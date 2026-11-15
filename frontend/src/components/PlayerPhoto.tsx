import { useState } from "react";

type Props = { name: string; photoUrl?: string | null; size?: "xs" | "sm" | "md" | "lg"; className?: string };

function initials(name: string): string {
  return name.split(" ").filter(Boolean).map((word) => word[0]).slice(0, 2).join("").toUpperCase();
}

/** Player face from the squad list; falls back to initials when absent or when the image fails. */
export function PlayerPhoto({ name, photoUrl, size = "sm", className = "" }: Props) {
  const [failed, setFailed] = useState(false);
  const classes = `player-photo player-photo--${size} ${className}`.trim();
  if (!photoUrl || failed) return <span className={`${classes} player-photo--fallback`} aria-hidden="true">{initials(name)}</span>;
  return <img className={classes} src={photoUrl} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}
