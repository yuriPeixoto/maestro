import type { Release } from '../services/api'

/** The dashboard's own version, from package.json at build time. */
export const DASHBOARD_VERSION = __APP_VERSION__

/** "0.1.0" -> [0, 1, 0]; anything after a hyphen (pre-release) is ignored. */
const parts = (version: string) => version.split('-')[0].split('.').map(Number)

export function compareVersions(a: string, b: string): number {
  const [pa, pb] = [parts(a), parts(b)]
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

/** Releases newer than `lastSeen`, all of them when nothing was seen yet. */
export function unseenReleases(releases: Release[], lastSeen: string | null): Release[] {
  if (!lastSeen) return releases
  return releases.filter((r) => compareVersions(r.version, lastSeen) > 0)
}

/** Notes in the interface's language, falling back to English. */
export function notesFor(release: Release, language: string): string[] {
  const lang = language.startsWith('pt') ? 'pt-BR' : 'en'
  return release.notes[lang] ?? release.notes.en ?? []
}

/** "2026-11-05" -> "5 de novembro de 2026" / "November 5, 2026". */
export function releaseDate(isoDate: string, language: string): string {
  const [year, month, day] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString(language, { day: 'numeric', month: 'long', year: 'numeric' })
}
