import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bug, ChevronDown, ChevronUp, Search, ShieldQuestion } from 'lucide-react'
import Pagination from './Pagination'
import { useVulnerabilities } from '../hooks/useSecurity'
import type { VulnEntry } from '../services/api'

const PAGE_SIZE = 20

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'unknown'] as const
type Severity = typeof SEVERITIES[number]
type SeverityFilter = Severity | 'all'

const SEV_STYLE: Record<Severity, { bg: string; text: string; border: string }> = {
  critical: { bg: 'rgba(239,68,68,0.12)',   text: '#F87171', border: 'rgba(239,68,68,0.25)' },
  high:     { bg: 'rgba(249,115,22,0.12)',  text: '#FB923C', border: 'rgba(249,115,22,0.25)' },
  medium:   { bg: 'rgba(245,158,11,0.12)',  text: '#FBBF24', border: 'rgba(245,158,11,0.25)' },
  low:      { bg: 'rgba(148,163,184,0.10)', text: '#94A3B8', border: 'rgba(148,163,184,0.2)' },
  unknown:  { bg: 'rgba(148,163,184,0.06)', text: '#64748B', border: 'rgba(148,163,184,0.15)' },
}

interface PackageGroup {
  key: string
  name: string
  version: string
  worst: Severity
  vulns: VulnEntry[]
}

const severityOf = (vuln: VulnEntry): Severity =>
  SEVERITIES.includes(vuln.severity as Severity) ? vuln.severity as Severity : 'unknown'

const severityRank = (severity: Severity): number => SEVERITIES.indexOf(severity)

function groupByPackage(vulns: VulnEntry[]): PackageGroup[] {
  const groups = new Map<string, PackageGroup>()
  for (const vuln of vulns) {
    const key = `${vuln.runtime}@${vuln.version}`
    const group = groups.get(key) ?? { key, name: vuln.runtime, version: vuln.version, worst: 'unknown', vulns: [] }
    group.vulns.push(vuln)
    if (severityRank(severityOf(vuln)) < severityRank(group.worst)) group.worst = severityOf(vuln)
    groups.set(key, group)
  }
  return [...groups.values()].sort((a, b) =>
    severityRank(a.worst) - severityRank(b.worst) || b.vulns.length - a.vulns.length,
  )
}

function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation()
  const style = SEV_STYLE[severity]
  return (
    <span
      className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold uppercase tracking-wider shrink-0"
      style={{ background: style.bg, color: style.text, border: `1px solid ${style.border}` }}
    >
      {t(`security.vulns.severity.${severity}`)}
    </span>
  )
}

