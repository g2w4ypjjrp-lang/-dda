// API istemcisi: aynı kökene (/v1, /admin/v1) istek atar; çerezler tarayıcıda kalır.
// Hata gövdesi her zaman {code, detail}; arayüz `code` ile davranır (ör. reauth_required).

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields?: { loc: string[]; msg: string }[],
  ) {
    super(message);
  }
}

type Json = Record<string, unknown> | unknown[];

export async function api<T>(path: string, init?: { method?: string; body?: Json; signal?: AbortSignal }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: init?.method ?? (init?.body ? "POST" : "GET"),
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
      body: init?.body ? JSON.stringify(init.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
      signal: init?.signal,
    });
  } catch {
    throw new ApiError(0, "network", "Sunucuya ulaşılamadı. Bağlantınızı kontrol edin.");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const body = (data ?? {}) as { code?: string; detail?: string; fields?: { loc: string[]; msg: string }[] };
    throw new ApiError(
      res.status,
      body.code ?? `http_${res.status}`,
      body.detail ?? (res.status >= 500 ? "Sunucu hatası. Lütfen biraz sonra tekrar deneyin." : "İstek tamamlanamadı."),
      body.fields,
    );
  }
  return data as T;
}

export const post = <T>(path: string, body: Json = {}) => api<T>(path, { method: "POST", body });
export const put = <T>(path: string, body: Json) => api<T>(path, { method: "PUT", body });
export const patch = <T>(path: string, body: Json) => api<T>(path, { method: "PATCH", body });
