import type { CSSProperties } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

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
  disabled?: boolean;
}

function accentForValue(value: string): string {
  switch (value) {
    case "all":
    case "kanban":
    case "list":
      return "color-mix(in oklab, #73b8ff 76%, #c7e0ff 24%)";
    case "match_desc":
    case "updated_desc":
      return "color-mix(in oklab, #8e74ff 80%, #cfc6ff 20%)";
    case "stage_priority":
      return "color-mix(in oklab, #6f8cff 80%, #d5dcff 20%)";
    case "posted_desc":
      return "color-mix(in oklab, #4bb7d8 82%, #b5f0ff 18%)";
    case "company_asc":
      return "color-mix(in oklab, #ffb76b 78%, #ffe3ba 22%)";
    case "not_applied":
      return "color-mix(in oklab, #d9a861 78%, #ffe2b7 22%)";
    case "staging":
      return "color-mix(in oklab, #7a8dff 78%, #d0d7ff 22%)";
    case "applied":
      return "color-mix(in oklab, #57a8ee 80%, #d6f0ff 20%)";
    case "interviewing":
      return "color-mix(in oklab, #46c1a7 80%, #cff9eb 20%)";
    case "offer":
      return "color-mix(in oklab, #52c97b 82%, #d6ffe1 18%)";
    case "rejected":
      return "color-mix(in oklab, #e07b98 80%, #ffd7e1 20%)";
    case "low":
      return "color-mix(in oklab, #77c69e 80%, #dbffea 20%)";
    case "medium":
      return "color-mix(in oklab, #f3c15e 78%, #fff0c5 22%)";
    case "high":
      return "color-mix(in oklab, #eb7b73 80%, #ffd9d5 20%)";
    default:
      return "color-mix(in oklab, var(--accent) 76%, white 24%)";
  }
}

export function ThemedSelect<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  compact = false,
  disabled = false,
}: ThemedSelectProps<T>) {
  const accentStyle = {
    "--themed-select-accent": accentForValue(value),
  } as CSSProperties;

  return (
    <div className={`themed-select-wrap ${compact ? "compact" : ""}`} data-value={value} style={accentStyle}>
      <Select value={value} onValueChange={(next) => onChange(next as T)} disabled={disabled}>
        <SelectTrigger aria-label={ariaLabel} className="themed-select-trigger">
          <span className="themed-select-value">
            <SelectValue />
          </span>
        </SelectTrigger>
        <SelectContent className="themed-select-menu" align="start" data-value={value} style={accentStyle}>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value} className="themed-select-option">
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
