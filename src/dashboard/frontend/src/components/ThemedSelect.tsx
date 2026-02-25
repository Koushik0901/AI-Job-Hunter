import type { KeyboardEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

interface SelectOption<T extends string> {
  value: T;
  label: string;
}

interface ThemedSelectProps<T extends string> {
  value: T;
  options: Array<SelectOption<T>>;
  onChange: (value: T) => void;
  ariaLabel: string;
  compact?: boolean;
}

export function ThemedSelect<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  compact = false,
}: ThemedSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selectedLabel = useMemo(
    () => options.find((option) => option.value === value)?.label ?? String(value),
    [options, value],
  );

  useEffect(() => {
    if (!open) return;
    const selectedIndex = Math.max(
      0,
      options.findIndex((option) => option.value === value),
    );
    setHighlightedIndex(selectedIndex);
    function onDocumentMouseDown(event: MouseEvent): void {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("mousedown", onDocumentMouseDown);
    return () => window.removeEventListener("mousedown", onDocumentMouseDown);
  }, [open, options, value]);

  useEffect(() => {
    setOpen(false);
  }, [value]);

  function openMenuWithCurrent(): void {
    const selectedIndex = Math.max(
      0,
      options.findIndex((option) => option.value === value),
    );
    setHighlightedIndex(selectedIndex);
    setOpen(true);
  }

  function selectAtIndex(index: number): void {
    if (index < 0 || index >= options.length) return;
    const next = options[index];
    onChange(next.value);
    setOpen(false);
  }

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        openMenuWithCurrent();
      } else {
        setHighlightedIndex((current) => Math.min(current + 1, options.length - 1));
      }
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openMenuWithCurrent();
      } else {
        setHighlightedIndex((current) => Math.max(current - 1, 0));
      }
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) {
        openMenuWithCurrent();
      } else {
        selectAtIndex(highlightedIndex);
      }
      return;
    }
    if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        setOpen(false);
      }
    }
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((current) => Math.min(current + 1, options.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((current) => Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectAtIndex(highlightedIndex);
      return;
    }
    if (event.key === "Escape" || event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div
      className={`themed-select-wrap ${compact ? "compact" : ""}`}
      ref={rootRef}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        className="themed-select-trigger"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((current) => !current);
        }}
        onKeyDown={onTriggerKeyDown}
      >
        <span>{selectedLabel}</span>
        <span className={`themed-select-caret ${open ? "open" : ""}`} aria-hidden="true">▾</span>
      </button>
      {open && (
        <div
          className="themed-select-menu"
          role="listbox"
          aria-label={ariaLabel}
          tabIndex={-1}
          onKeyDown={onMenuKeyDown}
        >
          {options.map((option, index) => (
            <button
              key={option.value}
              type="button"
              className={`themed-select-option ${option.value === value ? "active" : ""} ${index === highlightedIndex ? "highlighted" : ""}`}
              role="option"
              aria-selected={option.value === value}
              onMouseDown={(event) => {
                // Prevent parent label default behavior from re-firing trigger click.
                event.preventDefault();
              }}
              onMouseEnter={() => setHighlightedIndex(index)}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onChange(option.value);
                setOpen(false);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
