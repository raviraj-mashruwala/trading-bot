import { NextRequest, NextResponse } from "next/server";

const AUTH_USER = process.env.AUTH_USER || "admin";
const AUTH_PASS = process.env.AUTH_PASS || "";

export function middleware(request: NextRequest) {
  if (!AUTH_PASS) return NextResponse.next();

  // Skip auth for API proxy routes (handled server-side)
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.next();
  }

  const auth = request.headers.get("authorization");
  if (auth) {
    const [scheme, encoded] = auth.split(" ");
    if (scheme === "Basic") {
      const decoded = atob(encoded);
      const [user, pass] = decoded.split(":");
      if (user === AUTH_USER && pass === AUTH_PASS) {
        return NextResponse.next();
      }
    }
  }

  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Trading Bot"' },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
