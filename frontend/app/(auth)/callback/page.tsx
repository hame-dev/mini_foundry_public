"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function AuthCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    const next = params.get("next") || "/workspace";
    router.replace(next);
  }, [params, router]);

  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <div className="app-card p-4 text-sm text-[var(--muted)]">Completing sign-in...</div>
    </main>
  );
}
