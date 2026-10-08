"use client";

import { useState, useEffect } from "react";

const SQUARE_OFF_HOUR = 15;
const SQUARE_OFF_MINUTE = 10;
const MARKET_OPEN_HOUR = 9;
const MARKET_OPEN_MINUTE = 15;

function getTimeToSquareOff(): { hours: number; minutes: number; seconds: number; active: boolean } {
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes();

  const afterOpen = h > MARKET_OPEN_HOUR || (h === MARKET_OPEN_HOUR && m >= MARKET_OPEN_MINUTE);
  const beforeSquareOff = h < SQUARE_OFF_HOUR || (h === SQUARE_OFF_HOUR && m < SQUARE_OFF_MINUTE);

  if (!afterOpen || !beforeSquareOff) {
    return { hours: 0, minutes: 0, seconds: 0, active: false };
  }

  const target = new Date(now);
  target.setHours(SQUARE_OFF_HOUR, SQUARE_OFF_MINUTE, 0, 0);
  const diff = Math.max(0, Math.floor((target.getTime() - now.getTime()) / 1000));

  return {
    hours: Math.floor(diff / 3600),
    minutes: Math.floor((diff % 3600) / 60),
    seconds: diff % 60,
    active: true,
  };
}

export function SquareOffCountdown() {
  const [time, setTime] = useState(getTimeToSquareOff);

  useEffect(() => {
    const interval = setInterval(() => setTime(getTimeToSquareOff()), 1000);
    return () => clearInterval(interval);
  }, []);

  if (!time.active) return null;

  const urgent = time.hours === 0 && time.minutes < 30;

  return (
    <div className={`flex items-center gap-1.5 text-xs font-mono ${urgent ? "text-[#f85149]" : "text-[#5a6a7f]"}`}>
      <span className="text-[10px] uppercase tracking-wider">SQ OFF</span>
      <span>{String(time.hours).padStart(2, "0")}:{String(time.minutes).padStart(2, "0")}:{String(time.seconds).padStart(2, "0")}</span>
    </div>
  );
}
