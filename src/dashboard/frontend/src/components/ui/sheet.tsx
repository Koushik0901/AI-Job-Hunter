import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

export function SheetPortal({ ...props }: DialogPrimitive.DialogPortalProps): JSX.Element {
  return <DialogPrimitive.Portal {...props} />;
}

export function SheetOverlay({
  className,
  ...props
}: DialogPrimitive.DialogOverlayProps): JSX.Element {
  return <DialogPrimitive.Overlay className={joinClasses("ui-sheet-overlay", className)} {...props} />;
}

interface SheetContentProps extends DialogPrimitive.DialogContentProps {
  side?: "left" | "right";
}

export function SheetContent({
  className,
  children,
  side = "right",
  ...props
}: SheetContentProps): JSX.Element {
  return (
    <SheetPortal>
      <SheetOverlay />
      <DialogPrimitive.Content
        className={joinClasses("ui-sheet-content", side === "left" ? "ui-sheet-left" : "ui-sheet-right", className)}
        {...props}
      >
        {children}
      </DialogPrimitive.Content>
    </SheetPortal>
  );
}

export function SheetHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={joinClasses("ui-sheet-header", className)} {...props} />;
}

export function SheetTitle({
  className,
  ...props
}: DialogPrimitive.DialogTitleProps): JSX.Element {
  return <DialogPrimitive.Title className={joinClasses("ui-sheet-title", className)} {...props} />;
}

