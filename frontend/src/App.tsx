import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import Dashboard from './components/Dashboard'
import LogsExplorer from './components/LogsExplorer'
import Infrastructure from './components/Infrastructure'
import Security from './components/Security'
import Alerts from './components/Alerts'
import ServerDashboard from './components/ServerDashboard'
import Login from './components/Login'
import { useUIStore } from './store/uiStore'
import { useAuthStore } from './store/authStore'

const queryClient = new QueryClient()

export type ViewType = 'dashboard' | 'logs' | 'infrastructure' | 'server' | 'security' | 'alerts'

function AppInner() {
  const [currentView, setCurrentView] = useState<ViewType>('dashboard')
  const selectedAgentId = useUIStore((s) => s.selectedAgentId)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  if (!isAuthenticated) return <Login />

  const renderView = () => {
    switch (currentView) {
      case 'dashboard':      return <Dashboard setView={setCurrentView} />
      case 'logs':           return <LogsExplorer setView={setCurrentView} />
      case 'infrastructure': return <Infrastructure setView={setCurrentView} />
      case 'server':         return selectedAgentId
                               ? <ServerDashboard serverId={selectedAgentId} setView={setCurrentView} />
                               : <Infrastructure setView={setCurrentView} />
      case 'security':       return <Security setView={setCurrentView} />
      case 'alerts':         return <Alerts setView={setCurrentView} />
      default:               return <Dashboard setView={setCurrentView} />
    }
  }

  return <>{renderView()}</>
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppInner />
    </QueryClientProvider>
  )
}

export default App
