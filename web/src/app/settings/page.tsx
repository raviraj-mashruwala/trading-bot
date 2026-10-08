"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ConfigSection } from "@/components/settings/config-section";
import { LlmTestButton } from "@/components/settings/llm-test-button";
import { KiteConnectButton } from "@/components/auth/kite-connect-button";
import { DataSyncSection } from "@/components/settings/data-sync-section";

const MAIN_SECTIONS = ["general", "llm"];
const ADVANCED_SECTIONS = ["strategy", "execution", "screening", "backtest", "risk", "kite", "paper"];

const SECTION_LABELS: Record<string, string> = {
  general: "General",
  llm: "LLM Provider",
  strategy: "Strategy",
  execution: "Execution",
  screening: "Screening Filters",
  backtest: "Backtest",
  risk: "Risk",
  kite: "Kite",
  paper: "Paper Trading",
};

const HIDDEN_FIELDS = new Set(["auto_derived", "capital_source"]);

function filterFields(fields: Record<string, unknown>): Record<string, unknown> {
  const filtered: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fields)) {
    if (!HIDDEN_FIELDS.has(k) && typeof v !== "object") filtered[k] = v;
  }
  return filtered;
}

export default function SettingsPage() {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: api.getConfig });

  if (isLoading || !config) {
    return (
      <div className="flex items-center gap-2 py-12 text-muted-foreground">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#d4a015] border-t-transparent" />
        Loading configuration...
      </div>
    );
  }

  const handleSave = async (section: string, changed: Record<string, unknown>) => {
    await api.putConfig(section, changed);
    queryClient.invalidateQueries({ queryKey: ["config"] });
  };

  const general = config.general as Record<string, unknown> | undefined;
  const capitalSource = general?.capital_source;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>

      {/* Capital banner */}
      {general && (
        <div className="flex items-center gap-3 rounded-lg border border-border/50 bg-card/80 px-4 py-3">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60">Capital</span>
          <span className="font-mono text-lg font-semibold text-foreground/90">
            ₹{Number(general.capital ?? 0).toLocaleString("en-IN")}
          </span>
          <span className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded ${
            capitalSource === "kite" ? "bg-[#2da44e]/10 text-[#2da44e]" : "bg-[#d4a015]/10 text-[#d4a015]"
          }`}>
            {capitalSource === "kite" ? "Live from Kite" : "Config"}
          </span>
        </div>
      )}

      {/* Kite connection */}
      <div className="rounded-lg border border-border/50 bg-card/80 p-4">
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[#d4a015]/80">Broker</div>
        <KiteConnectButton />
      </div>

      {/* Data sync */}
      <DataSyncSection />

      {/* Main sections */}
      {MAIN_SECTIONS.map((section) => {
        const raw = config[section as keyof typeof config] as Record<string, unknown> | undefined;
        if (!raw) return null;
        const fields = filterFields(raw);
        if (Object.keys(fields).length === 0) return null;
        return (
          <div key={section}>
            <ConfigSection
              name={SECTION_LABELS[section] ?? section}
              fields={fields}
              onSave={(changed) => handleSave(section, changed)}
            />
            {section === "llm" && (
              <div className="mt-2 ml-4">
                <LlmTestButton />
              </div>
            )}
          </div>
        );
      })}

      {/* Secrets */}
      {config.secrets && (
        <div className="rounded-lg border border-border/30 bg-card/40 p-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/50">Secrets (read-only)</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[13px]">
            {Object.entries(config.secrets).map(([key, val]) => (
              <div key={key} className="flex justify-between">
                <span className="text-muted-foreground/60">{key}</span>
                <span className="font-mono text-muted-foreground/40">{String(val)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Advanced toggle */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex items-center gap-2 text-xs text-muted-foreground/50 hover:text-muted-foreground/80 transition-colors cursor-pointer"
      >
        <span className={`transition-transform ${showAdvanced ? "rotate-90" : ""}`}>▸</span>
        Advanced Settings
        <span className="text-[10px]">({ADVANCED_SECTIONS.length} sections)</span>
      </button>

      {/* Advanced sections */}
      {showAdvanced && (
        <div className="space-y-4 pl-3 border-l border-border/30">
          {ADVANCED_SECTIONS.map((section) => {
            const raw = config[section as keyof typeof config] as Record<string, unknown> | undefined;
            if (!raw) return null;
            const fields = filterFields(raw);
            if (Object.keys(fields).length === 0) return null;
            return (
              <ConfigSection
                key={section}
                name={SECTION_LABELS[section] ?? section}
                fields={fields}
                onSave={(changed) => handleSave(section, changed)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
