"use client";

import { useState, useEffect } from "react";
import { Dialog } from "@/components/ui/dialog";

const SHORTCUTS = [
  { key: "D", label: "Dashboard" },
  { key: "A", label: "Analysis" },
  { key: "E", label: "Execution / Trading" },
  { key: "R", label: "Review" },
  { key: "H", label: "History" },
  { key: "S", label: "Settings" },
  { key: "?", label: "Show this help" },
];

export function KeyboardShortcutsHelp() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = () => setOpen(true);
    document.addEventListener("show-shortcuts", handler);
    return () => document.removeEventListener("show-shortcuts", handler);
  }, []);

  return (
    <Dialog open={open} onClose={() => setOpen(false)}>
      <h3 className="text-sm font-semibold text-[#e6edf3] mb-3">Keyboard Shortcuts</h3>
      <div className="space-y-1.5">
        {SHORTCUTS.map((s) => (
          <div key={s.key} className="flex items-center gap-3">
            <kbd className="flex h-6 w-6 items-center justify-center rounded bg-[#0f1419] border border-[rgba(28,39,54,0.5)] text-xs font-mono text-[#d4a015]">
              {s.key}
            </kbd>
            <span className="text-xs text-[#c9d1d9]">{s.label}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[10px] text-[#5a6a7f]">Shortcuts are disabled when typing in input fields.</p>
    </Dialog>
  );
}
