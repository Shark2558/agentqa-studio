import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { Bandaids, Bug, ClipboardText, ClockCounterClockwise, FolderOpen, ImagesSquare, ListChecks, Pulse, Question, Robot, SquaresFour } from "@phosphor-icons/react";
import { navBadges, type Badge } from "../lib/gates";
import { useGateCounts } from "../lib/useGateCounts";

type Props = {
  /** The project the person is inside, if any (never the wizard's `new`). */
  slug: string | null;
  /** Called when a link is chosen (the drawer closes itself with it). */
  onNavigate?: () => void;
};

type LinkProps = { to: string; label: string; icon: ReactNode; badge?: Badge | null; end?: boolean; onNavigate?: () => void };

/** A destination; a badge says what waits there, and its spoken name says it in words ("Questions, 15 open"). */
function Item({ to, label, icon, badge, end, onNavigate }: LinkProps) {
  return (
    <NavLink to={to} end={end} onClick={onNavigate} aria-label={badge ? `${label}, ${badge.name}` : undefined}>
      {icon}
      {label}
      {badge && <span className="nav-badge" aria-hidden="true">{badge.text}</span>}
    </NavLink>
  );
}

/** The one list of destinations, shared by the sidebar and the phone drawer. Live View is always listed. */
export function NavLinks({ slug, onNavigate }: Props) {
  const project = slug ? `/projects/${encodeURIComponent(slug)}` : null;
  const badges = navBadges(useGateCounts(slug).data);
  return (
    <div className="nav">
      <div className="nav-sect">Overview</div>
      <Item to="/" end label="Projects" icon={<FolderOpen aria-hidden="true" />} onNavigate={onNavigate} />
      <Item to={project ? `${project}/live` : "/live"} label="Live View" icon={<Pulse aria-hidden="true" />} onNavigate={onNavigate} />
      {project && (
        <>
          <div className="nav-sect">This project</div>
          <Item to={project} end label="Overview" icon={<SquaresFour aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/requirements`} label="Requirements" icon={<ListChecks aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/questions`} label="Questions" badge={badges.questions} icon={<Question aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/plan`} label="Test plan" badge={badges.plan} icon={<ClipboardText aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/defects`} label="Defects" badge={badges.defects} icon={<Bug aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/visual`} label="Visual review" badge={badges.visual} icon={<ImagesSquare aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/heals`} label="Heals" badge={badges.heals} icon={<Bandaids aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/changes`} label="Change log" icon={<ClockCounterClockwise aria-hidden="true" />} onNavigate={onNavigate} />
          <Item to={`${project}/ai`} label="AI" icon={<Robot aria-hidden="true" />} onNavigate={onNavigate} />
        </>
      )}
    </div>
  );
}
