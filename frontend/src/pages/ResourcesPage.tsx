import { useState, useEffect } from 'react';
import { useAppStore } from '../stores/appStore';
import { resourcesApi } from '../services/api';
import type { Resource, EmbeddingStatus } from '../types';

export default function ResourcesPage() {
  const { currentWorkspace } = useAppStore();
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedResource, setSelectedResource] = useState<Resource | null>(null);
  const [embeddingStatus, setEmbeddingStatus] = useState<EmbeddingStatus | null>(null);
  const [filter, setFilter] = useState<'all' | 'complete' | 'pending' | 'error'>('all');

  useEffect(() => {
    if (currentWorkspace) {
      loadResources();
    }
  }, [currentWorkspace]);

  const loadResources = async () => {
    if (!currentWorkspace) return;
    setLoading(true);
    try {
      const data = await resourcesApi.list(currentWorkspace.id, 0, 100);
      setResources(data.resources);
    } catch (error) {
      console.error('Failed to load resources:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadEmbeddingStatus = async (resourceId: string) => {
    try {
      const status = await resourcesApi.getEmbeddingStatus(resourceId);
      setEmbeddingStatus(status);
    } catch (error) {
      console.error('Failed to load embedding status:', error);
    }
  };

  const triggerEmbeddings = async (resourceId: string) => {
    try {
      await resourcesApi.triggerEmbeddings(resourceId);
      loadResources();
      if (selectedResource?.id === resourceId) {
        loadEmbeddingStatus(resourceId);
      }
    } catch (error) {
      console.error('Failed to trigger embeddings:', error);
    }
  };

  const deleteResource = async (resourceId: string) => {
    if (!confirm('Are you sure you want to delete this resource?')) return;
    try {
      await resourcesApi.delete(resourceId);
      setResources(prev => prev.filter(r => r.id !== resourceId));
      if (selectedResource?.id === resourceId) {
        setSelectedResource(null);
      }
    } catch (error) {
      console.error('Failed to delete resource:', error);
    }
  };

  const getFileIcon = (type: string) => {
    switch (type) {
      case 'pdf': return '📄';
      case 'word': return '📝';
      case 'excel': return '📊';
      case 'markdown': return '📑';
      case 'text': return '📃';
      default: return '📁';
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'complete':
        return <span className="bg-green-900/50 text-green-400 px-2 py-1 rounded text-xs">✅ Ready</span>;
      case 'processing':
        return <span className="bg-yellow-900/50 text-yellow-400 px-2 py-1 rounded text-xs">⏳ Processing</span>;
      case 'pending':
        return <span className="bg-blue-900/50 text-blue-400 px-2 py-1 rounded text-xs">🕐 Pending</span>;
      case 'error':
        return <span className="bg-red-900/50 text-red-400 px-2 py-1 rounded text-xs">❌ Error</span>;
      default:
        return <span className="bg-gray-700 text-gray-400 px-2 py-1 rounded text-xs">{status}</span>;
    }
  };

  const filteredResources = resources.filter(r => {
    if (filter === 'all') return true;
    return r.embedding_status === filter;
  });

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return 'N/A';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      {/* Resource List */}
      <div className="flex-1 flex flex-col border-r border-gray-700">
        {/* Header */}
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <h1 className="text-xl font-bold">Resources</h1>
          <div className="flex gap-2">
            {(['all', 'complete', 'pending', 'error'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded text-sm ${
                  filter === f
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                }`}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-8 text-center text-gray-400">Loading...</div>
          ) : filteredResources.length === 0 ? (
            <div className="p-8 text-center">
              <div className="text-5xl mb-4">📚</div>
              <p className="text-gray-400">No resources found</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-700">
              {filteredResources.map((resource) => (
                <div
                  key={resource.id}
                  onClick={() => {
                    setSelectedResource(resource);
                    loadEmbeddingStatus(resource.id);
                  }}
                  className={`p-4 cursor-pointer hover:bg-gray-800 ${
                    selectedResource?.id === resource.id ? 'bg-gray-800' : ''
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{getFileIcon(resource.resource_type)}</span>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium truncate">{resource.title}</h3>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-gray-500">
                          {resource.chunks_count} chunks
                        </span>
                        <span className="text-xs text-gray-500">•</span>
                        <span className="text-xs text-gray-500">
                          {formatDate(resource.created_at)}
                        </span>
                      </div>
                    </div>
                    {getStatusBadge(resource.embedding_status)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="p-4 border-t border-gray-700 bg-gray-800">
          <div className="flex justify-between text-sm text-gray-400">
            <span>{filteredResources.length} resources</span>
            <span>
              {filteredResources.reduce((acc, r) => acc + r.chunks_count, 0)} total chunks
            </span>
          </div>
        </div>
      </div>

      {/* Resource Details */}
      <div className="w-96 bg-gray-800 overflow-y-auto">
        {selectedResource ? (
          <div className="p-6">
            <div className="text-center mb-6">
              <div className="text-5xl mb-3">{getFileIcon(selectedResource.resource_type)}</div>
              <h2 className="text-lg font-bold">{selectedResource.title}</h2>
              <p className="text-sm text-gray-400 mt-1">
                {selectedResource.resource_type.toUpperCase()}
              </p>
            </div>

            {/* Status */}
            <div className="mb-6">
              <h3 className="text-sm font-medium text-gray-400 mb-2">Status</h3>
              {getStatusBadge(selectedResource.embedding_status)}
              
              {embeddingStatus && (
                <div className="mt-3">
                  <div className="flex justify-between text-sm mb-1">
                    <span>Embedding Progress</span>
                    <span>{embeddingStatus.progress_percent.toFixed(0)}%</span>
                  </div>
                  <div className="bg-gray-700 rounded-full h-2">
                    <div
                      className="bg-blue-500 h-2 rounded-full transition-all"
                      style={{ width: `${embeddingStatus.progress_percent}%` }}
                    />
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    {embeddingStatus.chunks_embedded} / {embeddingStatus.chunks_total} chunks
                  </div>
                </div>
              )}
            </div>

            {/* Details */}
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-1">Size</h3>
                <p>{formatSize(selectedResource.file_size)}</p>
              </div>
              
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-1">Chunks</h3>
                <p>{selectedResource.chunks_count}</p>
              </div>
              
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-1">Created</h3>
                <p>{formatDate(selectedResource.created_at)}</p>
              </div>
              
              {selectedResource.tags && selectedResource.tags.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 mb-1">Tags</h3>
                  <div className="flex flex-wrap gap-1">
                    {selectedResource.tags.map((tag, i) => (
                      <span key={i} className="bg-gray-700 px-2 py-1 rounded text-xs">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              
              {selectedResource.notes && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 mb-1">Notes</h3>
                  <p className="text-sm">{selectedResource.notes}</p>
                </div>
              )}

              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-1">Usage</h3>
                <div className="flex gap-4 text-sm">
                  <span>🔍 {selectedResource.query_count} queries</span>
                  <span>📎 {selectedResource.citation_count} citations</span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="mt-6 space-y-2">
              {selectedResource.embedding_status !== 'complete' && 
               selectedResource.embedding_status !== 'processing' && (
                <button
                  onClick={() => triggerEmbeddings(selectedResource.id)}
                  className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg text-sm"
                >
                  Generate Embeddings
                </button>
              )}
              
              <button
                onClick={() => deleteResource(selectedResource.id)}
                className="w-full bg-red-600/20 hover:bg-red-600/30 text-red-400 py-2 rounded-lg text-sm"
              >
                Delete Resource
              </button>
            </div>
          </div>
        ) : (
          <div className="p-6 text-center text-gray-400">
            <div className="text-5xl mb-4">👈</div>
            <p>Select a resource to view details</p>
          </div>
        )}
      </div>
    </div>
  );
}
