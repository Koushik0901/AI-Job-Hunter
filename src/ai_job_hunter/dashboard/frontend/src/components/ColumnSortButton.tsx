import { useState, useRef } from "react";
import { MoreHorizontal } from "lucide-react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import type { ColumnSortOption } from "../types";

interface ColumnSortButtonProps {
  value: ColumnSortOption;
  options: Array<{ value: ColumnSortOption; label: string }>;
  onChange: (value: ColumnSortOption) => void;
  columnLabel: string;
}

export function ColumnSortButton({
  value,
  options,
  onChange,
  columnLabel,
}: ColumnSortButtonProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const currentLabel = options.find((opt) => opt.value === value)?.label || value;

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          ref={triggerRef}
          type="button"
          className="column-sort-button"
          title={`Sort ${columnLabel} by ${currentLabel}`}
          aria-label={`Sort ${columnLabel}`}
          aria-expanded={open}
        >
          <MoreHorizontal size={16} strokeWidth={2.2} />
        </button>
      </PopoverPrimitive.Trigger>

      <PopoverPrimitive.Content
        className="column-sort-popover"
        align="start"
        side="bottom"
        sideOffset={4}
      >
        <div className="column-sort-menu">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`column-sort-option ${option.value === value ? "active" : ""}`}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
              title={option.label}
            >
              <span className="column-sort-option-label">{option.label}</span>
              {option.value === value && (
                <span className="column-sort-option-check" aria-hidden="true">
                  ✓
                </span>
              )}
            </button>
          ))}
        </div>
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Root>
  );
}
