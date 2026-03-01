import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>): JSX.Element {
  const safeValue = Number.isFinite(value) ? Math.max(0, Math.min(100, Number(value))) : 0;
  return (
    <ProgressPrimitive.Root className={joinClasses("ui-progress", className)} value={safeValue} {...props}>
      <ProgressPrimitive.Indicator className="ui-progress-indicator" style={{ transform: `translateX(-${100 - safeValue}%)` }} />
    </ProgressPrimitive.Root>
  );
}

