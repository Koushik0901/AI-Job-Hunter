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
}

export function ThemedSelect<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  compact = false,
}: ThemedSelectProps<T>) {
  const selectedLabel = options.find((option) => option.value === value)?.label ?? String(value);

  return (
    <div className={`themed-select-wrap ${compact ? "compact" : ""}`}>
      <Select value={value} onValueChange={(next) => onChange(next as T)}>
        <SelectTrigger aria-label={ariaLabel} className="themed-select-trigger">
          <SelectValue>{selectedLabel}</SelectValue>
        </SelectTrigger>
        <SelectContent className="themed-select-menu">
          {options.map((option) => (
            <SelectItem
              key={option.value}
              value={option.value}
              className={`themed-select-option ${option.value === value ? "active" : ""}`}
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

