"use client";

import { useEffect, useRef, type ReactNode } from "react";

export function Modal({ open, busy = false, onClose, labelledBy, testId, children }: {
  open: boolean;
  busy?: boolean;
  onClose: () => void;
  labelledBy: string;
  testId: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, [open]);

  if (!open) return null;
  return (
    <dialog
      ref={ref}
      className="modal-shell w-full h-full max-w-none max-h-none m-0 border-0 text-text-primary"
      aria-labelledby={labelledBy}
      data-testid={testId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div className="modal-card">{children}</div>
    </dialog>
  );
}
