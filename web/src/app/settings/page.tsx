"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ConfigSection } from "@/components/settings/config-section";
import { LlmTestButton } from "@/components/settings/llm-test-button";

const SECTION_ORDER = ["general", "scanner", "strategy", "risk", "execution", "llm", "paper"];

export default function SettingsPage() {
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

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>

      {SECTION_ORDER.map((section) => (
        <div key={section}>
          <ConfigSection
            name={section}
            fields={config[section as keyof typeof config] as Record<string, unknown>}
            onSave={(changed) => handleSave(section, changed)}
          />
          {section === "llm" && (
            <div className="mt-2 ml-4">
              <LlmTestButton />
            </div>
          )}
        </div>
      ))}

      <div className="rounded-lg border border-border/30 bg-card/40 p-4">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/50">Secrets (read-only)</div>
        <div className="grid grid-cols-2 gap-2 text-[13px]">
          {Object.entries(config.secrets).map(([key, val]) => (
            <div key={key} className="flex justify-between">
              <span className="text-muted-foreground/60">{key}</span>
              <span className="font-mono-nums text-muted-foreground/40">{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
