"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, post } from "./api";
import type { AdminMe, Me } from "./types";

/** Oturum açmış kullanıcı (yoksa null). 401 hata değil, "giriş yapılmamış" demektir. */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/v1/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function useAdminMe() {
  return useQuery({
    queryKey: ["admin-me"],
    queryFn: async () => {
      try {
        return await api<AdminMe>("/admin/v1/me");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null;
        throw e;
      }
    },
  });
}

export function useLogout(scope: "app" | "admin" = "app") {
  const qc = useQueryClient();
  return async () => {
    await post(scope === "app" ? "/v1/auth/logout" : "/admin/v1/auth/logout").catch(() => undefined);
    await qc.invalidateQueries({ queryKey: [scope === "app" ? "me" : "admin-me"] });
    qc.removeQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("admin") || q.queryKey[0] === "me" });
  };
}
