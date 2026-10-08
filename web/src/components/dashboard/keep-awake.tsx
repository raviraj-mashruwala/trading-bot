"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function KeepAwake() {
  const [active, setActive] = useState(false);
  const [tick, setTick] = useState(0);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const startVideoFallback = useCallback(() => {
    if (videoRef.current) return;
    const video = document.createElement("video");
    video.setAttribute("playsinline", "");
    video.setAttribute("muted", "");
    video.style.position = "fixed";
    video.style.top = "-1px";
    video.style.left = "-1px";
    video.style.width = "1px";
    video.style.height = "1px";
    video.style.opacity = "0.01";
    // 1-second silent webm loop
    video.src =
      "data:video/webm;base64,GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQJChYECGFOAZwEAAAAAAAHTEU2bdLpNu4tTq4QVSalmU6yBoU27i1OrhBZUrmtTrIHGTbuMU6uEElTDZ1OsijZMu4xTq4QGU6mlU2iBoUu7jFOrhBJUw2dTrIHATbuMU6uEHFO7a1OsgAAAAAAAAAAAAFNzc3MAAAAAAAAAAABAAAAAAAWAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHAAAARW==";
    video.loop = true;
    video.muted = true;
    document.body.appendChild(video);
    video.play().catch(() => {});
    videoRef.current = video;
  }, []);

  const stopVideoFallback = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.remove();
      videoRef.current = null;
    }
  }, []);

  const start = useCallback(async () => {
    setActive(true);
    setTick(0);

    // Wake Lock API
    if ("wakeLock" in navigator) {
      try {
        wakeLockRef.current = await navigator.wakeLock.request("screen");
        wakeLockRef.current.addEventListener("release", () => {
          // Re-acquire if page becomes visible again while still active
        });
      } catch {
        startVideoFallback();
      }
    } else {
      startVideoFallback();
    }

    // Heartbeat tick every 30s for visual feedback
    intervalRef.current = setInterval(() => {
      setTick((t) => t + 1);

      // Re-acquire wake lock if it was released (e.g. tab switch)
      if ("wakeLock" in navigator && !wakeLockRef.current) {
        navigator.wakeLock.request("screen").then((s) => {
          wakeLockRef.current = s;
        }).catch(() => {});
      }
    }, 30_000);
  }, [startVideoFallback]);

  const stop = useCallback(() => {
    setActive(false);
    setTick(0);

    if (wakeLockRef.current) {
      wakeLockRef.current.release();
      wakeLockRef.current = null;
    }

    stopVideoFallback();

    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, [stopVideoFallback]);

  // Re-acquire wake lock on visibility change
  useEffect(() => {
    if (!active) return;

    const handleVisibility = async () => {
      if (document.visibilityState === "visible" && active && "wakeLock" in navigator) {
        try {
          wakeLockRef.current = await navigator.wakeLock.request("screen");
        } catch {
          // ignore
        }
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [active]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wakeLockRef.current) wakeLockRef.current.release();
      stopVideoFallback();
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [stopVideoFallback]);

  return (
    <button
      onClick={active ? stop : start}
      className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[10px] transition-colors cursor-pointer ${
        active
          ? "bg-[#2da44e]/10 text-[#2da44e] border border-[#2da44e]/30"
          : "text-muted-foreground/50 hover:text-muted-foreground/80 hover:bg-[#161d26] border border-transparent"
      }`}
      title={active ? `Keeping awake — ${tick} ticks` : "Prevent system sleep"}
    >
      <span className={`inline-flex h-1.5 w-1.5 rounded-full ${active ? "bg-[#2da44e] animate-pulse" : "bg-muted-foreground/30"}`} />
      {active ? "Awake" : "Keep Awake"}
    </button>
  );
}
