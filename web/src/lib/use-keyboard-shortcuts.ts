"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function useKeyboardShortcuts() {
  const router = useRouter();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      switch (e.key.toLowerCase()) {
        case "e":
          router.push("/trading");
          break;
        case "a":
          router.push("/analysis");
          break;
        case "d":
          router.push("/");
          break;
        case "r":
          router.push("/review");
          break;
        case "h":
          router.push("/history");
          break;
        case "s":
          router.push("/settings");
          break;
        case "?":
          document.dispatchEvent(new CustomEvent("show-shortcuts"));
          break;
      }
    };

    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [router]);
}
