import React from 'react';
import Sidebar from './Sidebar';
import { Search } from 'lucide-react';
import type { ViewType } from '../App';

interface LayoutProps {
    children: React.ReactNode;
    currentView: ViewType;
    setView: (view: ViewType) => void;
    title: string;
}

const Layout: React.FC<LayoutProps> = ({ children, currentView, setView, title }) => {
    return (
        <div className="flex min-h-screen bg-brand-dark text-slate-100 font-sans selection:bg-brand-neon selection:text-brand-dark">
            <Sidebar currentView={currentView} setView={setView} />

            <main className="flex-1 overflow-y-auto">
                <header className="h-16 border-b border-white/5 bg-brand-dark/50 backdrop-blur-md sticky top-0 z-10 px-8 flex items-center justify-between">
                    <div className="flex items-center gap-4 text-sm text-slate-400">
                        <span>Cliente</span>
                        <span className="text-slate-600">/</span>
                        <span className="text-slate-100 font-medium">Client Name</span>
                        <span className="text-slate-600">/</span>
                        <span className="text-slate-100 font-medium opacity-70">{title}</span>
                    </div>
                    <div className="flex items-center gap-6">
                        <div className="relative">
                            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                            <input
                                type="text"
                                placeholder="Pesquisar veículos, logs..."
                                className="bg-brand-slate border border-white/10 rounded-full py-1.5 pl-9 pr-4 text-sm focus:outline-none focus:border-brand-purple/50 w-64 transition-all"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-brand-neon animate-pulse shadow-[0_0_8px_rgba(57,255,20,0.6)]"></div>
                            <span className="text-xs font-mono uppercase tracking-tighter text-brand-neon text-glow-neon">Live Server</span>
                        </div>
                    </div>
                </header>

                <div className="p-8 max-w-7xl mx-auto">
                    {children}
                </div>
            </main>
        </div>
    );
};

export default Layout;
