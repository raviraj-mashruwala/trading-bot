"use client";

import { useQuery } from "@tanstack/react-query";
import { ruleApi, type RuleTrade } from "@/lib/rule-api";
import { RuleControls } from "@/components/rules/rule-controls";
import { cn } from "@/lib/utils";

const PHASE_LABEL: Record<string, string> = {
  waiting_signal: "Waiting for 09:16 signal",
  waiting_entry: "Signal fired, entering at 09:20",
  entry_pending: "Entry order working",
  in_position: "Short open",
  exiting: "Buying back",
  done: "Done for today",
  error: "Needs attention",
};

function inr(n: number | null | undefined, sign = false) {
  if (n == null) return "—";
  const s = `₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  if (!sign) return n < 0 ? `-${s}` : s;
  return n >= 0 ? `+${s}` : `-${s}`;
}

function num(n: number | null | undefined, d = 2) {
  return n == null ? "—" : n.toFixed(d);
}

function pnlClass(n: number | null | undefined) {
  if (n == null) return "text-[#e6edf3]";
  return n >= 0 ? "text-[#2da44e]" : "text-[#f85149]";
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">{label}</p>
      <p className={cn("font-mono-nums text-base font-semibold text-[#e6edf3]", tone)}>{value}</p>
    </div>
  );
}

function Totals({ trades }: { trades: RuleTrade[] }) {
  const rows = (["paper", "live"] as const).map((mode) => {
    const closed = trades.filter((t) => t.mode === mode && t.status === "closed");
    const net = closed.reduce((s, t) => s + (t.net_pnl ?? 0), 0);
    const wins = closed.filter((t) => (t.net_pnl ?? 0) > 0).length;
    return { mode, n: closed.length, net, wins };
  });
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {rows.map((r) => (
        <div key={r.mode} className="contents">
          <Stat label={`${r.mode} trades`} value={`${r.n}${r.n ? ` · ${r.wins} won` : ""}`} />
          <Stat label={`${r.mode} net P&L`} value={r.n ? inr(r.net, true) : "—"} tone={r.n ? pnlClass(r.net) : undefined} />
        </div>
      ))}
    </div>
  );
}

export default function RulesPage() {
  const { data: status } = useQuery({ queryKey: ["rule-status"], queryFn: ruleApi.status, refetchInterval: 3000 });
  const preview = useQuery({ queryKey: ["rule-preview"], queryFn: ruleApi.preview, refetchInterval: 60_000, retry: false });
  const today = status?.session?.trade_date;
  const { data: events = [] } = useQuery({
    queryKey: ["rule-events", today],
    queryFn: () => ruleApi.events(today),
    refetchInterval: 5000,
  });
  const { data: trades = [] } = useQuery({ queryKey: ["rule-trades"], queryFn: ruleApi.trades, refetchInterval: 15_000 });

  const session = status?.session;
  const position = session?.position;
  const running = status?.running ?? false;
  const heroValue = session?.result?.net_pnl ?? position?.unrealised_pnl ?? null;
  const heroLabel = session?.result ? "Today's net P&L" : position ? "Unrealised P&L" : "KEC intraday short";
  const p = preview.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-xs text-muted-foreground">{heroLabel}</p>
          <p className={cn("hero-number text-4xl", heroValue == null ? "text-[#e6edf3]" : pnlClass(heroValue))}>
            {heroValue == null ? (session ? PHASE_LABEL[session.phase] ?? session.phase : "Not running") : inr(heroValue, true)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("h-1.5 w-1.5 rounded-full", running ? "animate-pulse bg-[#2da44e]" : "bg-muted-foreground/30")} />
          <span className="text-xs text-muted-foreground">
            {running ? `Running · ${session?.mode}` : "Stopped"}
          </span>
          {session?.mode === "live" && running && (
            <span className="rounded-sm bg-[#f85149]/15 px-1.5 py-0.5 text-[11px] font-medium text-[#f85149]">LIVE</span>
          )}
        </div>
      </div>

      <RuleControls status={status} />
      {status?.error && <p className="text-xs text-[#f85149]">Executor error: {status.error}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-[rgba(28,39,54,0.5)] bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold text-[#e6edf3]">Today&apos;s conditions</h2>
          {preview.isError && (
            <p className="text-xs text-muted-foreground">{(preview.error as Error).message}</p>
          )}
          {p && (
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Previous close" value={num(p.previous_close)} />
              <Stat
                label="Close position in range"
                value={`${(p.previous_close_pos * 100).toFixed(0)}%`}
                tone={p.weak_close_met ? "text-[#d4a015]" : undefined}
              />
              <Stat label="Gap trigger (open at or above)" value={num(p.gap_trigger_price)} />
              <Stat label="Today's open" value={num(p.today_open)} />
              <Stat label="Stop distance (ADR 14)" value={`${p.adr_pct.toFixed(2)}%`} />
              <Stat
                label="Signal"
                value={p.signal ? (p.signal.trade ? "Short" : "No trade") : p.weak_close_met ? "Short (weak close)" : "Decided at 09:16"}
                tone={p.signal?.trade || (!p.signal && p.weak_close_met) ? "text-[#d4a015]" : undefined}
              />
            </div>
          )}
          {p?.signal?.reasons?.length ? (
            <p className="mt-3 text-xs text-muted-foreground">{p.signal.reasons.join(" · ")}</p>
          ) : null}
        </section>

        <section className="rounded-lg border border-[rgba(28,39,54,0.5)] bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold text-[#e6edf3]">Position</h2>
          {position ? (
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Short quantity" value={String(position.quantity)} />
              <Stat label="Entry" value={num(position.entry_price)} />
              <Stat label="Stop" value={num(position.stop)} />
              <Stat label="Last price" value={num(position.last_price)} />
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              {session?.note || "No position. The rule shorts KEC at 09:20 only when a condition is met."}
            </p>
          )}
          {session?.result && (
            <p className="mt-3 text-xs text-muted-foreground">
              Gross {inr(session.result.gross_pnl, true)} · est. charges {inr(session.result.est_charges)}
            </p>
          )}
        </section>
      </div>

      <section className="rounded-lg border border-[rgba(28,39,54,0.5)] bg-card p-4">
        <h2 className="mb-3 text-sm font-semibold text-[#e6edf3]">Today&apos;s log</h2>
        {events.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nothing yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {events.map((e) => (
              <li key={e.id} className="flex gap-3 text-xs">
                <span className="font-mono-nums text-muted-foreground">{e.timestamp.slice(11, 19)}</span>
                <span className="w-28 shrink-0 font-mono-nums text-[#d4a015]/80">{e.kind}</span>
                <span className="text-[#b8c0c8]">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-4 rounded-lg border border-[rgba(28,39,54,0.5)] bg-card p-4">
        <h2 className="text-sm font-semibold text-[#e6edf3]">History</h2>
        <Totals trades={trades} />
        {trades.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[11px] text-muted-foreground">
                  {["Date", "Mode", "Qty", "Entry", "Exit", "Reason", "Charges", "Net P&L"].map((h) => (
                    <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono-nums">
                {trades.map((t) => (
                  <tr key={t.id} className="border-t border-border/50">
                    <td className="py-2 pr-4">{t.trade_date}</td>
                    <td className={cn("py-2 pr-4", t.mode === "live" && "text-[#f85149]")}>{t.mode}</td>
                    <td className="py-2 pr-4">{t.quantity}</td>
                    <td className="py-2 pr-4">{num(t.entry_price)}</td>
                    <td className="py-2 pr-4">{num(t.exit_price)}</td>
                    <td className="py-2 pr-4">{t.exit_reason ?? t.status}</td>
                    <td className="py-2 pr-4">{inr(t.est_charges)}</td>
                    <td className={cn("py-2 pr-4", pnlClass(t.net_pnl))}>{inr(t.net_pnl, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Rule: short KEC at 09:20 if it opens 1%+ above the previous close, or the previous day closed in the
        bottom 20% of its range. Stop 1× the 14-day average range above entry. Buy back at 15:15. One trade a day.
        Backtest 2019–Nov 2026 was positive but not statistically reliable outside its training years.
      </p>
    </div>
  );
}
