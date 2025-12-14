import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAppStore } from '../stores/appStore';
import { resourcesApi, conversationsApi } from '../services/api';
import type { EmbeddingStats } from '../types';

export default function HomePage() {
  const { currentWorkspace } = useAppStore();
  const [stats, setStats] = useState<{
    resources: number;
    conversations: number;
    embeddings: EmbeddingStats | null;
  }>({
    resources: 0,
    conversations: 0,
    embeddings: null,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadStats = async () => {
      if (!currentWorkspace) return;
      
      try {
        const [resourcesData, conversationsData, embeddingsData] = await Promise.all([
          resourcesApi.list(currentWorkspace.id, 0, 1),
          conversationsApi.list(currentWorkspace.id, 0, 1),
          resourcesApi.getEmbeddingStats(),
        ]);

        setStats({
          resources: resourcesData.total,
          conversations: conversationsData.length,
          embeddings: embeddingsData,
        });
      } catch (error) {
        console.error('Failed to load stats:', error);
      } finally {
        setLoading(false);
      }
    };

    loadStats();
  }, [currentWorkspace]);

  return (
    <div className="p-6">
      {/* Welcome Section */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">
          Welcome to Docify
        </h1>
        <p className="text-gray-400">
          Your local-first AI second brain for deep research
        </p>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-3xl font-bold text-blue-400">
            {loading ? '...' : stats.resources}
          </div>
          <div className="text-sm text-gray-400">Resources</div>
        </div>
        
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-3xl font-bold text-green-400">
            {loading ? '...' : stats.embeddings?.chunks_embedded || 0}
          </div>
          <div className="text-sm text-gray-400">Chunks Embedded</div>
        </div>
        
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-3xl font-bold text-purple-400">
            {loading ? '...' : stats.conversations}
          </div>
          <div className="text-sm text-gray-400">Conversations</div>
        </div>
        
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-3xl font-bold text-yellow-400">
            {loading ? '...' : (stats.embeddings?.complete || 0)}
          </div>
          <div className="text-sm text-gray-400">Ready to Search</div>
        </div>
      </div>

      {/* Embedding Status */}
      {stats.embeddings && stats.embeddings.chunks_pending > 0 && (
        <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg p-4 mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-yellow-400 font-semibold">Embeddings Processing</h3>
              <p className="text-gray-400 text-sm">
                {stats.embeddings.chunks_pending} chunks pending processing
              </p>
            </div>
            <div className="text-right">
              <div className="text-2xl font-bold text-yellow-400">
                {Math.round((stats.embeddings.chunks_embedded / stats.embeddings.chunks_total) * 100)}%
              </div>
              <div className="text-xs text-gray-500">Complete</div>
            </div>
          </div>
          <div className="mt-3 bg-gray-700 rounded-full h-2">
            <div 
              className="bg-yellow-500 h-2 rounded-full transition-all"
              style={{ 
                width: `${(stats.embeddings.chunks_embedded / stats.embeddings.chunks_total) * 100}%` 
              }}
            />
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <Link
          to="/upload"
          className="bg-gray-800 rounded-lg p-6 border border-gray-700 hover:border-blue-500 transition-colors group"
        >
          <div className="text-4xl mb-4">📤</div>
          <h3 className="text-lg font-semibold mb-2 group-hover:text-blue-400">Upload Documents</h3>
          <p className="text-gray-400 text-sm">
            Add PDFs, Word docs, Excel files, or Markdown to your knowledge base
          </p>
        </Link>

        <Link
          to="/chat"
          className="bg-gray-800 rounded-lg p-6 border border-gray-700 hover:border-green-500 transition-colors group"
        >
          <div className="text-4xl mb-4">💬</div>
          <h3 className="text-lg font-semibold mb-2 group-hover:text-green-400">Start Chatting</h3>
          <p className="text-gray-400 text-sm">
            Ask questions and get cited answers from your documents
          </p>
        </Link>

        <Link
          to="/resources"
          className="bg-gray-800 rounded-lg p-6 border border-gray-700 hover:border-purple-500 transition-colors group"
        >
          <div className="text-4xl mb-4">📚</div>
          <h3 className="text-lg font-semibold mb-2 group-hover:text-purple-400">Browse Resources</h3>
          <p className="text-gray-400 text-sm">
            View and manage all your uploaded documents
          </p>
        </Link>
      </div>

      {/* Features */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="text-lg font-semibold mb-4">How It Works</h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="w-12 h-12 bg-blue-600 rounded-full flex items-center justify-center mx-auto mb-2">
              <span className="text-xl">1</span>
            </div>
            <h4 className="font-medium mb-1">Upload</h4>
            <p className="text-xs text-gray-400">Add your documents</p>
          </div>
          <div className="text-center">
            <div className="w-12 h-12 bg-blue-600 rounded-full flex items-center justify-center mx-auto mb-2">
              <span className="text-xl">2</span>
            </div>
            <h4 className="font-medium mb-1">Process</h4>
            <p className="text-xs text-gray-400">AI creates embeddings</p>
          </div>
          <div className="text-center">
            <div className="w-12 h-12 bg-blue-600 rounded-full flex items-center justify-center mx-auto mb-2">
              <span className="text-xl">3</span>
            </div>
            <h4 className="font-medium mb-1">Ask</h4>
            <p className="text-xs text-gray-400">Query your knowledge</p>
          </div>
          <div className="text-center">
            <div className="w-12 h-12 bg-blue-600 rounded-full flex items-center justify-center mx-auto mb-2">
              <span className="text-xl">4</span>
            </div>
            <h4 className="font-medium mb-1">Get Answers</h4>
            <p className="text-xs text-gray-400">Cited & verified</p>
          </div>
        </div>
      </div>
    </div>
  );
}
