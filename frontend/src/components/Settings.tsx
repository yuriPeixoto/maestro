import React from 'react';
import Layout from './Layout';
import type { ViewType } from '../App';
import { User, Bell, Database, Box, Sliders } from 'lucide-react';

interface SettingsProps {
    setView: (view: ViewType) => void;
}

const Settings: React.FC<SettingsProps> = ({ setView }) => {
    return (
        <Layout currentView="settings" setView={setView} title="Configurações do Projeto">
            <div className="max-w-4xl space-y-8">
                <section className="glass-card p-6">
                    <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 mb-6 flex items-center gap-2">
                        <User className="w-4 h-4 text-brand-purple" />
                        Configuração do Cliente
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div className="space-y-1">
                            <label className="text-xs text-slate-400 font-mono">Nome da Empresa</label>
                            <input
                                type="text"
                                defaultValue="Gestão Frota Carvalima"
                                className="w-full bg-brand-dark border border-white/10 rounded px-4 py-2 text-sm focus:border-brand-purple/50 outline-none"
                            />
                        </div>
                        <div className="space-y-1">
                            <label className="text-xs text-slate-400 font-mono">Identificador Fiscal (CNPJ)</label>
                            <input
                                type="text"
                                defaultValue="00.000.000/0001-00"
                                className="w-full bg-brand-dark border border-white/10 rounded px-4 py-2 text-sm focus:border-brand-purple/50 outline-none"
                            />
                        </div>
                    </div>
                </section>

                <section className="glass-card p-6">
                    <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 mb-6 flex items-center gap-2">
                        <Sliders className="w-4 h-4 text-brand-neon" />
                        Parâmetros de Telemetria (In-Transit)
                    </h3>
                    <div className="space-y-4">
                        <div className="flex items-center justify-between p-3 rounded bg-white/5 border border-white/5">
                            <div>
                                <h4 className="text-sm font-bold">Frequência de Batching</h4>
                                <p className="text-[10px] text-slate-500">Intervalo de envio de métricas dos agentes em campo.</p>
                            </div>
                            <select className="bg-brand-dark border border-white/10 text-xs rounded px-2 py-1 outline-none">
                                <option>60 segundos</option>
                                <option selected>30 segundos</option>
                                <option>10 segundos (Debug)</option>
                            </select>
                        </div>

                        <div className="flex items-center justify-between p-3 rounded bg-white/5 border border-white/5 opacity-50">
                            <div>
                                <h4 className="text-sm font-bold">Compressão LZ4</h4>
                                <p className="text-[10px] text-slate-500">Reduzir consumo de dados via rede móvel (4G/SAT).</p>
                            </div>
                            <div className="w-10 h-5 bg-brand-purple rounded-full relative cursor-pointer">
                                <div className="absolute right-1 top-1 w-3 h-3 bg-white rounded-full"></div>
                            </div>
                        </div>
                    </div>
                </section>

                <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {[
                        { label: 'Notificações', icon: Bell, desc: 'E-mail / Webhook' },
                        { label: 'Storage Retention', icon: Database, desc: 'Histórico 90 dias' },
                        { label: 'Integrations', icon: Box, desc: 'SAP / TMS Connect' },
                    ].map(opt => (
                        <button key={opt.label} className="glass-card p-6 text-center hover:bg-white/5 transition-all">
                            <opt.icon className="w-6 h-6 text-brand-purple mx-auto mb-3" />
                            <h4 className="text-sm font-bold truncate">{opt.label}</h4>
                            <p className="text-[10px] text-slate-500">{opt.desc}</p>
                        </button>
                    ))}
                </section>

                <div className="flex justify-end gap-4 border-t border-white/5 pt-8">
                    <button className="px-6 py-2 text-sm text-slate-400 font-bold hover:text-white">Cancelar</button>
                    <button className="px-6 py-2 text-sm bg-brand-purple rounded font-bold shadow-[0_0_15px_rgba(124,58,237,0.3)] hover:brightness-110 transition-all text-white">Salvar Alterações</button>
                </div>
            </div>
        </Layout>
    );
};

export default Settings;
