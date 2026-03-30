import * as React from "react";
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
export const AlertDialogPortal = AlertDialogPrimitive.Portal;
export const AlertDialogAction = AlertDialogPrimitive.Action;
export const AlertDialogCancel = AlertDialogPrimitive.Cancel;

export const AlertDialogOverlay = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Overlay>,
  AlertDialogPrimitive.AlertDialogOverlayProps
>(function AlertDialogOverlay({ className, ...props }, ref): JSX.Element {
  return <AlertDialogPrimitive.Overlay ref={ref} className={joinClasses("ui-alert-dialog-overlay", className)} {...props} />;
});

export const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  AlertDialogPrimitive.AlertDialogContentProps
>(function AlertDialogContent({ className, ...props }, ref): JSX.Element {
  return (
    <AlertDialogPortal>
      <AlertDialogOverlay />
      <AlertDialogPrimitive.Content ref={ref} className={joinClasses("ui-alert-dialog-content", className)} {...props} />
    </AlertDialogPortal>
  );
});

export function AlertDialogHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={joinClasses("ui-alert-dialog-header", className)} {...props} />;
}

export function AlertDialogFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={joinClasses("ui-alert-dialog-footer", className)} {...props} />;
}

export function AlertDialogTitle({
  className,
  ...props
}: AlertDialogPrimitive.AlertDialogTitleProps): JSX.Element {
  return <AlertDialogPrimitive.Title className={joinClasses("ui-alert-dialog-title", className)} {...props} />;
}

export function AlertDialogDescription({
  className,
  ...props
}: AlertDialogPrimitive.AlertDialogDescriptionProps): JSX.Element {
  return <AlertDialogPrimitive.Description className={joinClasses("ui-alert-dialog-description", className)} {...props} />;
}
