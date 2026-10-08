/**
 * Static plain-English explanations for every decision the executor emits.
 * Zero LLM cost — deterministic mapping from reason codes to educational text.
 */

interface Explanation {
  short: string;
  detail: string;
}

const ENTRY_EXPLANATIONS: Record<string, Explanation> = {
  // EntryGuard reasons
  "Entry window expired": {
    short: "Too late to enter",
    detail: "The planned entry window has closed. Setups lose edge as the day progresses — entering late means less time for the move to play out and higher risk of getting caught in end-of-day noise.",
  },
  "Max entry wait expired": {
    short: "Waited too long",
    detail: "The maximum wait time for this setup has passed. If conditions haven't aligned by now, the original thesis may no longer be valid. Better to skip than force a late entry.",
  },
  "Volume too low, no liquidity": {
    short: "Not enough volume",
    detail: "Current volume is below 30% of normal. Low volume means wide spreads, poor fills, and risk of getting stuck in a position. Wait for volume to pick up before entering.",
  },
  "Choppy, conflicting signals": {
    short: "Mixed signals",
    detail: "Price action is choppy with no clear trend. The 1-minute and 5-minute timeframes disagree, and candle bodies are small relative to wicks. Entering here is a coin flip.",
  },
  "Price falling below VWAP": {
    short: "Below VWAP for longs",
    detail: "Price is dropping below VWAP with negative short-term momentum. For a long trade, this means institutions are selling. Wait for price to reclaim VWAP before entering.",
  },
  "Price rising above VWAP": {
    short: "Above VWAP for shorts",
    detail: "Price is climbing above VWAP with positive short-term momentum. For a short trade, this means buying pressure is too strong. Wait for price to drop below VWAP.",
  },
  "Momentum aligned, volume adequate": {
    short: "Strong entry signal",
    detail: "Both 1-minute and 5-minute momentum agree with the trade direction, volume is adequate (>70% of normal), and the trend is aligned. This is the highest-confidence entry condition.",
  },
  "No disqualifying signal, marginal conditions": {
    short: "Marginal — nothing strong",
    detail: "Nothing is actively wrong, but nothing is strongly confirming either. This is a gray zone entry — the bot enters but with lower confidence. If AI escalation is available, it will be consulted.",
  },
  "No candle data yet": {
    short: "Waiting for market data",
    detail: "The market just opened and no 1-minute candle has closed yet. The bot needs at least one candle to assess momentum and volume. This typically resolves within 1-2 minutes of market open.",
  },
  "Ticker degraded": {
    short: "Data feed issue",
    detail: "The live data feed is degraded or reconnecting. The bot blocks new entries when data quality is uncertain to avoid entering on stale prices. Entries resume when the feed recovers.",
  },
  "Wait timeout — conditions never cleared": {
    short: "Conditions never aligned",
    detail: "The bot waited until the maximum allowed time but entry conditions never became favorable. The setup is cancelled. This often means the stock moved differently than the overnight analysis predicted.",
  },
  "LLM escalation failed": {
    short: "AI check failed",
    detail: "The entry was in a gray zone (low confidence) and the AI safety check failed to respond in time. The bot blocks the entry for safety — better to miss a marginal trade than enter blind.",
  },
};

const EXIT_EXPLANATIONS: Record<string, Explanation> = {
  BOOK_TARGET_1: {
    short: "First target hit — taking partial profit",
    detail: "Price reached Target 1. The bot books 50% of the position to lock in gains, then trails the stop to breakeven on the remainder. This guarantees a profit on the trade while keeping upside open.",
  },
  BOOK_TARGET_2: {
    short: "Second target hit — closing position",
    detail: "Price reached Target 2, the full profit target. The entire remaining position is closed. This is the best-case outcome for a trade.",
  },
  STOP_HIT: {
    short: "Stop loss triggered",
    detail: "Price hit the stop loss level. The position is closed to limit the loss. Stops are non-negotiable — they protect capital. A single trade should never risk more than 1-2% of total capital.",
  },
  SQUARE_OFF: {
    short: "End-of-day closure",
    detail: "It's 3:10 PM — 10 minutes before Zerodha's automatic MIS square-off at 3:20 PM. The bot closes all remaining positions to avoid the broker's forced exit, which can get worse fills.",
  },
  MOMENTUM_EXIT: {
    short: "Momentum reversed",
    detail: "The 5-minute momentum shifted strongly against the trade direction. Even though the stop hasn't been hit, the conditions that justified the trade no longer exist. Early exit preserves more capital than waiting for the stop.",
  },
  PATTERN_EXIT: {
    short: "Adverse candle pattern",
    detail: "A strong reversal candle pattern appeared on the 5-minute chart (e.g., bearish engulfing for longs, bullish engulfing for shorts). These patterns often precede sharp moves against the position.",
  },
  TRAIL_STOP: {
    short: "Stop tightened",
    detail: "The trailing stop has been moved to lock in more profit as price moves favorably. The bot uses ATR-based trailing that adapts to volatility — tighter in calm markets, wider in volatile ones.",
  },
  KILL_SWITCH: {
    short: "Daily loss limit hit",
    detail: "Total losses for the day exceeded the maximum allowed daily loss. All positions are closed and no new trades will be placed today. This hard limit prevents catastrophic drawdowns.",
  },
};

