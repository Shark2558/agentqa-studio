/** The site map (ported from the v0.8 player): the screens the Explorer and the Exploratory Tester reached, by click
 *  depth, with the roles that reached each one and any HTTP error. Paths come from the application under test, so
 *  they are only ever keys of a Map and text on the page. */
import { num, safeShot, text, type LiveEvent } from "./event";

const MAP_AGENTS = new Set(["explorer", "exploratory"]);
const MAX_DEPTH = 8;
const MAX_NODES = 300;                 // a crawler that invents paths must not grow the map without end
const column = (n: number): number => Math.min(MAX_DEPTH, Math.max(0, Math.floor(n)));
const NODE_W = 176;
const NODE_H = 40;
const GAP_X = 214;
const GAP_Y = 52;
const PAD = 16;
const MIN_WIDTH = 400;
const HTTP_ERROR = 400;

export interface MapNode {
  readonly path: string;
  readonly depth: number;
  readonly parent: string | null;
  readonly roles: readonly string[];
  readonly status: number | null;
  readonly title: string;
  readonly shot: string | null;
}

export interface SiteMap {
  readonly nodes: ReadonlyMap<string, MapNode>;
  readonly order: readonly string[];
  readonly current: string | null;
}

export const emptyMap: SiteMap = { nodes: new Map(), order: [], current: null };

const keyOf = (path: string) => path.split("?")[0] || "/";

function added(nodes: ReadonlyMap<string, MapNode>, key: string, e: LiveEvent): MapNode {
  const known = nodes.get(key);
  const parentPath = text(e, "parent");
  const parent = parentPath ? keyOf(parentPath) : (known?.parent ?? null);
  const parentNode = parent ? nodes.get(parent) : undefined;
  const depth = known?.depth ?? column(num(e, "depth") ?? (parentNode ? parentNode.depth + 1 : key === "/" ? 0 : 1));
  const role = text(e, "role") ?? "anonymous";
  const status = num(e, "status") ?? null;
  const keepStatus = status !== null && (status >= HTTP_ERROR || known?.status == null) ? status : (known?.status ?? null);
  return {
    path: key, depth, parent: known?.parent ?? parent,
    roles: known?.roles.includes(role) ? known.roles : [...(known?.roles ?? []), role],
    status: keepStatus, title: text(e, "page_title") ?? known?.title ?? "", shot: safeShot(e.shot) ?? known?.shot ?? null,
  };
}

export function foldMap(map: SiteMap, events: readonly LiveEvent[]): SiteMap {
  let nodes: Map<string, MapNode> | null = null;
  let order: string[] | null = null;
  let current = map.current;
  for (const e of events) {
    const path = e.kind === "navigate" ? text(e, "path") : undefined;
    if (!path) continue;
    const key = keyOf(path);
    const known = (nodes ?? map.nodes).has(key);
    if (e.probe === true || !MAP_AGENTS.has(e.agent)) {
      if (known) current = key;                               // a check or another agent's visit only moves the marker
      continue;
    }
    if (!known && (order ?? map.order).length >= MAX_NODES) continue;
    nodes = nodes ?? new Map(map.nodes);
    order = order ?? [...map.order];
    if (!known) order.push(key);
    nodes.set(key, added(nodes, key, e));
    current = key;
  }
  return nodes && order ? { nodes, order, current } : current === map.current ? map : { ...map, current };
}

export interface MapLayout {
  width: number;
  height: number;
  nodes: (MapNode & { x: number; y: number; current: boolean })[];
  edges: { from: string; to: string }[];
}

/** Columns by depth (capped at 8), rows in the order the screens were found. */
export function layoutMap(map: SiteMap): MapLayout {
  const perColumn = new Map<number, number>();
  const placed = map.order.flatMap((path) => {
    const n = map.nodes.get(path);
    if (!n) return [];
    const column = Math.min(n.depth, MAX_DEPTH);
    const row = perColumn.get(column) ?? 0;
    perColumn.set(column, row + 1);
    return [{ ...n, x: PAD + column * GAP_X, y: PAD + row * GAP_Y, current: path === map.current }];
  });
  const columns = Math.max(0, ...perColumn.keys()) + 1;
  const rows = Math.max(1, ...perColumn.values());
  const edges = placed.filter((n) => n.parent && n.parent !== n.path && map.nodes.has(n.parent)).map((n) => ({ from: n.parent as string, to: n.path }));
  return { width: Math.max(PAD + columns * GAP_X, MIN_WIDTH), height: PAD + 8 + rows * GAP_Y, nodes: placed, edges };
}

export const MAP_NODE = { width: NODE_W, height: NODE_H } as const;
