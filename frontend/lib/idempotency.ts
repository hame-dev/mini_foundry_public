export function idempotencyKey(prefix = "mf"): string {
  const random = crypto.getRandomValues(new Uint32Array(4));
  return `${prefix}_${Array.from(random).map((n) => n.toString(16)).join("")}`;
}
