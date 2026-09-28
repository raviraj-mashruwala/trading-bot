"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";

function CallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    const requestToken = searchParams.get("request_token");
    if (!requestToken) {
      setStatus("error");
      setError("No request_token in URL. Please try logging in again.");
      return;
    }

    api.kiteCallback(requestToken)
      .then(() => {
        setStatus("success");
        queryClient.invalidateQueries({ queryKey: ["kite-status"] });
        setTimeout(() => router.push("/analysis"), 2000);
      })
      .catch((err) => {
        setStatus("error");
        setError(err.message || "Token exchange failed");
      });
  }, [searchParams, router, queryClient]);

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="bg-[#0f1419] rounded-lg p-8 max-w-md w-full text-center border border-[#1c2736]/50">
        {status === "loading" && (
          <>
            <div className="w-8 h-8 border-2 border-[#d4a015] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <h2 className="text-lg font-bold text-[#c9d1d9] mb-2">Connecting to Kite...</h2>
            <p className="text-[#5a6a7f] text-sm">Exchanging token with Zerodha</p>
          </>
        )}
        {status === "success" && (
          <>
            <div className="w-10 h-10 rounded-full bg-[#2da44e]/20 text-[#2da44e] flex items-center justify-center mx-auto mb-4 text-xl">✓</div>
            <h2 className="text-lg font-bold text-[#c9d1d9] mb-2">Kite Connected</h2>
            <p className="text-[#5a6a7f] text-sm">Redirecting to analysis...</p>
          </>
        )}
        {status === "error" && (
          <>
            <div className="w-10 h-10 rounded-full bg-[#f85149]/20 text-[#f85149] flex items-center justify-center mx-auto mb-4 text-xl">✗</div>
            <h2 className="text-lg font-bold text-[#c9d1d9] mb-2">Connection Failed</h2>
            <p className="text-[#5a6a7f] text-sm mb-4">{error}</p>
            <button
              onClick={() => router.push("/analysis")}
              className="px-4 py-2 bg-[#d4a015] text-[#070a0f] rounded-md text-sm font-medium hover:bg-[#d4a015]/90 cursor-pointer"
            >
              Back to Analysis
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function KiteCallbackPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-[#d4a015] border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <CallbackContent />
    </Suspense>
  );
}
