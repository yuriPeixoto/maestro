import React from 'react';
import Layout from './Layout';
import type { ViewType } from '../App';
import { Server, Activity, Monitor, Network } from 'lucide-react';

interface InfrastructureProps {
    setView: (view: ViewType) => void;
}

const Infrastructure: React.FC<InfrastructureProps> = ({ setView }) => {
    const nodes = [
        { id: 'SRV-DB-PROD-01', role: 'Database Master', load: 82, ram: 74, status: 'online', ip: '10.0.0.10' },
        { id: 'SRV-APP-PROD-01', role: 'Application API', load: 45, ram: 58, status: 'online', ip: '10.0.0.21' },
        { id: 'SRV-WEB-PROD-01', role: 'Nginx Load Balancer', load: 12, ram: 22, status: 'online', ip: '10.0.0.5' },
        { id: 'SRV-MON-LOCAL-01', role: 'Maestro Aggregator', load: 92, ram: 88, status: 'warning', ip: '10.0.0.100' },
    ];

    return (
        <Layout currentView="infrastructure" setView={setView} title="Mapa de Servidores">
            <div className="space-y-4 mb-8">
                <h2 className="text-xl font-bold flex items-center gap-2">
                    <Network className="w-5 h-5 text-brand-purple" />
                    Topologia On-Premise (Cluster Carvalima)
                </h2>
                <p className="text-slate-400 text-sm">Status detalhado dos recursos de hardware por host monitorado.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {nodes.map(node => (
                    <div key={node.id} className="glass-card p-5 relative overflow-hidden group">
                        <div className={`absolute top-0 right-0 w-1 h-full ${node.status === 'online' ? 'bg-brand-neon shadow-[0_0_10px_rgba(57,255,20,0.5)]' : 'bg-orange-500 ripple-orange'
                            }`}></div>

                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 bg-brand-slate rounded-lg">
                                <Server className="w-4 h-4 text-brand-purple" />
                            </div>
                            <div>
                                <h3 className="text-sm font-bold font-mono tracking-tight">{node.id}</h3>
                                <span className="text-[10px] text-slate-500 uppercase">{node.role}</span>
                            </div>
                        </div>

                        <div className="space-y-4">
                            <div className="space-y-1">
                                <div className="flex justify-between text-[10px]">
                                    <span className="text-slate-400 uppercase font-bold">CPU Load</span>
                                    <span className={`font-mono ${node.load > 90 ? 'text-red-400' : 'text-brand-neon'}`}>{node.load}%</span>
                                </div>
                                <div className="h-1 w-full bg-slate-700/50 rounded-full overflow-hidden">
                                    <div
                                        className={`h-full transition-all duration-1000 ${node.load > 90 ? 'bg-red-500' : 'bg-brand-neon'}`}
                                        style={{ width: `${node.load}%` }}
                                    ></div>
                                </div>
                            </div>

                            <div className="space-y-1">
                                <div className="flex justify-between text-[10px]">
                                    <span className="text-slate-400 uppercase font-bold">RAM Usage</span>
                                    <span className="font-mono text-brand-purple">{node.ram}%</span>
                                </div>
                                <div className="h-1 w-full bg-slate-700/50 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-brand-purple transition-all duration-1000"
                                        style={{ width: `${node.ram}%` }}
                                    ></div>
                                </div>
                            </div>
                        </div>

                        <div className="mt-6 pt-4 border-t border-white/5 flex justify-between items-center opacity-70 group-hover:opacity-100 transition-opacity font-mono text-[9px]">
                            <div className="flex items-center gap-1.5">
                                <Activity className="w-3 h-3 text-slate-500" />
                                <span>Uptime: 12d 4h</span>
                            </div>
                            <span className="text-slate-500">{node.ip}</span>
                        </div>
                    </div>
                ))}
            </div>

            <div className="mt-12 glass-card p-8 flex items-center justify-center border-dashed border-2">
                <div className="text-center space-y-2">
                    <Monitor className="w-12 h-12 text-slate-700 mx-auto" />
                    <p className="text-slate-500 text-sm italic">Visualização de Rack 3D em desenvolvimento...</p>
                </div>
            </div>
        </Layout>
    );
};

export default Infrastructure;
