/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { ProjectId, HistoryRecord } from './types';
import { AppShell } from './components/AppShell';
import { DashboardScreen } from './components/DashboardScreen';
import { PlaygroundScreen } from './components/PlaygroundScreen';
import { SupportScreen } from './components/SupportScreen';
import { WebAgentScreen } from './components/WebAgentScreen';
import { DeepResearchScreen } from './components/DeepResearchScreen';
import { ImageScreen } from './components/ImageScreen';
import { CapstoneScreen } from './components/CapstoneScreen';
import { HistoryList, HistoryViewDetail } from './components/HistoryViews';
import { getRemoteHistory, getEnvWarningMsg } from './lib/api';
import { ErrorBanner, SkeletonHistoryRows } from './components/SharedComponents';

export default function App() {
  // Navigation Routing States
  const [currentProjectId, setCurrentProjectId] = useState<ProjectId | 'dashboard'>('dashboard');
  const [historyActive, setHistoryActive] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);

  // Unified Histories cache
  const [histories, setHistories] = useState<Record<ProjectId, HistoryRecord[]>>({
    playground: [],
    support: [],
    'web-agent': [],
    'deep-research': [],
    image: [],
    capstone: []
  });

  // Loading/Errors States
  const [historiesLoading, setHistoriesLoading] = useState(false);
  const [historyRetrievalError, setHistoryRetrievalError] = useState<string | null>(null);

  // Environment and general warnings (statically checked)
  const envWarning = getEnvWarningMsg();

  // Load and hydrate histories across all projects
  useEffect(() => {
    let active = true;
    const loadAllHistories = async () => {
      setHistoriesLoading(true);
      setHistoryRetrievalError(null);
      
      const projects: ProjectId[] = ['playground', 'support', 'web-agent', 'deep-research', 'image', 'capstone'];
      const loaded: Partial<Record<ProjectId, HistoryRecord[]>> = {};

      try {
        await Promise.all(
          projects.map(async (pId) => {
            const list = await getRemoteHistory(pId);
            loaded[pId] = list;
          })
        );
        
        if (active) {
          setHistories(loaded as Record<ProjectId, HistoryRecord[]>);
        }
      } catch (err: any) {
        console.error('Unified history hydration failed:', err);
        if (active) {
          setHistoryRetrievalError(err.message || 'Gateway extraction failed');
        }
      } finally {
        if (active) setHistoriesLoading(false);
      }
    };

    loadAllHistories();
    return () => {
      active = false;
    };
  }, []);

  // Handler to append newly created runs to history list state dynamically
  const handleAddHistory = (record: HistoryRecord) => {
    setHistories(prev => {
      const list = prev[record.projectId] || [];
      const filtered = list.filter(item => item.id !== record.id);
      return {
        ...prev,
        [record.projectId]: [record, ...filtered]
      };
    });
  };

  // Handler to delete deep history record
  const handleDeleteHistory = (recordId: string) => {
    if (currentProjectId === 'dashboard') return;
    
    // Remove from local storage
    const storageKey = `ai_practice_monorepo_history_${currentProjectId}`;
    try {
      const data = localStorage.getItem(storageKey);
      if (data) {
        const list: HistoryRecord[] = JSON.parse(data);
        const filtered = list.filter(item => item.id !== recordId);
        localStorage.setItem(storageKey, JSON.stringify(filtered));
      }
    } catch (e) {
      console.error(e);
    }

    setHistories(prev => {
      const list = prev[currentProjectId as ProjectId] || [];
      return {
        ...prev,
        [currentProjectId]: list.filter(item => item.id !== recordId)
      };
    });

    if (selectedHistoryId === recordId) {
      setSelectedHistoryId(null);
    }
  };

  // Safe navigation handler
  const handleNavigate = (
    projectId: ProjectId | 'dashboard', 
    historyMode = false, 
    selectedHistId: string | null = null
  ) => {
    setCurrentProjectId(projectId);
    setHistoryActive(historyMode);
    setSelectedHistoryId(selectedHistId);
  };

  // Render Project-Specific Sandboxes
  const renderActiveScreen = () => {
    if (currentProjectId === 'dashboard') {
      return (
        <DashboardScreen
          onNavigate={(pId) => handleNavigate(pId)}
          envWarning={envWarning}
        />
      );
    }

    // Handlers for History Listing & Detail Reuse views (Section 4.12 of SPEC)
    if (historyActive) {
      if (selectedHistoryId) {
        const activeList = histories[currentProjectId] || [];
        const selectedRecord = activeList.find(r => r.id === selectedHistoryId);
        
        if (selectedRecord) {
          return (
            <HistoryViewDetail
              projectId={currentProjectId}
              record={selectedRecord}
              onBack={() => setSelectedHistoryId(null)}
            />
          );
        }
      }

      if (historiesLoading) {
        return (
          <div className="flex flex-col gap-4">
            <span className="text-xs font-semibold font-mono text-text-faint animate-pulse uppercase">Retrieving histories...</span>
            <SkeletonHistoryRows />
          </div>
        );
      }

      if (historyRetrievalError) {
        return (
          <ErrorBanner
            action={`load_history`}
            reason={`Failed to query history log segments for project ${currentProjectId}: ${historyRetrievalError}`}
          />
        );
      }

      return (
        <HistoryList
          projectId={currentProjectId}
          records={histories[currentProjectId] || []}
          onSelect={(recId) => setSelectedHistoryId(recId)}
          onDelete={handleDeleteHistory}
        />
      );
    }

    // Standard Project screens routing
    switch (currentProjectId) {
      case 'playground':
        return <PlaygroundScreen onAddHistory={handleAddHistory} />;
      case 'support':
        return <SupportScreen onAddHistory={handleAddHistory} />;
      case 'web-agent':
        return <WebAgentScreen onAddHistory={handleAddHistory} />;
      case 'deep-research':
        return <DeepResearchScreen onAddHistory={handleAddHistory} />;
      case 'image':
        return <ImageScreen onAddHistory={handleAddHistory} />;
      case 'capstone':
        return <CapstoneScreen onAddHistory={handleAddHistory} />;
      default:
        return (
          <div className="text-center p-12 text-sm italic text-text-faint">
            Target screen unresolved.
          </div>
        );
    }
  };

  return (
    <AppShell
      currentProjectId={currentProjectId}
      onNavigate={handleNavigate}
      historyActive={historyActive}
      selectedHistoryId={selectedHistoryId}
    >
      {renderActiveScreen()}
    </AppShell>
  );
}
