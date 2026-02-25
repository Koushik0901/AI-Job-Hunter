import { useMemo, useState, type CSSProperties, type ReactNode } from "react";

interface SpotlightSurfaceProps {
  children: ReactNode;
  className?: string;
}

export function SpotlightSurface({ children, className }: SpotlightSurfaceProps) {
  const [position, setPosition] = useState({ x: 50, y: 30 });

  const style = useMemo<CSSProperties>(
    () => ({
      background: `radial-gradient(440px circle at ${position.x}% ${position.y}%, var(--spotlight-color), rgba(80, 179, 255, 0) 55%), var(--panel-bg)`,
    }),
    [position],
  );

  return (
    <div
      className={className}
      style={style}
      onMouseMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / rect.width) * 100;
        const y = ((event.clientY - rect.top) / rect.height) * 100;
        setPosition({ x, y });
      }}
    >
      {children}
    </div>
  );
}
