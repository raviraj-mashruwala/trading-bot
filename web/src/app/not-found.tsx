import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20">
      <span className="text-5xl font-mono text-[#5a6a7f]">404</span>
      <p className="text-sm text-[#5a6a7f]">Page not found</p>
      <Link
        href="/"
        className="rounded-md bg-[rgba(212,160,21,0.2)] border border-[rgba(212,160,21,0.3)] px-3 py-1.5 text-xs font-medium text-[#d4a015] hover:bg-[rgba(212,160,21,0.3)]"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}
