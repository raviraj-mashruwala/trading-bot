"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ConfigSection } from "@/components/settings/config-section";
import { LlmTestButton } from "@/components/settings/llm-test-button";

const SECTION_ORDER = ["general", "scanner", "strategy", "risk", "execution", "llm", "paper"];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: api.getConfig });

  if (isLoading || !config) return <div>Loading config...</div>;

  const handleSave = async (section: string, changed: Record<string, unknown>) => {
    await api.putConfig(section, changed);
    queryClient.invalidateQueries({ queryKey: ["config"] });
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

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

      <div className="space-y-2 rounded border p-4 opacity-60">
        <h3 className="text-sm font-semibold">Secrets (read-only)</h3>
        <div className="grid grid-cols-2 gap-2 text-sm text-muted-foreground">
          {Object.entries(config.secrets).map(([key, val]) => (
            <div key={key}><span className="font-mono">{key}:</span> {val}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
