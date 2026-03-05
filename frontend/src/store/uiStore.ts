import { create } from 'zustand';

interface UIState {
    isSidebarOpen: boolean;
    toggleSidebar: () => void;
    selectedAgentId: string | null;
    setSelectedAgentId: (id: string | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
    isSidebarOpen: true,
    toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
    selectedAgentId: null,
    setSelectedAgentId: (id) => set({ selectedAgentId: id }),
}));
