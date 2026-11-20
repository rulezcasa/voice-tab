const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** "13.3" | 13.3 -> "$13.30" */
export function money(v: string | number): string {
  return usd.format(typeof v === 'string' ? Number(v) : v)
}

/** "-13.30" -> "$13.30" (sign dropped; callers say owes/owed) */
export function absMoney(v: string | number): string {
  return money(Math.abs(typeof v === 'string' ? Number(v) : v))
}

export function cents(v: string | number): number {
  return Math.round((typeof v === 'string' ? Number(v) : v) * 100)
}

export function fromCents(c: number): string {
  return (c / 100).toFixed(2)
}

/** "2026-11-18" -> Date at local midnight */
export function parseDay(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function isoDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function prettyDay(s: string): string {
  const d = parseDay(s)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((today.getTime() - d.getTime()) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

export function initials(name: string): string {
  const parts = name.split(' ')
  return parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
}

/** "Qwen/Qwen3-Reranker-0.6B" -> "Qwen3-Reranker-0.6B" */
export function shortModel(m: string | null): string {
  if (!m) return ''
  return m.includes('/') ? m.split('/').pop()! : m
}
