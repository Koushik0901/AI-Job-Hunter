import { type ReactNode } from "react";

interface KanbanColumnProps {
  id: string;
  label: string;
  count: number;
  isActiveDrop: boolean;
  onDropJob: (status: string, url: string) => void;
  onReachEnd?: () => void;
  children: ReactNode;
}

export function KanbanColumn({
  id,
  label,
  count,
  isActiveDrop,
  onDropJob,
  onReachEnd,
  children,
}: KanbanColumnProps) {
  const toneClass = `tone-${id.replaceAll("_", "-")}`;
  const countLabel = count === 1 ? "1 role" : `${count} roles`;

  return (
    <section
      className={`kanban-column ${isActiveDrop ? "drop-active" : ""}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const url = event.dataTransfer.getData("text/job-url");
        if (url) {
          onDropJob(id, url);
        }
      }}
    >
      <header className="column-header">
        <div className="column-header-title">
          <span className={`column-tone ${toneClass}`} aria-hidden="true" />
          <div className="column-heading">
            <h3>{label}</h3>
            <p>{countLabel}</p>
          </div>
        </div>
        <span className="column-count">{count}</span>
      </header>
      <div
        className="column-items"
        onScroll={(event) => {
          if (!onReachEnd) {
            return;
          }
          const target = event.currentTarget;
          const remaining = target.scrollHeight - target.scrollTop - target.clientHeight;
          if (remaining < 120) {
            onReachEnd();
          }
        }}
      >
        {children}
      </div>
    </section>
  );
}
