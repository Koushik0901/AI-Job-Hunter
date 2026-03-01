import * as React from "react";
import * as AccordionPrimitive from "@radix-ui/react-accordion";

type DivProps = React.HTMLAttributes<HTMLDivElement>;
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement>;

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const Accordion = AccordionPrimitive.Root;

export function AccordionItem({
  className,
  ...props
}: AccordionPrimitive.AccordionItemProps): JSX.Element {
  return <AccordionPrimitive.Item className={joinClasses("ui-accordion-item", className)} {...props} />;
}

export function AccordionTrigger({
  className,
  children,
  ...props
}: AccordionPrimitive.AccordionTriggerProps & ButtonProps): JSX.Element {
  return (
    <AccordionPrimitive.Header className="ui-accordion-header">
      <AccordionPrimitive.Trigger className={joinClasses("ui-accordion-trigger", className)} {...props}>
        {children}
        <svg
          className="ui-accordion-trigger-icon"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  );
}

export function AccordionContent({
  className,
  children,
  ...props
}: AccordionPrimitive.AccordionContentProps & DivProps): JSX.Element {
  return (
    <AccordionPrimitive.Content className={joinClasses("ui-accordion-content", className)} {...props}>
      <div className="ui-accordion-content-inner">{children}</div>
    </AccordionPrimitive.Content>
  );
}
