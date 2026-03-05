import { useQuery } from '@tanstack/react-query';
import type { DashboardData } from '../types/metrics';

// Simulated API call
const fetchDashboardData = async (): Promise<DashboardData> => {
    // In a real app, this would be an axios/fetch call to /api
    return new Promise((resolve) => {
        setTimeout(() => {
            const now = new Date();
            resolve({
                cpuUsage: Array.from({ length: 10 }).map((_, i) => ({
                    id: `cpu-${i}`,
                    timestamp: new Date(now.getTime() - (9 - i) * 60000).toISOString(),
                    name: 'cpu_usage',
                    value: Math.random() * 100,
                    tags: { core: 'all' }
                })),
                memoryUsage: Array.from({ length: 10 }).map((_, i) => ({
                    id: `mem-${i}`,
                    timestamp: new Date(now.getTime() - (9 - i) * 60000).toISOString(),
                    name: 'memory_usage',
                    value: 40 + Math.random() * 20,
                    tags: { type: 'used' }
                })),
                recentLogs: [
                    { id: '1', timestamp: now.toISOString(), level: 'info', message: 'Agent connected', source: 'agent-01' },
                    { id: '2', timestamp: now.toISOString(), level: 'warn', message: 'High CPU usage detected', source: 'agent-02' }
                ]
            });
        }, 500);
    });
};

export const useDashboardData = () => {
    return useQuery({
        queryKey: ['dashboardData'],
        queryFn: fetchDashboardData,
        refetchInterval: 5000,
    });
};