const DRIFT_PATTERN = /^Price drift ([\d.]+)%/;
const STRONG_SELLING_PATTERN = /^Strong 5m selling/;
const STRONG_BUYING_PATTERN = /^Strong 5m buying/;
const BEARISH_PATTERN = /^Bearish 5m pattern: (.+)$/;
const BULLISH_PATTERN = /^Bullish 5m pattern: (.+)$/;
const STALE_DATA_PATTERN = /^Stale data/;
const LLM_PREFIX = /^LLM/;

export function getExplanation(decisionType: string, reason: string | null): Explanation | null {
  if (!reason) return null;

  // Exit decisions — keyed by type
  if (EXIT_EXPLANATIONS[decisionType]) {
    return EXIT_EXPLANATIONS[decisionType];
  }

  // Entry decisions — exact match first
  if (ENTRY_EXPLANATIONS[reason]) {
    return ENTRY_EXPLANATIONS[reason];
  }

  // Pattern matching for dynamic reasons
  if (DRIFT_PATTERN.test(reason)) {
    const pct = reason.match(DRIFT_PATTERN)?.[1] ?? "?";
    return {
      short: "Price moved too far",
      detail: `Current price drifted ${pct}% from the planned entry. When price moves significantly from the analysis level, the risk/reward changes. The stop and target distances were calculated for the original entry price.`,
    };
  }

  if (STRONG_SELLING_PATTERN.test(reason)) {
    return {
      short: "Sellers in control",
      detail: "5-minute momentum is extremely negative (below -60). Entering a long trade into this selling pressure is fighting the tape. The bot vetoes the entry to avoid catching a falling knife.",
    };
  }

  if (STRONG_BUYING_PATTERN.test(reason)) {
    return {
      short: "Buyers in control",
      detail: "5-minute momentum is extremely positive (above +60). Entering a short trade into this buying pressure means fighting strong demand. The bot vetoes to avoid shorting into strength.",
    };
  }

  if (BEARISH_PATTERN.test(reason)) {
    const pattern = reason.match(BEARISH_PATTERN)?.[1] ?? "unknown";
    return {
      short: `Bearish pattern: ${pattern}`,
      detail: `A ${pattern.replace(/_/g, " ")} appeared on the 5-minute chart. This is a reversal signal suggesting sellers are gaining control. The bot waits for the pattern to resolve before entering a long.`,
    };
  }

  if (BULLISH_PATTERN.test(reason)) {
    const pattern = reason.match(BULLISH_PATTERN)?.[1] ?? "unknown";
    return {
      short: `Bullish pattern: ${pattern}`,
      detail: `A ${pattern.replace(/_/g, " ")} appeared on the 5-minute chart. This is a reversal signal suggesting buyers are gaining control. The bot waits for the pattern to resolve before entering a short.`,
    };
  }

  if (STALE_DATA_PATTERN.test(reason)) {
    return {
      short: "Data feed delayed",
      detail: "The last market data update is over 2 minutes old. This could mean a ticker disconnect or exchange issue. The bot pauses entries until fresh data arrives to avoid acting on stale prices.",
    };
  }

  if (reason.startsWith("Price proximity entry")) {
    return {
      short: "Quick entry — price at target",
      detail: "Price is within 1% of the planned entry and no candle data exists yet (market just opened). The bot enters immediately to avoid missing a fast opening move. This bypasses the usual candle-based checks.",
    };
  }

  if (LLM_PREFIX.test(reason)) {
    return {
      short: "AI reviewed this trade",
      detail: "The entry was in a gray zone (confidence below 40%), so the bot consulted Claude for a second opinion. The AI evaluated momentum, volume, price action, and the broader market context before making a call.",
    };
  }

  return null;
}
