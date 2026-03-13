import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  ...props
}: DialogPrimitive.DialogContentProps): JSX.Element {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="ui-dialog-overlay" />
      <DialogPrimitive.Content className={joinClasses("ui-dialog-content", className)} {...props}>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={joinClasses("ui-dialog-header", className)} {...props} />;
}

export function DialogTitle({
  className,
  ...props
}: DialogPrimitive.DialogTitleProps): JSX.Element {
  return <DialogPrimitive.Title className={joinClasses("ui-dialog-title", className)} {...props} />;
}

export function DialogDescription({
  className,
  ...props
}: DialogPrimitive.DialogDescriptionProps): JSX.Element {
  return <DialogPrimitive.Description className={joinClasses("ui-dialog-description", className)} {...props} />;
}

export function DialogFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={joinClasses("ui-dialog-footer", className)} {...props} />;
}
