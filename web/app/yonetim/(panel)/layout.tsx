import type { ReactNode } from "react";

import { AdminShell } from "@/components/admin";

export const metadata = { title: "Yönetim", robots: { index: false, follow: false } };

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
