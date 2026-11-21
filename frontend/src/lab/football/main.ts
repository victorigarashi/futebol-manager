import "./lab.css";

/**
 * Football Research & Animation Lab (dev only: /football-lab.html, never in the public menu).
 * Each tab is an isolated module mounted on demand; nothing here decides a match result.
 */
export type TabModule = { mount: (host: HTMLElement, panel: HTMLElement) => (() => void) | void };
type TabDef = { id: string; label: string; load: () => Promise<TabModule> };

const TABS: TabDef[] = [
  { id: "characters", label: "Characters", load: () => import("./tabs/characters") },
  { id: "animation", label: "Animation", load: () => import("./tabs/animation") },
  { id: "goalkeeper", label: "Goalkeeper", load: () => import("./tabs/goalkeeper") },
  { id: "sprites", label: "Sprites", load: () => import("./tabs/sprites") },
  { id: "physics", label: "Physics", load: () => import("./tabs/physics") },
  { id: "ai", label: "Football AI", load: () => import("./tabs/ai") },
  { id: "performance", label: "Performance", load: () => import("./tabs/performance") },
];

const nav = document.getElementById("tabs")!;
const view = document.getElementById("view")!;
const panel = document.getElementById("panel")!;
let dispose: (() => void) | void;

function params(): URLSearchParams { return new URLSearchParams(location.hash.slice(1)); }

async function open(id: string) {
  const tab = TABS.find((t) => t.id === id) ?? TABS[0];
  for (const b of nav.querySelectorAll("button")) b.classList.toggle("on", b.dataset.tab === tab.id);
  if (dispose) dispose();
  view.replaceChildren(); panel.replaceChildren();
  document.body.dataset.ready = "0";
  const mod = await tab.load();
  dispose = mod.mount(view, panel);
  document.body.dataset.tab = tab.id;
  document.body.dataset.ready = "1";
}

for (const t of TABS) {
  const b = document.createElement("button");
  b.textContent = t.label; b.dataset.tab = t.id;
  b.addEventListener("click", () => { const p = params(); p.set("tab", t.id); location.hash = p.toString(); });
  nav.append(b);
}
window.addEventListener("hashchange", () => { const id = params().get("tab") ?? "characters"; if (id !== document.body.dataset.tab) void open(id); });
void open(params().get("tab") ?? "characters");

export function hashParam(name: string): string | null { return params().get(name); }
