"""Exploratory entry comparison on saved plans through 2026-10-30.

Frozen rules, before inspecting results:
* fixed_limit: original limit, stop and T1; active from the plan start.
* confirmed_fixed: first completed 5-minute directional candle closing beyond
  the planned entry and on the directional side of session VWAP. Fill at the
  next minute's open, retaining the original stop and target.
* opening_range: first completed 5-minute candle closing outside the initial
  09:15-09:20 range, in the plan direction and beyond session VWAP. Fill at the
  next minute's open. Stop at the opposite range edge, with a 0.5% minimum
  distance; target uses the original plan's reward/risk multiple.

Both confirmation methods stop looking at 10:30. No retries or re-entry after
the first signal. All variants cap quantity by original planned rupee risk and
original notional exposure. Stops/targets are checked using minute high/low;
gaps use the open. Ambiguous bars are excluded and counted, not called winners.
This is a per-leg counterfactual, not a portfolio simulation or holdout test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path

import duckdb

VARIANTS = ('fixed_limit', 'confirmed_fixed', 'opening_range')
AS_OF = '2026-10-30'
COST_SOURCE = 'https://zerodha.com/charges/'


def costs(entry, exit_price, quantity, long, slippage_bps):
    buy, sell = (entry, exit_price) if long else (exit_price, entry)
    bv, sv = buy * quantity, sell * quantity
    turnover = bv + sv
    brokerage = min(20, bv * .0003) + min(20, sv * .0003)
    exchange, sebi = turnover * .0000307, turnover * .000001
    gst = .18 * (brokerage + exchange + sebi)
    return (brokerage + exchange + sebi + gst + sv * .00025
            + bv * .00003 + turnover * .000000001 * 1.18
            + turnover * slippage_bps / 10000)


def load_inputs(database, plans_dir, supplement, cache):
    plans = [json.loads(p.read_text()) for p in sorted(plans_dir.glob('????-??-??.json'))
             if p.stem <= AS_OF]
    supplemental = json.loads(supplement.read_text()) if supplement.exists() else {}
    if cache.exists():
        raw = json.loads(cache.read_text())
    else:
        raw = {}
        con = duckdb.connect(str(database), read_only=True)
        for plan in plans:
            for leg in plan['legs']:
                key = plan['trade_date'] + '|' + leg['symbol']
                cursor = con.execute(
                    "SELECT timestamp,open,high,low,close,volume FROM candles "
                    "WHERE symbol=? AND interval='1m' AND timestamp::DATE=? ORDER BY timestamp",
                    [leg['symbol'], plan['trade_date']],
                )
                names = [x[0] for x in cursor.description]
                raw[key] = [dict(zip(names, row)) for row in cursor.fetchall()]
                if not raw[key] and key in supplemental:
                    raw[key] = [{'timestamp': row['date'], **{k: row[k] for k in
                                 ('open', 'high', 'low', 'close', 'volume')}}
                                for row in supplemental[key]]
        con.close()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw, default=str))
    parsed = {key: [{**row, 'timestamp': datetime.fromisoformat(str(row['timestamp']))
                    .replace(tzinfo=None)} for row in rows] for key, rows in raw.items()}
    return plans, parsed


def confirmation(candles, leg, variant):
    long = leg['direction'] == 'long'
    initial = [c for c in candles if time(9, 15) <= c['timestamp'].time() < time(9, 20)]
    if len(initial) != 5:
        return None
    range_high, range_low = max(c['high'] for c in initial), min(c['low'] for c in initial)
    pv = volume = 0.0
    bucket = []
    start = time.fromisoformat(leg['entry_window_start'])
    end = min(time(10, 30), time.fromisoformat(leg['entry_window_end']),
              time.fromisoformat(leg['max_entry_wait']))
    for i, candle in enumerate(candles):
        clock = candle['timestamp'].time()
        if clock < time(9, 15):
            continue
        pv += (candle['high'] + candle['low'] + candle['close']) / 3 * candle['volume']
        volume += candle['volume']
        bucket.append(candle)
        elapsed = (candle['timestamp'].hour * 60 + candle['timestamp'].minute) - 555
        if elapsed % 5 != 4:
            continue
        bar, bucket = bucket, []
        if len(bar) != 5 or i + 1 >= len(candles):
            continue
        nxt = candles[i + 1]
        fill_clock = nxt['timestamp'].time()
        if fill_clock < start:
            continue
        if fill_clock > end:
            break
        close, opening = bar[-1]['close'], bar[0]['open']
        if volume <= 0:
            continue
        directional = close > opening and close > pv / volume if long else close < opening and close < pv / volume
        level = leg['entry_price'] if variant == 'confirmed_fixed' else (range_high if long else range_low)
        beyond = close > level if long else close < level
        if directional and beyond:
            fill = nxt['open']
            if variant == 'confirmed_fixed':
                stop, target = leg['stop_loss'], leg['target_1']
            else:
                distance = max(fill - range_low if long else range_high - fill, fill * .005)
                stop = fill - distance if long else fill + distance
                rr = abs(leg['target_1'] - leg['entry_price']) / abs(leg['entry_price'] - leg['stop_loss'])
                target = fill + distance * rr * (1 if long else -1)
            return i + 1, fill, stop, target, True
    return None


def simulate(leg, candles, variant, slippage_bps):
    result = dict(status='NO_SIGNAL', entry_at='', exit_at='', fill='', stop='',
                  target='', quantity=0, gross='', cost='', net='', risk_used='', net_r='')
    if not candles:
        return {**result, 'status': 'NO_DATA'}
    square_off = time.fromisoformat(leg['exit_before'])
    session = [c for c in candles if time(9, 15) <= c['timestamp'].time() <= square_off]
    if not session or session[0]['timestamp'].time() != time(9, 15) or session[-1]['timestamp'].time() != square_off:
        return {**result, 'status': 'INCOMPLETE_DATA'}
    if any(b['timestamp'] - a['timestamp'] != timedelta(minutes=1) for a, b in zip(session, session[1:])):
        return {**result, 'status': 'GAPPED_DATA'}
    long = leg['direction'] == 'long'
    if variant == 'fixed_limit':
        candidate = None
        start = time.fromisoformat(leg['entry_window_start'])
        end = min(time.fromisoformat(leg['entry_window_end']), time.fromisoformat(leg['max_entry_wait']))
        for i, c in enumerate(session):
            if not start <= c['timestamp'].time() <= end:
                continue
            touched = c['low'] <= leg['entry_price'] if long else c['high'] >= leg['entry_price']
            if touched:
                at_open = c['open'] <= leg['entry_price'] if long else c['open'] >= leg['entry_price']
                candidate = (i, c['open'] if at_open else leg['entry_price'], leg['stop_loss'], leg['target_1'], at_open)
                break
    else:
        candidate = confirmation(session, leg, variant)
    if candidate is None:
        return result
    index, fill, stop, target, at_open = candidate
    result.update(fill=fill, stop=stop, target=target, entry_at=session[index]['timestamp'].isoformat())
    if not (stop < fill < target if long else target < fill < stop):
        return {**result, 'status': 'INVALID_LEVELS'}
    distance = abs(fill - stop)
    budget = abs(leg['entry_price'] - leg['stop_loss']) * leg['quantity']
    quantity = min(math.floor((budget + 1e-8) / distance),
                   math.floor((leg['entry_price'] * leg['quantity'] + 1e-8) / fill))
    if quantity <= 0:
        return {**result, 'status': 'ZERO_SIZE'}
    result.update(quantity=quantity, risk_used=round(distance * quantity, 6))
    for j in range(index, len(session)):
        candle = session[j]
        if candle['timestamp'].time() >= square_off:
            exit_price, status = candle['open'], 'SQUARE_OFF'
        else:
            hit_stop = candle['low'] <= stop if long else candle['high'] >= stop
            hit_target = candle['high'] >= target if long else candle['low'] <= target
            if j == index and not at_open and hit_target:
                return {**result, 'status': 'AMBIGUOUS_ENTRY_BAR'}
            open_stop = candle['open'] <= stop if long else candle['open'] >= stop
            open_target = candle['open'] >= target if long else candle['open'] <= target
            if (j != index or at_open) and open_stop:
                exit_price, status = candle['open'], 'STOP_GAP'
            elif (j != index or at_open) and open_target:
                exit_price, status = target, 'TARGET_GAP_LIMIT'
            elif hit_stop and hit_target:
                return {**result, 'status': 'AMBIGUOUS_EXIT_BAR'}
            elif hit_stop:
                exit_price, status = stop, 'STOP'
            elif hit_target:
                exit_price, status = target, 'TARGET'
            else:
                continue
        gross = (exit_price - fill) * quantity * (1 if long else -1)
        charge = costs(fill, exit_price, quantity, long, slippage_bps)
        return {**result, 'status': status, 'exit_at': candle['timestamp'].isoformat(),
                'gross': round(gross, 2), 'cost': round(charge, 2),
                'net': round(gross - charge, 2), 'net_r': round((gross - charge) / budget, 6)}
    return {**result, 'status': 'INCOMPLETE_DATA'}


def summarize(rows):
    resolved = [r for r in rows if isinstance(r['net'], (int, float))]
    return {'setups': len(rows), 'resolved_trades': len(resolved),
            'wins': sum(r['net'] > 0 for r in resolved),
            'gross': round(sum(r['gross'] for r in resolved), 2),
            'costs': round(sum(r['cost'] for r in resolved), 2),
            'net': round(sum(r['net'] for r in resolved), 2),
            'mean_net_r': round(sum(r['net_r'] for r in resolved) / len(resolved), 4) if resolved else None,
            'statuses': dict(Counter(r['status'] for r in rows))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('candles.duckdb'))
    parser.add_argument('--plans', type=Path, default=Path('trade_plans'))
    parser.add_argument('--supplement', type=Path, default=Path('/tmp/tradingbot-missing-replay-candles.json'))
    parser.add_argument('--output', type=Path, default=Path('research/output/entry_comparison'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / 'candles.json'
    plans, data = load_inputs(args.database, args.plans, args.supplement, cache)
    rows = []
    for plan in plans:
        for leg in plan['legs']:
            for bps in (5, 10):
                for variant in VARIANTS:
                    rows.append({'date': plan['trade_date'], 'symbol': leg['symbol'],
                                 'variant': variant, 'slippage_bps_per_side': bps,
                                 **simulate(leg, data.get(plan['trade_date'] + '|' + leg['symbol'], []), variant, bps)})
    with (args.output / 'trades.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    summary = {'as_of': AS_OF, 'cost_source': COST_SOURCE,
               'candles_sha256': hashlib.sha256(cache.read_bytes()).hexdigest(),
               'rules': __doc__, 'results': {}}
    for bps in (5, 10):
        summary['results'][str(bps)] = {v: summarize([r for r in rows if r['variant'] == v and r['slippage_bps_per_side'] == bps]) for v in VARIANTS}
    primary = [r for r in rows if r['slippage_bps_per_side'] == 5]
    summary['daily_net'] = {d: {v: round(sum(r['net'] for r in primary if r['date'] == d and r['variant'] == v and isinstance(r['net'], (int, float))), 2) for v in VARIANTS} for d in sorted({r['date'] for r in primary})}
    summary['plan_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.plans.glob('????-??-??.json')) if p.stem <= AS_OF}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps({'results': summary['results'], 'daily_net': summary['daily_net']}, indent=2))


if __name__ == '__main__':
    main()
