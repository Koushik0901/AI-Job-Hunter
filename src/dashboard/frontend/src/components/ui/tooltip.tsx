import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({
  className,
  sideOffset = 4,
  ...props
}: TooltipPrimitive.TooltipContentProps): JSX.Element {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content className={joinClasses("ui-tooltip-content", className)} sideOffset={sideOffset} {...props} />
    </TooltipPrimitive.Portal>
  );
}

