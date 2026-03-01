import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;
export const SelectGroup = SelectPrimitive.Group;
export const SelectLabel = SelectPrimitive.Label;

export function SelectTrigger({
  className,
  children,
  ...props
}: SelectPrimitive.SelectTriggerProps): JSX.Element {
  return (
    <SelectPrimitive.Trigger className={joinClasses("ui-select-trigger", className)} {...props}>
      {children}
      <SelectPrimitive.Icon className="ui-select-caret">▾</SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({
  className,
  children,
  ...props
}: SelectPrimitive.SelectContentProps): JSX.Element {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content className={joinClasses("ui-select-content", className)} {...props}>
        <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

export function SelectItem({
  className,
  children,
  ...props
}: SelectPrimitive.SelectItemProps): JSX.Element {
  return (
    <SelectPrimitive.Item className={joinClasses("ui-select-item", className)} {...props}>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}

