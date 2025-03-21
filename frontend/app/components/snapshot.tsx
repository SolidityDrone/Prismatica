'use client';

import { Camera } from 'lucide-react';
import { useState } from 'react';

export const Snapshot = () => {
    const [isSaving, setIsSaving] = useState(false);
    const [lastSaveStatus, setLastSaveStatus] = useState<{ success: boolean; message: string } | null>(null);

    const saveSnapshot = async () => {
        setIsSaving(true);
        setLastSaveStatus(null);
        
        try {
            const response = await fetch('http://localhost:5000/save_page_info', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    wallet_address: 'placeholder', // TODO: integrate with wagmi
                }),
            });

            const data = await response.json();
            
            if (data.status === 'success') {
                setLastSaveStatus({
                    success: true,
                    message: 'Snapshot saved successfully!'
                });
            } else {
                throw new Error(data.message || 'Failed to save snapshot');
            }
        } catch (error) {
            setLastSaveStatus({
                success: false,
                message: error instanceof Error ? error.message : 'Failed to save snapshot'
            });
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="relative">
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
            
            {lastSaveStatus && (
                <div className={`absolute top-full mt-2 p-2 rounded-md text-sm whitespace-nowrap
                    ${lastSaveStatus.success ? 'bg-green-900/80 text-green-200' : 'bg-red-900/80 text-red-200'}
                    border ${lastSaveStatus.success ? 'border-green-500/50' : 'border-red-500/50'}`}>
                    {lastSaveStatus.message}
                </div>
            )}
        </div>
    );
};
