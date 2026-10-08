"use client";

export function ErrorFallback({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20">
      <div className="h-12 w-12 rounded-full bg-[#f85149]/10 flex items-center justify-center">
        <span className="text-[#f85149] text-lg">!</span>
      </div>
      <h2 className="text-sm font-semibold text-[#e6edf3]">Something went wrong</h2>
      <p className="text-xs text-[#5a6a7f] max-w-sm text-center">{error.message}</p>
      <button
        onClick={reset}
        className="rounded-md bg-[rgba(212,160,21,0.2)] border border-[rgba(212,160,21,0.3)] px-3 py-1.5 text-xs font-medium text-[#d4a015] hover:bg-[rgba(212,160,21,0.3)]"
      >
        Try again
      </button>
    </div>
  );
}
