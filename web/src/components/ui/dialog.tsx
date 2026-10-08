"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

export function Dialog({ open, onClose, children }: DialogProps) {
  const ref = React.useRef<HTMLDialogElement>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handler = () => onClose();
    el.addEventListener("close", handler);
    return () => el.removeEventListener("close", handler);
  }, [onClose]);

  return (
    <dialog
      ref={ref}
      className="backdrop:bg-black/60 bg-transparent p-0 m-0 max-w-lg w-full open:flex open:items-center open:justify-center fixed inset-0"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-[#161d26] border border-[rgba(28,39,54,0.5)] rounded-lg p-6 w-full max-w-md mx-4 shadow-none">
        {children}
      </div>
    </dialog>
  );
}

interface AlertDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "destructive" | "default";
  loading?: boolean;
}

export function AlertDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  loading = false,
}: AlertDialogProps) {
  return (
    <Dialog open={open} onClose={onClose}>
      <h3 className="text-sm font-semibold text-[#e6edf3] mb-2">{title}</h3>
      <p className="text-xs text-[#c9d1d9] leading-relaxed mb-4">{description}</p>
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={loading}>
          {cancelLabel}
        </Button>
        <Button
          variant={variant === "destructive" ? "destructive" : "default"}
          size="sm"
          onClick={onConfirm}
          disabled={loading}
          className={cn(
            variant === "destructive" && "bg-[#f85149] text-white hover:bg-[#f85149]/90",
          )}
        >
          {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />}
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}