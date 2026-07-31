const PUBLIC_TOKEN_ROUTE_HEADERS = {
  source: "/r/:path*",
  headers: [
    { key: "Referrer-Policy", value: "no-referrer" },
    { key: "Cache-Control", value: "no-store" },
    { key: "X-Robots-Tag", value: "noindex, nofollow" },
  ],
};

export function publicRouteHeaders() {
  return [PUBLIC_TOKEN_ROUTE_HEADERS];
}
