"""Replay saved plans without calling a broker or changing source databases.

This is a mechanical limit-entry baseline, not a simulation of EntryGuard,
partial exits, trailing stops, market fallback, or queue priority. Ambiguous
OHLC ordering is excluded from P&L. Costs are estimates, not contract notes.
Run against a closed database or a consistent snapshot.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import time
from pathlib import Path

import duckdb


def estimated_cost(buy: float, sell: float, quantity: int) -> float:
    """NSE cash intraday schedule checked 2026-10-30; 5 bps slippage/side."""
    buy_value, sell_value = buy * quantity, sell * quantity
    turnover = buy_value + sell_value
    brokerage = min(20, buy_value * .0003) + min(20, sell_value * .0003)
    exchange = turnover * .0000307
    sebi = turnover * .000001
    return (brokerage + exchange + sebi + sell_value * .00025
            + buy_value * .00003 + .18 * (brokerage + exchange + sebi)
            + turnover * .0005)


def replay(leg: dict, candles: list[dict]) -> dict:
    start = time.fromisoformat(leg['entry_window_start'])
    end = min(time.fromisoformat(leg['entry_window_end']),
              time.fromisoformat(leg['max_entry_wait']))
    square_off = time.fromisoformat(leg['exit_before'])
    result = {'status': 'NO_ENTRY', 'entry_at': '', 'exit_at': '',
              'fill': '', 'exit': '', 'gross': '', 'cost': '', 'net': ''}
    if not candles:
        return {**result, 'status': 'NO_DATA'}
    if candles[0]['timestamp'].time() > start:
        return {**result, 'status': 'INCOMPLETE_DATA'}
    long = leg['direction'] == 'long'
    limit, stop, target = (leg[k] for k in ('entry_price', 'stop_loss', 'target_1'))
    fill = None
    for candle in candles:
        timestamp = candle['timestamp']
        clock = timestamp.time()
        if clock < start:
            continue
        newly_entered = False
        filled_at_open = False
        if fill is None:
            if clock > end or clock >= square_off:
                break
            filled_at_open = candle['open'] <= limit if long else candle['open'] >= limit
            touched = candle['low'] <= limit if long else candle['high'] >= limit
            if not touched:
                continue
            fill = candle['open'] if filled_at_open else limit
            result.update(fill=fill, entry_at=timestamp.isoformat())
            newly_entered = True
        # Bars are start-labelled. Square off at the first available bar open
        # at/after the deadline; do not inspect that bar's later high or low.
        if clock >= square_off:
            price, status = candle['open'], 'SQUARE_OFF'
        else:
            hit_stop = candle['low'] <= stop if long else candle['high'] >= stop
            hit_target = candle['high'] >= target if long else candle['low'] <= target
            if (newly_entered and not filled_at_open and (hit_stop or hit_target)):
                return {**result, 'status': 'AMBIGUOUS_ENTRY_BAR'}
            open_stop = candle['open'] <= stop if long else candle['open'] >= stop
            open_target = candle['open'] >= target if long else candle['open'] <= target
            if open_stop:
                price, status = candle['open'], 'STOP_GAP'
            elif open_target:
                price, status = candle['open'], 'TARGET_GAP'
            elif hit_stop and hit_target:
                return {**result, 'status': 'AMBIGUOUS_EXIT_BAR'}
            elif hit_stop:
                price, status = stop, 'STOP'
            elif hit_target:
                price, status = target, 'TARGET'
            else:
                continue
        quantity = leg['quantity']
        gross = (price - fill) * quantity * (1 if long else -1)
        cost = estimated_cost(fill, price, quantity) if long else estimated_cost(price, fill, quantity)
        return {**result, 'status': status, 'exit_at': timestamp.isoformat(),
                'exit': price, 'gross': round(gross, 2), 'cost': round(cost, 2),
                'net': round(gross - cost, 2)}
    incomplete = fill is not None or candles[-1]['timestamp'].time() < end
    return {**result, 'status': 'INCOMPLETE_DATA' if incomplete else 'NO_ENTRY'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('candles.duckdb'))
    parser.add_argument('--plans', type=Path, default=Path('trade_plans'))
    parser.add_argument('--output', type=Path, default=Path('research/output/saved_plan_replay.csv'))
    args = parser.parse_args()
    connection = duckdb.connect(str(args.database), read_only=True)
    results = []
    for path in sorted(args.plans.glob('????-??-??.json')):
        plan = json.loads(path.read_text())
        for leg in plan.get('legs', []):
            candles, interval = [], ''
            for candidate in ('1m', '5m', '15m'):
                cursor = connection.execute(
                    'SELECT timestamp, open, high, low, close, volume FROM candles '
                    'WHERE symbol=? AND interval=? AND timestamp::DATE=? ORDER BY timestamp',
                    [leg['symbol'], candidate, plan['trade_date']],
                )
                names = [column[0] for column in cursor.description]
                candles = [dict(zip(names, row)) for row in cursor.fetchall()]
                if candles:
                    interval = candidate
                    break
            result = replay(leg, candles)
            if interval == '1m':
                session = [c for c in candles if time(9, 15) <= c['timestamp'].time()
                           <= time.fromisoformat(leg['exit_before'])]
                if any((right['timestamp'] - left['timestamp']).total_seconds() > 60
                       for left, right in zip(session, session[1:])):
                    result.update(status='GAPPED_DATA', gross='', cost='', net='')
            # Coarse bars cannot establish exact entry-window or square-off
            # timing. Keep coverage evidence, exclude their P&L from totals.
            if interval and interval != '1m':
                result.update(status='COARSE_DATA', gross='', cost='', net='')
            results.append({'date': plan['trade_date'], 'symbol': leg['symbol'],
                            'direction': leg['direction'], 'interval': interval,
                            'bars': len(candles), **result})
    connection.close()
    if not results:
        print('No saved plan legs found.')
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    from collections import Counter
    print(json.dumps({'legs': len(results), 'statuses': dict(Counter(r['status'] for r in results)),
                      'mechanical_net_sum_not_portfolio_return': round(sum(r['net'] for r in results if isinstance(r['net'], (int, float))), 2),
                      'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
