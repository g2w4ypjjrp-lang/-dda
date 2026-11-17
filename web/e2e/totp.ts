import { createHmac } from "node:crypto";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function base32(secret: string): Buffer {
  let bits = "";
  for (const c of secret.replace(/=+$/, "").toUpperCase()) bits += ALPHABET.indexOf(c).toString(2).padStart(5, "0");
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

export function totp(secret: string, step = Math.floor(Date.now() / 30000)): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  const value = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(value).padStart(6, "0");
}

/** Sunucu aynı zaman adımını ikinci kez kabul etmez; bir sonraki adıma kadar bekler. */
export async function freshTotp(secret: string, used: Set<number>): Promise<string> {
  for (;;) {
    const step = Math.floor(Date.now() / 30000);
    if (!used.has(step)) {
      used.add(step);
      return totp(secret, step);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
}
