import React, { useState } from 'react';
import Layout from './Layout';
import type { ViewType } from '../App';
import { Search, Filter, Download, Terminal } from 'lucide-react';

interface LogsExplorerProps {
    setView: (view: ViewType) => void;
}

const LogsExplorer: React.FC<LogsExplorerProps> = ({ setView }) => {
    const [filter, setFilter] = useState('');

    const mockLogs = [
        { id: 1, time: '17:01:22', host: 'srv-db-01', service: 'postgresql', level: 'INFO', message: 'checkpoint complete: wrote 43 buffers (0.1%); LSN=0/19A2B40' },
        { id: 2, time: '17:01:21', host: 'srv-app-04', service: 'maestro', level: 'INFO', message: 'successfully pushed 1024 metric samples to aggregator' },
        { id: 3, time: '17:01:19', host: 'srv-web-02', service: 'nginx', level: 'WARN', message: '404 GET /wp-login.php from 192.168.1.45' },
        { id: 4, time: '17:01:15', host: 'srv-auth-01', service: 'sshd', level: 'CRIT', message: 'Failed password for invalid user admin from 203.0.113.1 port 54322 ssh2' },
        { id: 5, time: '17:01:10', host: 'srv-mon-01', service: 'kernel', level: 'WARN', message: '[ 842.1] TCP: request_sock_TCP: Possible SYN flood on port 80' },
        { id: 6, time: '17:00:55', host: 'srv-db-01', service: 'systemd', level: 'INFO', message: 'Started Daily rotation of log files.' },
    ];

    return (
        <Layout currentView="logs" setView={setView} title="Explorer de Syslogs">
            <div className="glass-card flex flex-col h-[700px]">
                {/* Toolbar */}
                <div className="p-4 border-b border-white/5 flex items-center justify-between bg-brand-dark/20">
                    <div className="flex items-center gap-4 flex-1">
                        <div className="relative w-96">
                            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                            <input
                                type="text"
                                placeholder="Filtrar por Host, Serviço ou Mensagem..."
                                className="w-full bg-brand-dark border border-white/10 rounded px-9 py-1.5 text-sm focus:outline-none focus:border-brand-purple/50"
                                value={filter}
                                onChange={(e) => setFilter(e.target.value)}
                            />
                        </div>
                        <button className="flex items-center gap-2 bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded border border-white/10 transition-all">
                            <Filter className="w-4 h-4 text-brand-purple" />
                            <span className="text-xs">Filtros Avançados</span>
                        </button>
                    </div>
                    <button className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors">
                        <Download className="w-4 h-4" />
                        <span className="text-xs">Exportar Logs (.log)</span>
                    </button>
                </div>

                {/* Console Log Area */}
                <div className="flex-1 overflow-y-auto p-4 font-mono text-sm bg-black/20">
                    <div className="space-y-1">
                        {mockLogs.map(log => (
                            <div key={log.id} className="group flex gap-4 py-1 hover:bg-white/5 rounded px-2 transition-all cursor-default">
                                <span className="text-slate-600 shrink-0">[{log.time}]</span>
                                <span className={`shrink-0 w-12 font-bold ${log.level === 'CRIT' ? 'text-red-500' : log.level === 'WARN' ? 'text-orange-400' : 'text-blue-400'
                                    }`}>{log.level}</span>
                                <span className="text-brand-purple shrink-0 font-bold">{log.host}</span>
                                <span className="text-brand-neon shrink-0 tracking-tighter opacity-80">&lt;{log.service}&gt;</span>
                                <span className="text-slate-300 truncate group-hover:text-white transition-colors">{log.message}</span>
                            </div>
                        ))}
                        <div className="py-2 border-t border-white/5 mt-4 flex items-center gap-3">
                            <Terminal className="w-4 h-4 text-brand-neon animate-pulse" />
                            <span className="text-brand-neon text-xs animate-pulse tracking-widest uppercase">Escutando logs da infraestrutura Carvalima...</span>
                        </div>
                    </div>
                </div>
            </div>
        </Layout>
    );
};

export default LogsExplorer;
