"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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
    <div className="space-y-4 rounded border p-4">
      <h3 className="text-sm font-semibold capitalize">{name}</h3>
      <div className="grid grid-cols-2 gap-3">
        {Object.entries(values).map(([key, val]) => (
          <div key={key}>
            <Label className="text-xs text-muted-foreground">{key}</Label>
            <Input
              value={val}
              onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
              className="mt-1"
            />
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
        {saved && <span className="text-xs text-green-600">Saved</span>}
      </div>
    </div>
  );
}
