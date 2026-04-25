// Kenji — shared UI primitives (1:1 port of ui.jsx)
import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

type IconName =
  | "sparkles" | "arrow" | "check" | "x" | "dot" | "mail" | "search" | "file"
  | "sliders" | "bolt" | "brain" | "send" | "pin" | "external" | "target"
  | "doc" | "book" | "pause" | "mic" | "plus" | "settings" | "pencil" | "split"
  | "copy" | "chevron" | "chevronDown" | "wand" | "globe" | "leaf" | "pipe";

export function Icon({ name, size = 16, className = "", style }: { name: IconName; size?: number; className?: string; style?: CSSProperties }) {
  const paths: Record<IconName, ReactNode> = {
    sparkles: <><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z"/><path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14z"/></>,
    arrow: <path d="M5 12h14m-6-6l6 6-6 6"/>,
    check: <path d="M4 12l5 5L20 6"/>,
    x: <path d="M6 6l12 12M18 6L6 18"/>,
    dot: <circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>,
    mail: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></>,
    file: <><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></>,
    sliders: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2" fill="currentColor" stroke="none"/><circle cx="8" cy="17" r="2" fill="currentColor" stroke="none"/></>,
    bolt: <path d="M13 3L4 14h7l-1 7 9-11h-7l1-7z"/>,
    brain: <><path d="M9 4a3 3 0 0 0-3 3v0a3 3 0 0 0-2 5v0a3 3 0 0 0 2 5v0a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3v0a3 3 0 0 0 2-5v0a3 3 0 0 0-2-5v0a3 3 0 0 0-3-3z"/></>,
    send: <path d="M4 12l16-8-5 16-3-7-8-1z"/>,
    pin: <><path d="M12 3l4 5v5l3 3H5l3-3V8z"/><path d="M12 16v5"/></>,
    external: <><path d="M14 4h6v6"/><path d="M20 4L10 14"/><path d="M18 12v6H6V6h6"/></>,
    target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/></>,
    doc: <><path d="M6 3h9l4 4v14H6z"/><path d="M9 12h8M9 16h6M9 8h4"/></>,
    book: <><path d="M4 4h7a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4z"/><path d="M20 4h-7a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h8z"/></>,
    pause: <><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></>,
    mic: <><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6l1.4 1.4m10 10l1.4 1.4M5.6 18.4l1.4-1.4m10-10l1.4-1.4"/></>,
    pencil: <><path d="M4 20h4l10-10-4-4L4 16z"/><path d="M14 6l4 4"/></>,
    split: <path d="M8 3v6M8 9c0 3 5 3 5 6v6M16 3v18"/>,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V4h12"/></>,
    chevron: <path d="M9 6l6 6-6 6"/>,
    chevronDown: <path d="M6 9l6 6 6-6"/>,
    wand: <><path d="M3 21l14-14"/><path d="M14 4l2 2M18 8l2 2M6 16l2 2"/></>,
    globe: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></>,
    leaf: <><path d="M20 4c0 10-8 16-16 16 0-10 8-16 16-16z"/><path d="M4 20c4-4 8-6 12-7"/></>,
    pipe: <><rect x="4" y="3" width="6" height="18" rx="1.5"/><rect x="14" y="3" width="6" height="18" rx="1.5"/></>,
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
      className={className} style={style} aria-hidden="true">
      {paths[name] || null}
    </svg>
  );
}

