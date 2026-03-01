import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const Tabs = TabsPrimitive.Root;

export function TabsList({
  className,
  ...props
}: TabsPrimitive.TabsListProps): JSX.Element {
  return <TabsPrimitive.List className={joinClasses("ui-tabs-list", className)} {...props} />;
}

export function TabsTrigger({
  className,
  ...props
}: TabsPrimitive.TabsTriggerProps): JSX.Element {
  return <TabsPrimitive.Trigger className={joinClasses("ui-tabs-trigger", className)} {...props} />;
}

export function TabsContent({
  className,
  ...props
}: TabsPrimitive.TabsContentProps): JSX.Element {
  return <TabsPrimitive.Content className={joinClasses("ui-tabs-content", className)} {...props} />;
}

