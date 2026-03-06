import React from 'react';
import {
    Terminal,
    Settings,
    Shield,
    LayoutDashboard,
    Bell,
    Zap,
    Server
} from 'lucide-react';
import type { ViewType } from '../App';

interface SidebarProps {
    currentView: ViewType;
    setView: (view: ViewType) => void;
}

const Sidebar: React.FC<SidebarProps> = ({ currentView, setView }) => {
    const menuItems: { icon: any, label: string, id: ViewType }[] = [
        { icon: LayoutDashboard, label: 'Dashboards', id: 'dashboard' },
        { icon: Terminal, label: 'Syslogs Explorer', id: 'logs' },
        { icon: Server, label: 'Infrastructure', id: 'infrastructure' },
        { icon: Shield, label: 'Security & Auth', id: 'security' },
        { icon: Bell, label: 'Alerts & Incidents', id: 'alerts' },
        { icon: Settings, label: 'Telemetry Config', id: 'settings' },
    ];

    return (
        <aside className="w-64 border-r border-white/5 bg-brand-dark hidden lg:flex flex-col h-screen sticky top-0">
            <div className="p-6 flex items-center gap-3">
                <div className="w-8 h-8 bg-brand-purple rounded-lg flex items-center justify-center shadow-[0_0_15px_rgba(124,58,237,0.4)]">
                    <Zap className="w-5 h-5 text-white fill-current" />
                </div>
                <span className="text-xl font-bold tracking-tight text-glow-purple">Maestro</span>
            </div>

            <nav className="flex-1 px-4 py-4 space-y-1">
                {menuItems.map((item) => (
                    <button
                        key={item.id}
                        onClick={() => setView(item.id)}
                        className={`flex items-center gap-3 w-full px-4 py-2.5 rounded-lg transition-all ${currentView === item.id
                                ? 'bg-brand-purple/10 text-brand-purple border border-brand-purple/20'
                                : 'text-slate-400 hover:text-slate-100 hover:bg-white/5'
                            } `}
                    >
                        <item.icon className="w-4 h-4" />
                        <span className="text-sm font-medium">{item.label}</span>
                    </button>
                ))}
            </nav>

            <div className="p-4 border-t border-white/5">
                <div className="flex items-center gap-3 p-3 rounded-xl bg-brand-slate/50 border border-white/5">
                    <div className="w-10 h-10 rounded-full bg-brand-purple/20 flex items-center justify-center border border-brand-purple/30 text-brand-purple font-bold text-xs">
                        SYS
                    </div>
                    <div className="flex flex-col overflow-hidden">
                        <span className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">Ambiente</span>
                        <span className="text-sm font-semibold truncate">Produção (Default)</span>
                    </div>
                </div>
            </div>
        </aside>
    );
};

export default Sidebar;
