"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function KiteConnectButton() {
  const [testResult, setTestResult] = useState<{
    ok: boolean; user_name?: string; user_id?: string;
    available_cash?: number; error?: string;
  } | null>(null);
  const [testing, setTesting] = useState(false);

  const { data: status, isLoading } = useQuery({
    queryKey: ["kite-status"],
    queryFn: api.getKiteStatus,
    refetchInterval: 30_000,
  });

  const handleConnect = async () => {
    try {
      const { login_url } = await api.getKiteLoginUrl();
      window.location.href = login_url;
    } catch {
      // Kite API not available
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const result = await api.testKiteConnection();
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, error: String(err) });
    }
    setTesting(false);
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#0f1419] text-[#5a6a7f] text-xs font-medium">
        <div className="w-2 h-2 rounded-full bg-[#5a6a7f] animate-pulse" />
        Kite
      </div>
    );
  }

  if (status?.authenticated) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#0f1419] text-xs font-medium">
          <div className="w-2 h-2 rounded-full bg-[#2da44e]" />
          <span className="text-[#2da44e]">Kite Connected</span>
        </div>
        <button
          onClick={handleTest}
          disabled={testing}
          className="px-2 py-1 rounded-md text-xs text-[#5a6a7f] hover:text-[#c9d1d9] hover:bg-[#161d26] transition-colors cursor-pointer disabled:opacity-50"
        >
          {testing ? "Testing..." : "Test"}
        </button>
        {testResult && (
          <div className="flex items-center gap-2 text-xs">
            {testResult.ok ? (
              <>
                <span className="text-[#2da44e]">✓</span>
                <span className="text-[#c9d1d9]">{testResult.user_name}</span>
                <span className="text-[#5a6a7f]">({testResult.user_id})</span>
                <span className="font-mono text-[#d4a015]">
                  ₹{(testResult.available_cash ?? 0).toLocaleString("en-IN")}
                </span>
              </>
            ) : (
              <span className="text-[#f85149]">{testResult.error}</span>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <button
      onClick={handleConnect}
      className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#d4a015]/10 text-[#d4a015] text-xs font-medium hover:bg-[#d4a015]/20 transition-colors cursor-pointer"
    >
      <div className="w-2 h-2 rounded-full bg-[#f85149]" />
      Connect Kite
    </button>
  );
}
