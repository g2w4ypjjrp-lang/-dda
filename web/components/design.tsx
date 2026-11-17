"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import {
  DESIGN_COOKIE, PREVIEW_KEY, designAttrs, designCss,
  type DesignConfig, type DesignPayload,
} from "@/lib/design";

interface DesignState {
  key: string;
  config: DesignConfig | null;
  payload: DesignPayload | null;
  /** Taslak/başka tasarım önizlemesi etkin mi (Design Studio veya ?tasarim=). */
  preview: boolean;
}

const Ctx = createContext<DesignState>({ key: "signature-black", config: null, payload: null, preview: false });

export const useDesign = () => useContext(Ctx);

/** Varsayılanlarla birlikte yerleşim kararları (API'ye ulaşılamazsa Signature Black yerleşimi). */
export function useLayout() {
  const { config } = useDesign();
  return {
    shell: config?.layout.shell ?? "topbar",
    hero: config?.layout.hero ?? "signature",
    matchList: config?.layout.match_list ?? "rows",
    logo: config?.layout.logo ?? "monogram",
    mobileNav: config?.mobile.nav ?? "tabs",
    chart: config?.components.chart ?? "area",
    chartStroke: config?.components.chart_stroke ?? 2,
    chartGrid: config?.components.chart_grid ?? true,
    mode: config?.mode ?? "dark",
  } as const;
}

function apply(key: string, config: DesignConfig) {
  const root = document.documentElement;
  for (const a of [...root.attributes]) if (a.name.startsWith("data-") && a.name !== "data-scroll-behavior") root.removeAttribute(a.name);
  for (const [k, v] of Object.entries(designAttrs(key, config))) root.setAttribute(k, v);
}

function injectPreview(config: DesignConfig) {
  let el = document.getElementById("mi-design-preview");
  if (!el) {
    el = document.createElement("style");
    el.id = "mi-design-preview";
    document.head.appendChild(el);
  }
  el.textContent = designCss(PREVIEW_KEY, config);
}

/** Kullanıcının tasarım tercihini çerezde saklar (null = site varsayılanı) ve sayfayı yeniler. */
export function chooseDesign(key: string | null) {
  document.cookie = key
    ? `${DESIGN_COOKIE}=${encodeURIComponent(key)}; path=/; max-age=31536000; samesite=lax`
    : `${DESIGN_COOKIE}=; path=/; max-age=0; samesite=lax`;
  window.location.reload();
}

export function DesignProvider({ payload, initialKey, children }: { payload: DesignPayload | null; initialKey: string; children: ReactNode }) {
  const [state, setState] = useState<DesignState>(() => ({
    key: initialKey,
    config: payload?.designs[initialKey]?.config ?? null,
    payload,
    preview: false,
  }));

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const draft = params.get("taslak");
    const requested = params.get("tasarim");
    if (draft && /^\d+$/.test(draft)) {
      // Taslak önizlemesi yalnızca design.read yetkili yöneticiye açılır (yetki API'de denetlenir).
      api<{ design_key: string; config: DesignConfig }>(`/admin/v1/design/versions/${draft}`)
        .then((v) => {
          injectPreview(v.config);
          apply(PREVIEW_KEY, v.config);
          setState((s) => ({ ...s, key: PREVIEW_KEY, config: v.config, preview: true }));
        })
        .catch(() => undefined);
    } else if (requested && payload?.designs[requested]) {
      const config = payload.designs[requested].config;
      apply(requested, config);
      setState((s) => ({ ...s, key: requested, config, preview: true }));
    }
    // Design Studio düzenleyicisinden canlı önizleme (yalnızca aynı köken).
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin || e.data?.type !== "mi-design-preview" || !e.data.config) return;
      const config = e.data.config as DesignConfig;
      injectPreview(config);
      apply(PREVIEW_KEY, config);
      setState((s) => ({ ...s, key: PREVIEW_KEY, config, preview: true }));
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [payload]);

  const value = useMemo(() => state, [state]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
