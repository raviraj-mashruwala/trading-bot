"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

interface Props {
  name: string;
  fields: Record<string, unknown>;
  onSave: (changed: Record<string, unknown>) => Promise<void>;
}

function parseValue(original: unknown, input: string): unknown {
  if (typeof original === "number") {
    const n = Number(input);
    return isNaN(n) ? input : n;
  }
  return input;
}

export function ConfigSection({ name, fields, onSave }: Props) {
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, String(v)]))
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    const changed: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(values)) {
      const parsed = parseValue(fields[key], val);
      if (String(parsed) !== String(fields[key])) {
        changed[key] = parsed;
      }
    }
    if (Object.keys(changed).length === 0) return;
    setSaving(true);
    await onSave(changed);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="rounded-lg border border-border/50 bg-card/80 p-4">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[#d4a015]/80">{name}</div>
      <div className="grid grid-cols-2 gap-3">
        {Object.entries(values).map(([key, val]) => (
          <div key={key}>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted-foreground/60">{key}</label>
            <input
              value={val}
              onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
              className="h-9 w-full rounded-md border border-border/50 bg-muted/30 px-3 text-sm text-foreground/90 outline-none transition-colors focus:border-[#d4a015]/50 focus:ring-1 focus:ring-[#d4a015]/30"
            />
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" onClick={handleSave} disabled={saving} className="bg-[#d4a015]/20 text-[#d4a015] border border-[#d4a015]/30 hover:bg-[#d4a015]/30">
          {saving ? "Saving..." : "Save"}
        </Button>
        {saved && <span className="text-[11px] text-[#2da44e]">Saved</span>}
      </div>
    </div>
  );
}