function PackageRow({ group }: { group: PackageGroup }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  return (
    <div className="border-t border-white/5">
      <button
        onClick={() => setOpen(!open)}
        className="w-full p-3.5 text-left transition-colors hover:bg-white/3 flex items-center gap-3"
      >
        <SeverityBadge severity={group.worst} />
        <div className="min-w-0 flex-1">
          <div className="font-mono text-xs font-bold text-slate-100 truncate">{group.name}</div>
          <div className="font-mono text-[10px] text-slate-500 truncate">{group.version}</div>
        </div>
        <span className="font-mono text-xs text-slate-300 shrink-0">
          {t('security.vulns.cves', { count: group.vulns.length })}
        </span>
        {open ? <ChevronUp size={12} className="text-slate-500 shrink-0" /> : <ChevronDown size={12} className="text-slate-500 shrink-0" />}
      </button>
      {open && (
        <div className="pb-2">
          {group.vulns.map((vuln) => (
            <div key={vuln.cve_id} className="px-3.5 py-2 pl-10 border-t border-white/5 flex items-start gap-3">
              <SeverityBadge severity={severityOf(vuln)} />
              <div className="min-w-0 flex-1">
                <div className="font-mono text-xs text-slate-200">{vuln.cve_id}</div>
                {vuln.summary && <div className="text-[11px] text-slate-400 mt-0.5">{vuln.summary}</div>}
                <div className="text-[10px] font-mono text-slate-500 mt-1">
                  {vuln.fixed_version
                    ? <span className="text-brand-neon">{t('security.vulns.fixedIn', { version: vuln.fixed_version })}</span>
                    : t('security.vulns.noFix')}
                  {vuln.published_at && (
                    <span> · {t('security.vulns.publishedOn', { date: new Date(vuln.published_at).toLocaleDateString() })}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function VulnerabilitiesCard({ serverId }: { serverId: string }) {
  const { t } = useTranslation()
  const { data, isFetching, isLoading } = useVulnerabilities(serverId)
  const [severity, setSeverity] = useState<SeverityFilter>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)

  const vulns = useMemo(() => data?.vulnerabilities ?? [], [data])
  const allGroups = useMemo(() => groupByPackage(vulns), [vulns])

  const severityCounts = useMemo(() => {
    const counts: Partial<Record<Severity, number>> = {}
    for (const vuln of vulns) counts[severityOf(vuln)] = (counts[severityOf(vuln)] ?? 0) + 1
    return counts
  }, [vulns])

  const filteredGroups = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const matches = vulns.filter((vuln) =>
      (severity === 'all' || severityOf(vuln) === severity)
      && (!needle || [vuln.runtime, vuln.cve_id, vuln.summary].some((text) => text.toLowerCase().includes(needle))),
    )
    return groupByPackage(matches)
  }, [vulns, severity, search])

  const totalPages = Math.max(1, Math.ceil(filteredGroups.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageGroups = filteredGroups.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const changeSeverity = (next: SeverityFilter) => {
    setSeverity(next)
    setPage(1)
  }

  const changeSearch = (next: string) => {
    setSearch(next)
    setPage(1)
  }

  const scanned = data?.scanned_at
    ? t('security.vulns.lastScan', { date: new Date(data.scanned_at).toLocaleString() })
    : null

  return (
    <div className="glass-card overflow-hidden">
      <div className="px-4 py-3 border-b border-white/5 bg-white/5 flex items-center justify-between gap-3 flex-wrap">
        <h3 className="text-sm font-bold flex items-center gap-2">
          <Bug size={14} className="text-brand-purple" />
          {t('security.vulns.title')}
          {isFetching && <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-pulse" />}
        </h3>
        <div className="flex items-center gap-3 text-[11px] font-mono text-slate-500">
          {vulns.length > 0 && (
            <span className="text-slate-300">
              {t('security.vulns.summary', { count: vulns.length, packages: allGroups.length })}
            </span>
          )}
          {scanned && <span>{scanned}</span>}
        </div>
      </div>

      {isLoading ? (
        <p className="px-5 py-6 text-center text-xs text-slate-500">{t('common.loading')}</p>
      ) : !scanned ? (
        <div className="px-5 py-6 flex items-center justify-center gap-2 text-xs text-slate-400">
          <ShieldQuestion size={16} className="text-slate-500" />
          {t('security.vulns.notScanned')}
        </div>
      ) : vulns.length === 0 ? (
        <p className="px-5 py-6 text-center text-xs text-slate-400">{t('security.vulns.none')}</p>
      ) : (
        <>
          <div className="px-4 py-3 flex items-center gap-2 flex-wrap border-b border-white/5">
            <button
              onClick={() => changeSeverity('all')}
              className={`text-[11px] px-2.5 py-1 rounded-md font-mono transition-colors ${severity === 'all' ? 'bg-brand-purple/20 text-brand-purple' : 'text-slate-500 hover:text-slate-300'}`}
            >
              {t('security.vulns.all')} ({vulns.length})
            </button>
            {SEVERITIES.filter((level) => severityCounts[level]).map((level) => (
              <button
                key={level}
                onClick={() => changeSeverity(level)}
                className={`text-[11px] px-2.5 py-1 rounded-md font-mono transition-colors ${severity === level ? 'bg-brand-purple/20 text-brand-purple' : 'text-slate-500 hover:text-slate-300'}`}
              >
                {t(`security.vulns.severity.${level}`)} ({severityCounts[level]})
              </button>
            ))}
            <span className="flex-1" />
            <div className="relative w-56">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => changeSearch(e.target.value)}
                placeholder={t('security.vulns.search')}
                className="w-full bg-brand-dark border border-white/10 rounded pl-8 pr-3 py-1.5 text-xs font-mono focus:outline-none focus:border-brand-purple/50"
              />
            </div>
          </div>

          {pageGroups.length === 0 ? (
            <p className="px-5 py-6 text-center text-xs text-slate-500">{t('security.vulns.noMatch')}</p>
          ) : (
            pageGroups.map((group) => <PackageRow key={group.key} group={group} />)
          )}

          <Pagination page={currentPage} totalPages={totalPages} onChange={setPage} />
        </>
      )}
    </div>
  )
}
