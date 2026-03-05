import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import Dashboard from './components/Dashboard';
import LogsExplorer from './components/LogsExplorer';
import Infrastructure from './components/Infrastructure';
import Security from './components/Security';
import Alerts from './components/Alerts';
import Settings from './components/Settings';

const queryClient = new QueryClient();

export type ViewType = 'dashboard' | 'logs' | 'infrastructure' | 'security' | 'alerts' | 'settings';

function App() {
  const [currentView, setCurrentView] = useState<ViewType>('dashboard');

  const renderView = () => {
    switch (currentView) {
      case 'dashboard': return <Dashboard setView={setCurrentView} />;
      case 'logs': return <LogsExplorer setView={setCurrentView} />;
      case 'infrastructure': return <Infrastructure setView={setCurrentView} />;
      case 'security': return <Security setView={setCurrentView} />;
      case 'alerts': return <Alerts setView={setCurrentView} />;
      case 'settings': return <Settings setView={setCurrentView} />;
      default: return <Dashboard setView={setCurrentView} />;
    }
  };

  return (
    <QueryClientProvider client={queryClient}>
      {renderView()}
    </QueryClientProvider>
  );
}

export default App;
