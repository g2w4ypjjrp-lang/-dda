"use client";

// "Kupona ekle" sepeti: yalnızca tarayıcıda tutulan taslak seçimler. Olasılık ve geçerlilik her
// zaman sunucuda (/v1/coupons/preview) tahmin kayıtlarından yeniden hesaplanır; burada saklanan
// etiketler yalnızca görüntü içindir.
import { useSyncExternalStore } from "react";

export interface BasketLeg {
  prediction_id: number;
  fixture_id: number;
  market: string;
  pick: string;
  label: string;
  match: string;
  kickoff_at: string;
}

const KEY = "mi.basket.v1";
const listeners = new Set<() => void>();
let cache: BasketLeg[] | null = null;
const EMPTY: BasketLeg[] = [];

function read(): BasketLeg[] {
  if (cache) return cache;
  try {
    const raw = window.localStorage.getItem(KEY);
    cache = raw ? (JSON.parse(raw) as BasketLeg[]) : [];
  } catch {
    cache = [];
  }
  return cache;
}

function write(legs: BasketLeg[]) {
  cache = legs;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(legs));
  } catch {
    /* gizli sekme vb.: yalnızca bellekte kalır */
  }
  listeners.forEach((l) => l());
}

const same = (a: Pick<BasketLeg, "prediction_id" | "market" | "pick">, b: Pick<BasketLeg, "prediction_id" | "market" | "pick">) =>
  a.prediction_id === b.prediction_id && a.market === b.market && a.pick === b.pick;

export const basket = {
  has: (leg: Pick<BasketLeg, "prediction_id" | "market" | "pick">) => read().some((x) => same(x, leg)),
  toggle(leg: BasketLeg) {
    const legs = read();
    write(legs.some((x) => same(x, leg)) ? legs.filter((x) => !same(x, leg)) : [...legs, leg].slice(-20));
  },
  remove: (leg: BasketLeg) => write(read().filter((x) => !same(x, leg))),
  clear: () => write([]),
};

export function useBasket(): BasketLeg[] {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      const onStorage = (e: StorageEvent) => { if (e.key === KEY) { cache = null; cb(); } };
      window.addEventListener("storage", onStorage);
      return () => { listeners.delete(cb); window.removeEventListener("storage", onStorage); };
    },
    read,
    () => EMPTY,
  );
}
