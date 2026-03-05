export interface Metric {
    id: string;
    timestamp: string;
    name: string;
    value: number;
    tags: Record<string, string>;
}

export interface LogEntry {
    id: string;
    timestamp: string;
    level: 'info' | 'warn' | 'error' | 'debug';
    message: string;
    source: string;
}

export interface DashboardData {
    cpuUsage: Metric[];
    memoryUsage: Metric[];
    recentLogs: LogEntry[];
}
