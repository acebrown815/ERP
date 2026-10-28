"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";

import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

const SessionContext = createContext<Me | null>(null);

export const meQueryKey = ["auth", "me"] as const;

export function useMeQuery() {
  return useQuery({ queryKey: meQueryKey, queryFn: () => api.get<Me>("/auth/me"), staleTime: 60_000, retry: false });
}

export function SessionProvider({ me, children }: { me: Me; children: ReactNode }) {
  return <SessionContext.Provider value={me}>{children}</SessionContext.Provider>;
}

export function useMe(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error("useMe must be used inside <SessionProvider>");
  return me;
}

/** UI gating only; the API enforces every permission again. */
export function useCan() {
  const me = useMe();
  return (permission: string) => permission in me.permissions;
}

export function Can({ permission, children }: { permission: string; children: ReactNode }) {
  return useCan()(permission) ? <>{children}</> : null;
}

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      qc.clear();
      router.replace("/login");
    }
  };
}
