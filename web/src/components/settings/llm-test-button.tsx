"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function LlmTestButton() {
  const [result, setResult] = useState<{ ok: boolean; error?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const handleTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      const res = await api.testLlm();
      setResult(res);
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : "Unknown error" });
    }
    setTesting(false);
  };

  return (
    <div className="flex items-center gap-3">
      <Button size="sm" variant="outline" onClick={handleTest} disabled={testing}>
        {testing ? "Testing..." : "Test Connection"}
      </Button>
      {result && (
        <span className={`text-xs ${result.ok ? "text-[#2da44e]" : "text-[#f85149]"}`}>
          {result.ok ? "Connection OK" : `Failed: ${result.error}`}
        </span>
      )}
    </div>
  );
}
