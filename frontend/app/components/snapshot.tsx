'use client';

import { Camera, Download, ChevronDown, ChevronUp } from 'lucide-react';
import { useState, useEffect } from 'react';

interface SavedPage {
    url: string;
    timestamp: string;
    files: {
        html: string;
        screenshot: string;
        metadata: string;
    };
}

export const Snapshot = () => {
    const [isSaving, setIsSaving] = useState(false);
    const [lastSaveStatus, setLastSaveStatus] = useState<{ success: boolean; message: string } | null>(null);
    const [savedPages, setSavedPages] = useState<SavedPage[]>([]);
    const [showSavedPages, setShowSavedPages] = useState(false);
    const [isLoading, setIsLoading] = useState(false);

    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

    const fetchSavedPages = async () => {
        try {
            setIsLoading(true);
            const response = await fetch(`${API_URL}/list_saved_pages`, {
                credentials: 'include',
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                setSavedPages(data.pages);
            } else {
                console.error('Error fetching saved pages:', data.message);
            }
        } catch (error) {
            console.error('Error fetching saved pages:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const downloadFile = async (filename: string) => {
        try {
            const response = await fetch(`${API_URL}/download_saved_page/${filename}`, {
                credentials: 'include',
            });
            
            if (!response.ok) {
                throw new Error('Download failed');
            }
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Error downloading file:', error);
        }
    };

    const saveSnapshot = async () => {
        setIsSaving(true);
        setLastSaveStatus(null);
        
        try {
            const response = await fetch(`${API_URL}/save_page_info`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    wallet_address: 'placeholder', // TODO: integrate with wagmi
                }),
            });

            if (!response.ok) {
                throw new Error('Failed to save snapshot');
            }

            // Get the filename from the Content-Disposition header
            const contentDisposition = response.headers.get('Content-Disposition');
            const filename = contentDisposition?.split('filename=')[1]?.replace(/"/g, '') || 'snapshot.zip';

            // Create a blob from the response
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);

            // Create a temporary link and trigger download
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            setLastSaveStatus({
                success: true,
                message: 'Snapshot saved successfully!'
            });
        } catch (error) {
            setLastSaveStatus({
                success: false,
                message: error instanceof Error ? error.message : 'Failed to save snapshot'
            });
        } finally {
            setIsSaving(false);
        }
    };

    // Fetch saved pages when the component mounts or when showSavedPages is toggled
    useEffect(() => {
        if (showSavedPages) {
            fetchSavedPages();
        }
    }, [showSavedPages]);

    return (
        <div className="relative">
            <div className="flex items-center gap-2">
                <button
                    onClick={saveSnapshot}
                    disabled={isSaving}
                    className={`flex items-center justify-center p-2 rounded-lg 
                        bg-cyan-900/50 hover:bg-cyan-800/50 
                        border border-cyan-500/50 hover:border-cyan-400
                        transition-all duration-200 ease-in-out
                        ${isSaving ? 'opacity-50 cursor-not-allowed' : ''}
                        text-cyan-300 hover:text-cyan-200`}
                    title="Save page snapshot"
                >
                    <Camera className={`w-5 h-5 ${isSaving ? 'animate-pulse' : ''}`} />
                </button>

                <button
                    onClick={() => setShowSavedPages(!showSavedPages)}
                    className={`flex items-center justify-center p-2 rounded-lg 
                        bg-cyan-900/50 hover:bg-cyan-800/50 
                        border border-cyan-500/50 hover:border-cyan-400
                        transition-all duration-200 ease-in-out
                        text-cyan-300 hover:text-cyan-200`}
                    title={showSavedPages ? "Hide saved pages" : "Show saved pages"}
                >
                    {showSavedPages ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
                </button>
            </div>
            
            {lastSaveStatus && (
                <div className={`absolute top-full mt-2 p-2 rounded-md text-sm whitespace-nowrap
                    ${lastSaveStatus.success ? 'bg-green-900/80 text-green-200' : 'bg-red-900/80 text-red-200'}
                    border ${lastSaveStatus.success ? 'border-green-500/50' : 'border-red-500/50'}`}>
                    {lastSaveStatus.message}
                </div>
            )}

            {showSavedPages && (
                <div className="absolute top-full mt-2 w-96 max-h-96 overflow-y-auto rounded-lg 
                    bg-gray-900/90 border border-cyan-500/30 p-4 space-y-4">
                    <h3 className="text-cyan-300 font-semibold mb-2">Saved Pages</h3>
                    
                    {isLoading ? (
                        <div className="text-cyan-200 text-sm">Loading saved pages...</div>
                    ) : savedPages.length === 0 ? (
                        <div className="text-cyan-200 text-sm">No saved pages found</div>
                    ) : (
                        <div className="space-y-4">
                            {savedPages.map((page, index) => (
                                <div key={index} className="border border-cyan-500/20 rounded p-3 space-y-2">
                                    <div className="text-cyan-200 text-sm truncate">{page.url}</div>
                                    <div className="text-cyan-400/60 text-xs">
                                        {new Date(page.timestamp).toLocaleString()}
                                    </div>
                                    <div className="flex gap-2 mt-2">
                                        {Object.entries(page.files).map(([type, filename]) => (
                                            <button
                                                key={type}
                                                onClick={() => downloadFile(filename)}
                                                className="flex items-center gap-1 px-2 py-1 rounded
                                                    bg-cyan-900/30 hover:bg-cyan-800/30
                                                    border border-cyan-500/30 hover:border-cyan-400/30
                                                    text-cyan-300 text-xs"
                                            >
                                                <Download className="w-3 h-3" />
                                                {type}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
