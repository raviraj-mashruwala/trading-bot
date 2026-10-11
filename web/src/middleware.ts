import { NextRequest, NextResponse } from "next/server";

const AUTH_USER = process.env.AUTH_USER || "admin";
const AUTH_PASS = process.env.AUTH_PASS || "";

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export function middleware(request: NextRequest) {
  if (!AUTH_PASS) return NextResponse.next();

  const auth = request.headers.get("authorization");
  if (auth) {
    try {
      const [scheme, encoded] = auth.split(" ");
      if (scheme === "Basic" && encoded) {
        const decoded = atob(encoded);
        const colonIdx = decoded.indexOf(":");
        if (colonIdx > 0) {
          const user = decoded.slice(0, colonIdx);
          const pass = decoded.slice(colonIdx + 1);
          if (constantTimeEqual(user, AUTH_USER) && constantTimeEqual(pass, AUTH_PASS)) {
            return NextResponse.next();
          }
        }
      }
    } catch {
      // Invalid base64 or malformed header — fall through to 401
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
