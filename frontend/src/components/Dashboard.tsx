import React from 'react';
import ReactECharts from 'echarts-for-react';
import { useDashboardData } from '../hooks/useMetrics';
import { Activity, Database, AlertCircle } from 'lucide-react';

const Dashboard: React.FC = () => {
    const { data, isLoading, isError } = useDashboardData();

    if (isLoading) return <div className="p-8">Loading Maestro Dashboard...</div>;
    if (isError) return <div className="p-8 text-red-500">Error loading telemetry data.</div>;

    const cpuOption = {
        title: { text: 'CPU Usage (%)' },
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: data?.cpuUsage.map(m => new Date(m.timestamp).toLocaleTimeString()) },
        yAxis: { type: 'value', max: 100 },
        series: [{
            data: data?.cpuUsage.map(m => m.value),
            type: 'line',
            smooth: true,
            areaStyle: { opacity: 0.3 }
        }]
    };

    return (
        <div className="min-h-screen bg-gray-50 p-8">
            <header className="mb-8 flex items-center justify-between">
                <h1 className="text-3xl font-bold text-gray-900">Maestro Dashboard</h1>
                <div className="flex gap-4">
                    <div className="flex items-center gap-2 bg-white px-4 py-2 rounded-lg shadow-sm border border-gray-200">
                        <Activity className="w-5 h-5 text-blue-500" />
                        <span className="font-medium">System Health: Stable</span>
                    </div>
                </div>
            </header>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
                <div className="bg-white p-6 rounded-xl shadow-md border border-gray-100">
                    <ReactECharts option={cpuOption} />
                </div>
                <div className="bg-white p-6 rounded-xl shadow-md border border-gray-100">
                    <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
                        <AlertCircle className="w-5 h-5 text-orange-500" />
                        Recent Logs
                    </h2>
                    <div className="space-y-3">
                        {data?.recentLogs.map(log => (
                            <div key={log.id} className="p-3 bg-gray-50 rounded-md border-l-4 border-l-blue-400">
                                <div className="flex justify-between text-xs text-gray-500 mb-1">
                                    <span>{log.source}</span>
                                    <span>{new Date(log.timestamp).toLocaleTimeString()}</span>
                                </div>
                                <p className="text-sm font-medium">{log.message}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Dashboard;
