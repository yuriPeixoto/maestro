import { useTranslation } from 'react-i18next'
import Layout from './Layout'
import ReleaseNotes from './ReleaseNotes'
import type { ViewType } from '../App'
import { useAbout } from '../hooks/useAbout'
import { DASHBOARD_VERSION, compareVersions, releaseDate } from '../utils/release'
import { relativeTime } from '../utils/format'

const REPOSITORY_URL = 'https://github.com/yuriPeixoto/maestro'
const LINKS = [
  { key: 'github', href: REPOSITORY_URL },
  { key: 'license', href: `${REPOSITORY_URL}/blob/main/LICENSE` },
  { key: 'install', href: `${REPOSITORY_URL}/blob/main/docs/deployment.md` },
]

function VersionPill({ current }: { current: boolean }) {
  const { t } = useTranslation()
  return (
    <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full whitespace-nowrap ${
      current ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'
    }`}>
      {current ? t('about.current') : t('about.outdated')}
    </span>
  )
}

// "dev" and "unknown" parse as NaN and never match: they read as outdated, as they should.
const sameVersion = (a: string, b: string) => compareVersions(a, b) === 0

export default function About({ setView }: { setView: (view: ViewType) => void }) {
  const { t, i18n } = useTranslation()
  const { data: about, isLoading } = useAbout()
  const released = about?.releases.find((r) => r.version === about.version)

  return (
    <Layout currentView="about" setView={setView} title={t('about.title')}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-3xl font-bold font-mono tracking-tight">
              Maestro <span className="text-violet-300">{about?.version ?? DASHBOARD_VERSION}</span>
            </h1>
            <p className="text-sm text-slate-400">
              {t('about.tagline')}
              {released && ` ${t('about.releasedOn', { date: releaseDate(released.date, i18n.language) })}`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {LINKS.map((link) => (
              <a
                key={link.key}
                href={link.href}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-mono px-3 py-1 rounded-full border border-white/10 text-slate-400 hover:text-slate-100 hover:border-brand-purple/40"
              >
                {t(`about.links.${link.key}`)}
              </a>
            ))}
          </div>
        </div>

        {isLoading || !about ? (
          <p className="text-sm text-slate-500">{t('common.loading')}</p>
        ) : (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <section className="rounded-2xl border border-white/10 bg-brand-slate p-5 space-y-3 min-w-0">
                <h2 className="text-sm font-bold text-slate-200">{t('about.components')}</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="text-[10px] text-slate-500 uppercase tracking-widest">
                      <tr><th className="py-1.5 pr-3 font-medium">{t('about.part')}</th><th className="py-1.5 pr-3 font-medium">{t('about.version')}</th><th /></tr>
                    </thead>
                    <tbody>
                      <tr className="border-t border-white/5">
                        <td className="py-2 pr-3">{t('about.dashboard')}</td>
                        <td className="py-2 pr-3 font-mono">{DASHBOARD_VERSION}</td>
                        <td className="py-2"><VersionPill current={sameVersion(DASHBOARD_VERSION, about.version)} /></td>
                      </tr>
                      <tr className="border-t border-white/5">
                        <td className="py-2 pr-3">{t('about.api')}</td>
                        <td className="py-2 pr-3 font-mono">{about.version}</td>
                        <td className="py-2"><VersionPill current /></td>
                      </tr>
                      <tr className="border-t border-white/5">
                        <td className="py-2 pr-3">ClickHouse</td>
                        <td className="py-2 pr-3 font-mono">{about.clickhouse_version ?? '—'}</td>
                        <td className="py-2 text-xs text-slate-500">{t('about.metricsDatabase')}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-slate-500">{t('about.componentsHint')}</p>
              </section>

              <section className="rounded-2xl border border-white/10 bg-brand-slate p-5 space-y-3 min-w-0">
                <h2 className="text-sm font-bold text-slate-200">{t('about.agents')}</h2>
                {about.agents.length === 0 ? (
                  <p className="text-sm text-slate-500">{t('about.noAgents')}</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead className="text-[10px] text-slate-500 uppercase tracking-widest">
                        <tr>
                          <th className="py-1.5 pr-3 font-medium">{t('about.server')}</th>
                          <th className="py-1.5 pr-3 font-medium">{t('about.version')}</th>
                          <th className="py-1.5 pr-3 font-medium">{t('about.lastSeen')}</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {about.agents.map((agent) => (
                          <tr key={agent.server_id} className="border-t border-white/5">
                            <td className="py-2 pr-3 font-mono">{agent.server_id}</td>
                            <td className="py-2 pr-3 font-mono">{agent.version}</td>
                            <td className="py-2 pr-3 text-slate-400">{agent.last_seen ? relativeTime(agent.last_seen, t) : '—'}</td>
                            <td className="py-2"><VersionPill current={sameVersion(agent.version, about.version)} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="text-xs text-slate-500">{t('about.agentsHint')}</p>
              </section>
            </div>

            <section className="rounded-2xl border border-white/10 bg-brand-slate p-5 space-y-4">
              <h2 className="text-sm font-bold text-slate-200">{t('about.history')}</h2>
              <div className="divide-y divide-white/5">
                {about.releases.map((release) => (
                  <div key={release.version} className="py-4 first:pt-0"><ReleaseNotes release={release} /></div>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </Layout>
  )
}