export function ScoreRing({ value, size = 48, stroke = 3 }: { value: number; size?: number; stroke?: number }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c - (value / 100) * c;
  const color = value >= 85 ? "var(--primary)" : value >= 70 ? "var(--tertiary)" : "var(--warn)";
  // Animate from hidden (c) to target on mount — transition fires because initial render uses c
  const [currentOff, setCurrentOff] = useState(c);
  useEffect(() => {
    const id = requestAnimationFrame(() => setCurrentOff(off));
    return () => cancelAnimationFrame(id);
  }, [off]);
  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size/2} cy={size/2} r={r} stroke="var(--outline-variant)" strokeWidth={stroke} fill="none"/>
        <circle cx={size/2} cy={size/2} r={r} stroke={color} strokeWidth={stroke}
          strokeDasharray={c} strokeDashoffset={currentOff} strokeLinecap="round" fill="none"
          style={{ transition: "stroke-dashoffset 700ms cubic-bezier(0.22, 1, 0.36, 1)" }}/>
      </svg>
      <div className="ring-val" style={{ fontSize: size <= 40 ? 12 : 14 }}>{value}</div>
    </div>
  );
}

export function Radar({ axes, size = 150 }: { axes: Record<string, number>; size?: number }) {
  const keys = Object.keys(axes);
  const cx = size/2, cy = size/2, r = size/2 - 20;
  const pts = keys.map((k, i) => {
    const a = (i / keys.length) * Math.PI * 2 - Math.PI/2;
    const v = axes[k] / 100;
    return [cx + Math.cos(a) * r * v, cy + Math.sin(a) * r * v];
  });
  return (
    <svg width={size} height={size}>
      {[0.33, 0.66, 1].map((lv, li) => (
        <polygon key={li}
          points={keys.map((_, i) => {
            const a = (i / keys.length) * Math.PI * 2 - Math.PI/2;
            return `${cx + Math.cos(a) * r * lv},${cy + Math.sin(a) * r * lv}`;
          }).join(" ")}
          fill="none" stroke="var(--outline-variant)" strokeWidth="1"/>
      ))}
      {keys.map((_, i) => {
        const a = (i / keys.length) * Math.PI * 2 - Math.PI/2;
        return <line key={i} x1={cx} y1={cy} x2={cx + Math.cos(a) * r} y2={cy + Math.sin(a) * r} stroke="var(--sc)" strokeWidth="1"/>;
      })}
      <polygon points={pts.map(p => p.join(",")).join(" ")}
        fill="var(--primary-tint)" stroke="var(--primary)" strokeWidth="1.5"/>
      {pts.map((p, i) => (<circle key={i} cx={p[0]} cy={p[1]} r="3" fill="var(--primary)"/>))}
      {keys.map((k, i) => {
        const a = (i / keys.length) * Math.PI * 2 - Math.PI/2;
        const lx = cx + Math.cos(a) * (r + 12);
        const ly = cy + Math.sin(a) * (r + 12);
        return (<text key={k} x={lx} y={ly} fontSize="10" fontFamily="'Inter', sans-serif" fontWeight="600" textAnchor="middle" dominantBaseline="middle" fill="var(--on-surface-variant)">{k}</text>);
      })}
    </svg>
  );
}

export function BarMeter({ value, max = 100, color = "var(--primary)" }: { value: number; max?: number; color?: string }) {
  const targetW = (value / max) * 100;
  const [w, setW] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setW(targetW));
    return () => cancelAnimationFrame(id);
  }, [targetW]);
  return (
    <div className="bar-meter">
      <div className="bar-meter-fill" style={{ width: `${w}%`, background: color, transition: "width 600ms cubic-bezier(0.22, 1, 0.36, 1)" }}/>
    </div>
  );
}

export function BrandMark({ size = 34 }: { size?: number }) {
  return <div className="brand-mark" style={{ width: size, height: size, fontSize: size * 0.5 }}>K</div>;
}

export function CoLogo({ letter, size = 32 }: { letter: string; color?: string; size?: number }) {
  const style: CSSProperties = {
    width: size, height: size, borderRadius: 10,
    background: "var(--sc)",
    color: "var(--on-surface)",
    display: "grid", placeItems: "center",
    fontFamily: "var(--font-display)", fontSize: size * 0.45, fontWeight: 700,
    flexShrink: 0,
    border: "1px solid var(--outline-variant)",
    textTransform: "uppercase",
    letterSpacing: "-0.02em",
  };
  return <div style={style}>{letter}</div>;
}
