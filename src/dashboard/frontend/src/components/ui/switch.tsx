import * as React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Switch({
  className,
  ...props
}: SwitchPrimitive.SwitchProps): JSX.Element {
  return (
    <SwitchPrimitive.Root className={joinClasses("ui-switch", className)} {...props}>
      <SwitchPrimitive.Thumb className="ui-switch-thumb" />
    </SwitchPrimitive.Root>
  );
}

