"use client";
import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "./api";
import type { User } from "./types";

export function useUser() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<User>("/auth/me")
      .then(setUser)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  return { user, loading };
}
