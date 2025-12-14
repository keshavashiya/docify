import { useState, useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useAppStore } from '../stores/appStore';
import { workspacesApi, healthApi } from '../services/api';

const navItems = [
  { path: '/', label: 'Home', icon: '🏠' },
  { path: '/chat', label: 'Chat', icon: '💬' },
  { path: '/upload', label: 'Upload', icon: '📤' },
  { path: '/resources', label: 'Resources', icon: '📚' },
];

export default function Layout() {
  const location = useLocation();
  const { 
    currentWorkspace, 
    workspaces, 
    setWorkspaces, 
    setCurrentWorkspace,
    sidebarOpen,
    toggleSidebar 
  } = useAppStore();
  
  const [apiStatus, setApiStatus] = useState<'checking' | 'online' | 'offline'>('checking');

  useEffect(() => {
    const checkHealth = async () => {
      try {
        await healthApi.check();
        setApiStatus('online');
      } catch {
        setApiStatus('offline');
      }
    };

    const loadWorkspaces = async () => {
      try {
        const data = await workspacesApi.list();
        setWorkspaces(data);
        if (data.length > 0 && !currentWorkspace) {
          setCurrentWorkspace(data[0]);
        }
      } catch (error) {
        console.error('Failed to load workspaces:', error);
      }
    };

    checkHealth();
    loadWorkspaces();

    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [setWorkspaces, setCurrentWorkspace, currentWorkspace]);

  const createDefaultWorkspace = async () => {
    try {
      const workspace = await workspacesApi.create({ name: 'Default', workspace_type: 'personal' });
      setWorkspaces([...workspaces, workspace]);
      setCurrentWorkspace(workspace);
    } catch (error) {
      console.error('Failed to create workspace:', error);
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white flex">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-64' : 'w-16'} bg-gray-800 border-r border-gray-700 flex flex-col transition-all duration-300`}>
        {/* Logo */}
        <div className="h-16 flex items-center px-4 border-b border-gray-700">
          {sidebarOpen ? (
            <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">
              Docify
            </h1>
          ) : (
            <span className="text-2xl">📚</span>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-2">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg mb-1 transition-colors ${
                location.pathname === item.path
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-700 hover:text-white'
              }`}
            >
              <span className="text-lg">{item.icon}</span>
              {sidebarOpen && <span>{item.label}</span>}
            </Link>
          ))}
        </nav>

        {/* Workspace Selector */}
        {sidebarOpen && (
          <div className="p-4 border-t border-gray-700">
            <label className="text-xs text-gray-500 uppercase tracking-wider">Workspace</label>
            {workspaces.length === 0 ? (
              <button
                onClick={createDefaultWorkspace}
                className="mt-2 w-full bg-blue-600 hover:bg-blue-700 text-white text-sm py-2 px-3 rounded-lg"
              >
                Create Workspace
              </button>
            ) : (
              <select
                value={currentWorkspace?.id || ''}
                onChange={(e) => {
                  const ws = workspaces.find(w => w.id === e.target.value);
                  setCurrentWorkspace(ws || null);
                }}
                className="mt-2 w-full bg-gray-700 text-white text-sm py-2 px-3 rounded-lg border border-gray-600"
              >
                {workspaces.map((ws) => (
                  <option key={ws.id} value={ws.id}>{ws.name}</option>
                ))}
              </select>
            )}
          </div>
        )}

        {/* Toggle Button */}
        <button
          onClick={toggleSidebar}
          className="p-4 border-t border-gray-700 text-gray-400 hover:text-white"
        >
          {sidebarOpen ? '◀' : '▶'}
        </button>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="h-16 bg-gray-800 border-b border-gray-700 flex items-center justify-between px-6">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold">
              {navItems.find(item => item.path === location.pathname)?.label || 'Docify'}
            </h2>
          </div>

          {/* Status */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${
                apiStatus === 'online' ? 'bg-green-500' :
                apiStatus === 'offline' ? 'bg-red-500' : 'bg-yellow-500'
              }`} />
              <span className="text-xs text-gray-400">
                API {apiStatus}
              </span>
            </div>
            {currentWorkspace && (
              <span className="text-xs text-gray-500 bg-gray-700 px-2 py-1 rounded">
                {currentWorkspace.name}
              </span>
            )}
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-auto">
          {apiStatus === 'offline' ? (
            <div className="p-6">
              <div className="bg-red-900/20 border border-red-700 rounded-lg p-4">
                <h3 className="text-red-400 font-semibold mb-2">⚠️ Backend Offline</h3>
                <p className="text-gray-400 text-sm">
                  Cannot connect to the backend API. Make sure Docker services are running:
                </p>
                <code className="block mt-2 bg-gray-800 text-green-400 p-2 rounded text-sm">
                  docker-compose up -d
                </code>
              </div>
            </div>
          ) : !currentWorkspace && workspaces.length === 0 ? (
            <div className="p-6">
              <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg p-4">
                <h3 className="text-yellow-400 font-semibold mb-2">No Workspace</h3>
                <p className="text-gray-400 text-sm mb-4">
                  Create a workspace to get started.
                </p>
                <button
                  onClick={createDefaultWorkspace}
                  className="bg-blue-600 hover:bg-blue-700 text-white py-2 px-4 rounded-lg text-sm"
                >
                  Create Default Workspace
                </button>
              </div>
            </div>
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}
