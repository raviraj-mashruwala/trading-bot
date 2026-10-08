import { Skeleton } from "@/components/ui/skeleton";
export default function Loading() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-20 rounded-lg" />
      <Skeleton className="h-40 rounded-lg" />
      <Skeleton className="h-60 rounded-lg" />
    </div>
  );
}
