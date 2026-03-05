import React from 'react';
import ReactECharts from 'echarts-for-react';
import * as echarts from 'echarts';
import { useDashboardData } from '../hooks/useMetrics';
import Layout from './Layout';
import type { ViewType } from '../App';
import {
    Activity,
    Terminal,
    Shield,
    Cpu,
    Server
} from 'lucide-react';

interface DashboardProps {
    setView: (view: ViewType) => void;
}

const Dashboard: React.FC<DashboardProps> = ({ setView }) => {
    const { data, isLoading, isError } = useDashboardData();

    if (isLoading) return <div className="p-8">Carregando Telemetria da Infraestrutura...</div>;
    if (isError) return <div className="p-8 text-red-500">Erro na conexão com os agentes Maestro.</div>;

    const chartTheme = {
        color: ['#39FF14', '#7C3AED'],
        backgroundColor: 'transparent',
        textStyle: { color: '#94A3B8' },
        title: { textStyle: { color: '#F1F5F9' } },
    };

    const cpuOption = {
        ...chartTheme,
        tooltip: { trigger: 'axis', backgroundColor: '#1E293B', borderColor: '#7C3AED', textStyle: { color: '#F1F5F9' } },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: {
            type: 'category',
            boundaryGap: false,
            data: data?.cpuUsage.map(m => new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })),
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#1E293B' } } },
        series: [
            {
                name: 'Aggregate Cluster CPU',
                type: 'line',
                smooth: true,
                showSymbol: false,
                data: data?.cpuUsage.map(m => m.value),
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(57, 255, 20, 0.3)' },
                        { offset: 1, color: 'rgba(57, 255, 20, 0)' }
                    ])
                },
                lineStyle: { width: 3, color: '#39FF14' }
            }
        ]
    };

    return (
        <Layout currentView="dashboard" setView={setView} title="Observabilidade Geral">
            <div className="space-y-8">
                {/* Stats Row */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {[
                        { label: 'Servidores Ativos', value: '42', delta: 'Cluster OK', icon: Server, color: 'text-brand-purple' },
                        { label: 'Ingestão de Métricas', value: '1.2M/min', delta: '+5% load', icon: Activity, color: 'text-brand-neon' },
                        { label: 'Incidentes Críticos', value: '0', delta: 'last 24h', icon: Shield, color: 'text-brand-neon' },
                    ].map((stat) => (
                        <div key={stat.label} className="glass-card p-6 border-l-4 border-l-brand-purple/50">
                            <div className="flex justify-between items-start mb-2">
                                <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">{stat.label}</span>
                                <stat.icon className={`w-5 h-5 ${stat.color}`} />
                            </div>
                            <div className="flex items-baseline gap-2">
                                <span className="text-2xl font-bold font-mono">{stat.value}</span>
                                <span className="text-[10px] font-semibold text-brand-neon">{stat.delta}</span>
                            </div>
                        </div>
                    ))}
                </div>

                {/* Charts Row */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <section className="glass-card p-6">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="font-semibold flex items-center gap-2 text-glow-neon">
                                <Cpu className="w-4 h-4 text-brand-neon" />
                                Carga de CPU (Infraestrutura On-Premise)
                            </h3>
                        </div>
                        <div className="h-[300px]">
                            <ReactECharts option={cpuOption} style={{ height: '100%', width: '100%' }} />
                        </div>
                    </section>

                    <section className="glass-card p-6 flex flex-col">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="font-semibold flex items-center gap-2 text-glow-purple">
                                <Terminal className="w-4 h-4 text-brand-purple" />
                                Syslogs em Tempo Real
                            </h3>
                            <button
                                onClick={() => setView('logs')}
                                className="text-[10px] text-slate-500 hover:text-brand-purple transition-colors uppercase tracking-widest font-mono"
                            >
                                Ver Explorer
                            </button>
                        </div>
                        <div className="flex-1 space-y-3 overflow-y-auto max-h-[300px] scrollbar-hide">
                            {[
                                { id: '1', host: 'srv-db-01', msg: 'PostgreSQL: vacuum scale factor reached', time: '17:01:22' },
                                { id: '2', host: 'srv-app-04', msg: 'maestro-agent: successfully pushed 512 samples', time: '17:01:20' },
                                { id: '3', host: 'srv-web-02', msg: 'nginx: 200 GET /api/v1/metrics', time: '17:01:15' },
                                { id: '4', host: 'srv-db-01', msg: 'systemd: Started Daily apt download activities', time: '17:01:10' },
                                { id: '5', host: 'srv-mon-01', msg: 'kernel: [ 124.5] TCP: request_sock_TCP: Possible SYN flood', time: '17:01:05' },
                            ].map((log) => (
                                <div key={log.id} className="p-3 bg-white/5 border border-white/5 rounded-lg hover:border-brand-purple/30 group transition-all">
                                    <div className="flex justify-between items-center mb-1 text-[10px] font-mono">
                                        <span className="text-brand-neon opacity-70 group-hover:opacity-100 font-bold">[{log.host}]</span>
                                        <span className="text-slate-500">{log.time}</span>
                                    </div>
                                    <p className="text-xs font-mono text-slate-300 group-hover:text-slate-100 leading-tight">
                                        {log.msg}
                                    </p>
                                </div>
                            ))}
                        </div>
                    </section>
                </div>
            </div>
        </Layout>
    );
};

export default Dashboard;

