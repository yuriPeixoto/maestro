import React from 'react';
import Layout from './Layout';
import type { ViewType } from '../App';
import { ShieldAlert, ShieldCheck, Key, Eye, Lock } from 'lucide-react';

interface SecurityProps {
    setView: (view: ViewType) => void;
}

const Security: React.FC<SecurityProps> = ({ setView }) => {
    const securityEvents = [
        { id: 1, type: 'SSH', action: 'Failed Login', host: 'srv-db-01', result: 'Blocked', user: 'root' },
        { id: 2, type: 'PRIV', action: 'Sudo Execution', host: 'srv-app-04', result: 'Success', user: 'yuripeixoto' },
        { id: 3, type: 'FW', action: 'Port Scan Block', host: 'srv-web-02', result: 'Dropped', user: 'System' },
        { id: 4, type: 'AUTH', action: 'New SSH Key Added', host: 'srv-mon-01', result: 'Success', user: 'admin' },
    ];

    return (
        <Layout currentView="security" setView={setView} title="Segurança da Infraestrutura">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Security Overview */}
                <div className="lg:col-span-2 space-y-6">
                    <div className="glass-card p-6 bg-gradient-to-br from-brand-purple/5 to-transparent">
                        <h2 className="text-lg font-bold mb-6 flex items-center gap-2">
                            <ShieldCheck className="w-5 h-5 text-brand-neon" />
                            Conformidade de End-Host (Carvalima)
                        </h2>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {[
                                { label: 'SSH Hardening', val: 'Active', status: 'OK' },
                                { label: 'SELinux/AppArm', val: 'Enforced', status: 'OK' },
                                { label: 'Package Audits', val: '2 Pending', status: 'Update' },
                                { label: 'Root Logins', val: 'Disabled', status: 'OK' },
                            ].map(s => (
                                <div key={s.label} className="p-3 rounded bg-brand-dark/40 border border-white/5">
                                    <span className="text-[10px] text-slate-500 block uppercase font-bold">{s.label}</span>
                                    <span className="text-sm font-mono text-slate-200">{s.val}</span>
                                    {s.status === 'OK' && <span className="text-[8px] text-brand-neon block mt-1">● COMPLIANT</span>}
                                    {s.status === 'Update' && <span className="text-[8px] text-orange-400 block mt-1">● WARNING</span>}
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="glass-card overflow-hidden">
                        <div className="p-4 border-b border-white/5 bg-white/5 flex items-center justify-between">
                            <h3 className="text-sm font-bold flex items-center gap-2">
                                <Eye className="w-4 h-4 text-brand-purple" />
                                Audit Log (System Access)
                            </h3>
                        </div>
                        <table className="w-full text-left text-sm">
                            <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
                                <tr>
                                    <th className="px-6 py-3 font-medium">Evento</th>
                                    <th className="px-6 py-3 font-medium">Host Destino</th>
                                    <th className="px-6 py-3 font-medium">Status</th>
                                    <th className="px-6 py-3 font-medium">Usuário</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {securityEvents.map(ev => (
                                    <tr key={ev.id} className="hover:bg-white/5 transition-colors group">
                                        <td className="px-6 py-4 flex items-center gap-3">
                                            <Lock className="w-3 h-3 text-brand-purple opacity-50" />
                                            <span className="font-medium">{ev.action}</span>
                                        </td>
                                        <td className="px-6 py-4 font-mono text-xs">{ev.host}</td>
                                        <td className="px-6 py-4">
                                            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${ev.result === 'Success' ? 'bg-brand-neon/10 text-brand-neon border-brand-neon/20' :
                                                    ev.result === 'Blocked' || ev.result === 'Dropped' ? 'bg-red-500/10 text-red-500 border-red-500/20' :
                                                        'bg-brand-purple/10 text-brand-purple border-brand-purple/20'
                                                }`}>
                                                {ev.result}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 text-xs text-slate-400">{ev.user}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Action Center */}
                <div className="space-y-6">
                    <div className="glass-card p-6 border-red-500/20 bg-red-500/5">
                        <div className="flex items-center gap-3 mb-4">
                            <ShieldAlert className="w-6 h-6 text-red-500" />
                            <h3 className="font-bold text-red-500">Alertas de Intrusão</h3>
                        </div>
                        <p className="text-xs text-slate-400 mb-4">Nenhuma tentativa de força bruta detectada nos últimos 60 minutos.</p>
                        <button className="w-full py-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 rounded text-red-500 text-xs font-bold transition-all">
                            Scan de Vulnerabilidade
                        </button>
                    </div>

                    <div className="glass-card p-6">
                        <h3 className="font-bold text-sm mb-4 flex items-center gap-2">
                            <Key className="w-4 h-4 text-brand-purple" />
                            Chave de Acesso Maestro
                        </h3>
                        <div className="bg-brand-dark p-3 rounded border border-white/10 flex items-center justify-between mb-2">
                            <span className="text-xs font-mono text-slate-500">••••••••••••••••••••••••</span>
                            <button className="text-[10px] text-brand-purple font-bold">COPIAR</button>
                        </div>
                        <p className="text-[10px] text-slate-500 italic">Mantenha seu segredo de API seguro.</p>
                    </div>
                </div>
            </div>
        </Layout>
    );
};

export default Security;
