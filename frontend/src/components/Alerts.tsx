import React from 'react';
import Layout from './Layout';
import type { ViewType } from '../App';
import { AlertTriangle, Info, CheckCircle, Clock } from 'lucide-react';

interface AlertsProps {
    setView: (view: ViewType) => void;
}

const Alerts: React.FC<AlertsProps> = ({ setView }) => {
    const alerts = [
        { id: 1, type: 'CRIT', title: 'Mount Point Usage > 95%', desc: '/var/lib/postgresql no srv-db-01 está quase cheio.', time: 'Ago 12', color: 'text-red-500', bg: 'bg-red-500/10' },
        { id: 2, type: 'WARN', title: 'High Load Average', desc: 'srv-mon-01 reportando carga de 12.4 no último minuto.', time: 'Ago 2h', color: 'text-orange-400', bg: 'bg-orange-400/10' },
        { id: 3, type: 'INFO', title: 'Agente Atualizado', desc: 'Maestro-Agent v2.4.1 implantado com sucesso em 12 hosts.', time: 'Ago 5h', color: 'text-brand-purple', bg: 'bg-brand-purple/10' },
        { id: 4, type: 'SUCC', title: 'Backup Diário Concluído', desc: 'Snapshot da infraestrutura Carvalima armazenado no S3.', time: 'Ontem', color: 'text-brand-neon', bg: 'bg-brand-neon/10' },
    ];

    return (
        <Layout currentView="alerts" setView={setView} title="Central de Incidentes">
            <div className="max-w-3xl mx-auto space-y-4">
                <div className="flex justify-between items-center mb-8">
                    <div>
                        <h2 className="text-xl font-bold">Notificações do Sistema</h2>
                        <p className="text-xs text-slate-500 font-medium">Monitoramento de Infraestrutura &bull; Gestão Frota Carvalima</p>
                    </div>
                    <button className="text-xs text-brand-purple bg-brand-purple/10 border border-brand-purple/20 px-3 py-1.5 rounded hover:bg-brand-purple/20 transition-all">
                        Marcar tudo como lido
                    </button>
                </div>

                {alerts.map(alert => (
                    <div key={alert.id} className="glass-card p-5 group flex gap-5 hover:border-brand-purple/30 transition-all cursor-pointer">
                        <div className={`shrink-0 w-12 h-12 rounded-xl flex items-center justify-center ${alert.bg} border border-white/5`}>
                            {alert.type === 'CRIT' && <AlertTriangle className={`w-6 h-6 ${alert.color}`} />}
                            {alert.type === 'WARN' && <AlertTriangle className={`w-6 h-6 ${alert.color}`} />}
                            {alert.type === 'INFO' && <Info className={`w-6 h-6 ${alert.color}`} />}
                            {alert.type === 'SUCC' && <CheckCircle className={`w-6 h-6 ${alert.color}`} />}
                        </div>
                        <div className="flex-1">
                            <div className="flex justify-between items-start mb-1">
                                <h4 className="font-bold text-sm text-slate-200 group-hover:text-white">{alert.title}</h4>
                                <div className="flex items-center gap-1 text-[10px] text-slate-500 font-mono">
                                    <Clock className="w-3 h-3" />
                                    <span>{alert.time}</span>
                                </div>
                            </div>
                            <p className="text-xs text-slate-400 leading-relaxed">{alert.desc}</p>
                            <div className="mt-3 flex gap-2">
                                <button className="text-[10px] font-bold text-brand-purple hover:underline">Investigar</button>
                                <span className="text-slate-700">|</span>
                                <button className="text-[10px] font-bold text-slate-500 hover:text-slate-300">Silenciar</button>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </Layout>
    );
};

export default Alerts;
