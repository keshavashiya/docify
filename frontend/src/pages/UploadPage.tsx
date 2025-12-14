import { useState, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';
import { resourcesApi } from '../services/api';
import type { Resource } from '../types';

interface UploadState {
  file: File | null;
  uploading: boolean;
  progress: number;
  error: string | null;
  result: Resource | null;
}

export default function UploadPage() {
  const { currentWorkspace } = useAppStore();
  const [uploadState, setUploadState] = useState<UploadState>({
    file: null,
    uploading: false,
    progress: 0,
    error: null,
    result: null,
  });
  const [tags, setTags] = useState('');
  const [notes, setNotes] = useState('');
  const [recentUploads, setRecentUploads] = useState<Resource[]>([]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) {
      setUploadState(prev => ({ ...prev, file, error: null, result: null }));
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setUploadState(prev => ({ ...prev, file, error: null, result: null }));
    }
  };

  const handleUpload = async () => {
    if (!uploadState.file || !currentWorkspace) return;

    setUploadState(prev => ({ ...prev, uploading: true, progress: 0, error: null }));

    try {
      const tagsList = tags.split(',').map(t => t.trim()).filter(Boolean);
      
      const result = await resourcesApi.upload(
        uploadState.file,
        currentWorkspace.id,
        tagsList.length > 0 ? tagsList : undefined,
        notes || undefined
      );

      setUploadState(prev => ({ 
        ...prev, 
        uploading: false, 
        progress: 100, 
        result,
        file: null 
      }));
      
      setRecentUploads(prev => [result, ...prev.slice(0, 4)]);
      setTags('');
      setNotes('');

    } catch (error) {
      setUploadState(prev => ({ 
        ...prev, 
        uploading: false, 
        error: error instanceof Error ? error.message : 'Upload failed' 
      }));
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

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'complete': return 'text-green-400';
      case 'processing': return 'text-yellow-400';
      case 'pending': return 'text-blue-400';
      case 'error': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Upload Documents</h1>

      {/* Drop Zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
          uploadState.file 
            ? 'border-blue-500 bg-blue-500/10' 
            : 'border-gray-600 hover:border-gray-500'
        }`}
      >
        {uploadState.file ? (
          <div>
            <div className="text-5xl mb-4">📄</div>
            <p className="text-lg font-medium">{uploadState.file.name}</p>
            <p className="text-sm text-gray-400">
              {(uploadState.file.size / 1024 / 1024).toFixed(2)} MB
            </p>
            <button
              onClick={() => setUploadState(prev => ({ ...prev, file: null }))}
              className="mt-4 text-sm text-red-400 hover:text-red-300"
            >
              Remove
            </button>
          </div>
        ) : (
          <div>
            <div className="text-5xl mb-4">📤</div>
            <p className="text-lg mb-2">Drag and drop a file here</p>
            <p className="text-sm text-gray-400 mb-4">
              Supports: PDF, Word (.docx), Excel (.xlsx), Markdown (.md), Text (.txt)
            </p>
            <label className="cursor-pointer">
              <span className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded-lg">
                Browse Files
              </span>
              <input
                type="file"
                onChange={handleFileSelect}
                accept=".pdf,.docx,.xlsx,.md,.txt"
                className="hidden"
              />
            </label>
          </div>
        )}
      </div>

      {/* Options */}
      {uploadState.file && (
        <div className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Tags (comma-separated)</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="research, ai, machine-learning"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium mb-2">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add any notes about this document..."
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
            />
          </div>

          <button
            onClick={handleUpload}
            disabled={uploadState.uploading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white py-3 rounded-lg font-semibold transition-colors"
          >
            {uploadState.uploading ? 'Uploading...' : 'Upload Document'}
          </button>
        </div>
      )}

      {/* Error */}
      {uploadState.error && (
        <div className="mt-4 bg-red-900/20 border border-red-700 rounded-lg p-4">
          <p className="text-red-400">{uploadState.error}</p>
        </div>
      )}

      {/* Success */}
      {uploadState.result && (
        <div className="mt-4 bg-green-900/20 border border-green-700 rounded-lg p-4">
          <h3 className="text-green-400 font-semibold mb-2">✅ Upload Successful!</h3>
          <p className="text-gray-300">{uploadState.result.title}</p>
          <div className="mt-2 flex gap-4 text-sm text-gray-400">
            <span>{uploadState.result.chunks_count} chunks</span>
            <span className={getStatusColor(uploadState.result.embedding_status)}>
              Embeddings: {uploadState.result.embedding_status}
            </span>
          </div>
        </div>
      )}

      {/* Recent Uploads */}
      {recentUploads.length > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold mb-4">Recent Uploads</h2>
          <div className="space-y-2">
            {recentUploads.map((resource) => (
              <div
                key={resource.id}
                className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{getFileIcon(resource.resource_type)}</span>
                  <div>
                    <p className="font-medium">{resource.title}</p>
                    <p className="text-sm text-gray-400">
                      {resource.chunks_count} chunks
                    </p>
                  </div>
                </div>
                <div className={`text-sm ${getStatusColor(resource.embedding_status)}`}>
                  {resource.embedding_status === 'complete' ? '✅ Ready' : 
                   resource.embedding_status === 'processing' ? '⏳ Processing' :
                   resource.embedding_status === 'pending' ? '🕐 Pending' : '❌ Error'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Help */}
      <div className="mt-8 bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="font-semibold mb-4">📋 Supported Formats</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
          <div className="text-center">
            <div className="text-2xl mb-1">📄</div>
            <div>PDF</div>
          </div>
          <div className="text-center">
            <div className="text-2xl mb-1">📝</div>
            <div>Word (.docx)</div>
          </div>
          <div className="text-center">
            <div className="text-2xl mb-1">📊</div>
            <div>Excel (.xlsx)</div>
          </div>
          <div className="text-center">
            <div className="text-2xl mb-1">📑</div>
            <div>Markdown</div>
          </div>
          <div className="text-center">
            <div className="text-2xl mb-1">📃</div>
            <div>Text (.txt)</div>
          </div>
        </div>
      </div>
    </div>
  );
}
