import { useTranslation } from 'react-i18next'
import {
    Terminal,
    Shield,
    LayoutDashboard,
    Bell,
    TrendingUp,
    Zap,
    Server,
    LogOut,
    Users,
    Info,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ViewType } from '../App';
import { useAuthStore } from '../store/authStore';
import { usePermissions } from '../hooks/usePermissions';
import { DASHBOARD_VERSION } from '../utils/release';
import RoleBadge from './users/RoleBadge';

interface SidebarProps {
    currentView: ViewType;
    setView: (view: ViewType) => void;
}

interface MenuItem {
    icon: LucideIcon
    label: string
    id: ViewType
}

const itemClass = (active: boolean) =>
    `flex items-center gap-3 w-full px-4 py-2.5 rounded-lg transition-all border ${active
        ? 'bg-brand-purple/10 text-brand-purple border-brand-purple/20'
        : 'text-slate-400 border-transparent hover:text-slate-100 hover:bg-white/5'
    }`

// About is about Maestro itself, not a working screen: kept apart, last, and drawn differently.
const aboutClass = (active: boolean) =>
    `flex items-center gap-3 w-full px-4 py-2 rounded-lg transition-all border text-xs font-medium ${active
        ? 'bg-sky-400/10 text-sky-300 border-sky-400/40'
        : 'text-slate-400 border-white/10 hover:text-sky-300 hover:border-sky-400/30 hover:bg-sky-400/5'
    }`

const Sidebar: React.FC<SidebarProps> = ({ currentView, setView }) => {
    const { t } = useTranslation()
    const username = useAuthStore((s) => s.username)
    const logout = useAuthStore((s) => s.logout)
    const { role, can } = usePermissions()

    const mainItems: MenuItem[] = [
        { icon: LayoutDashboard, label: t('nav.dashboard'),      id: 'dashboard' },
        { icon: Terminal,        label: t('nav.logs'),            id: 'logs' },
        { icon: Server,          label: t('nav.infrastructure'),  id: 'infrastructure' },
        { icon: Shield,          label: t('nav.security'),        id: 'security' },
        { icon: Bell,            label: t('nav.alerts'),          id: 'alerts' },
        { icon: TrendingUp,      label: t('nav.capacity'),        id: 'capacity' },
    ];
    const adminItems: MenuItem[] = can('users.manage') || can('audit.view')
        ? [{ icon: Users, label: t('nav.users'), id: 'users' }]
        : [];

    const renderItem = (item: MenuItem) => (
        <button
            key={item.id}
            type="button"
            onClick={() => setView(item.id)}
            aria-current={currentView === item.id ? 'page' : undefined}
            className={itemClass(currentView === item.id)}
        >
            <item.icon className="w-4 h-4" aria-hidden="true" />
            <span className="text-sm font-medium">{item.label}</span>
        </button>
    )

    return (
        <aside className="w-64 border-r border-white/5 bg-brand-dark hidden lg:flex flex-col h-screen sticky top-0">
            <div className="p-6 flex items-center gap-3">
                <div className="w-8 h-8 bg-brand-purple rounded-lg flex items-center justify-center shadow-[0_0_15px_rgba(124,58,237,0.4)]">
                    <Zap className="w-5 h-5 text-white fill-current" aria-hidden="true" />
                </div>
                <span className="text-xl font-bold tracking-tight text-glow-purple">Maestro</span>
                <button
                    type="button"
                    onClick={() => setView('about')}
                    title={t('nav.about')}
                    className="self-end mb-0.5 text-[11px] font-mono text-slate-500 hover:text-violet-300 transition-colors"
                >
                    v{DASHBOARD_VERSION}
                </button>
            </div>

            <nav className="flex-1 px-4 py-4 flex flex-col gap-1 overflow-y-auto" aria-label={t('nav.menu')}>
                {mainItems.map(renderItem)}

                {adminItems.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-white/5 flex flex-col gap-1" role="group" aria-labelledby="nav-admin">
                        <span id="nav-admin" className="px-4 pb-1 text-[10px] text-slate-500 uppercase tracking-widest font-bold">
                            {t('nav.administration')}
                        </span>
                        {adminItems.map(renderItem)}
                    </div>
                )}

                <div className="mt-auto pt-3 border-t border-white/5">
                    <button
                        type="button"
                        onClick={() => setView('about')}
                        aria-current={currentView === 'about' ? 'page' : undefined}
                        className={aboutClass(currentView === 'about')}
                    >
                        <Info className="w-4 h-4" aria-hidden="true" />
                        <span>{t('nav.about')}</span>
                    </button>
                </div>
            </nav>

            <div className="p-4 border-t border-white/5 space-y-2">
                <button
                    type="button"
                    onClick={() => setView('profile')}
                    className="flex items-center gap-3 p-3 rounded-xl bg-brand-slate/50 border border-white/5 w-full text-left hover:border-brand-purple/30 transition-colors"
                >
                    <div className="w-9 h-9 rounded-full bg-brand-purple/20 flex items-center justify-center border border-brand-purple/30 text-brand-purple font-bold text-xs shrink-0">
                        {username?.[0]?.toUpperCase() ?? '?'}
                    </div>
                    <div className="flex flex-col overflow-hidden flex-1 min-w-0 gap-1">
                        <span className="text-sm font-semibold truncate font-mono">{username ?? '—'}</span>
                        {role ? <span><RoleBadge role={role} /></span> : (
                            <span className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">{t('nav.connectedAs')}</span>
                        )}
                    </div>
                </button>
                <button
                    type="button"
                    onClick={logout}
                    className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-all text-xs font-medium"
                >
                    <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
                    {t('nav.logout')}
                </button>
            </div>
        </aside>
    );
};

export default Sidebar;
