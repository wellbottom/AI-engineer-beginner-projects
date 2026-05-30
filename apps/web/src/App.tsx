/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useCallback } from 'react';
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
import { getRemoteHistory, getRemoteHistoryDetail, getEnvWarningMsg } from './lib/api';
import { ErrorBanner, SkeletonHistoryRows } from './components/SharedComponents';

const EMPTY_HISTORIES: Record<ProjectId, HistoryRecord[]> = {
  playground: [],
  support: [],
  'web-agent': [],
  'deep-research': [],
  image: [],
  capstone: [],
};

export default function App() {
  // Navigation / routing state.
  const [currentProjectId, setCurrentProjectId] = useState<ProjectId | 'dashboard'>('dashboard');
  const [historyActive, setHistoryActive] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);

  // Per-project history list cache (populated from the real backend on demand).
  const [histories, setHistories] = useState<Record<ProjectId, HistoryRecord[]>>(EMPTY_HISTORIES);

  // History view load/error state.
  const [historiesLoading, setHistoriesLoading] = useState(false);
  const [historyRetrievalError, setHistoryRetrievalError] = useState<string | null>(null);

  // Selected-record detail state (fetched via GET /history/{id}).
  const [detailRecord, setDetailRecord] = useState<HistoryRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Environment advisory for unconfigured backends.
  const envWarning = getEnvWarningMsg();

  // Load the active project's history list from its real backend when the
  // history view opens (Requirements 13.1, 13.2, 13.3). On failure/timeout the
  // error identifies the failed retrieval and affected project (Requirement 13.6).
  const loadProjectHistory = useCallback(async (projectId: ProjectId) => {
    setHistoriesLoading(true);
    setHistoryRetrievalError(null);
    try {
      const list = await getRemoteHistory(projectId);
      setHistories((prev) => ({ ...prev, [projectId]: list }));
    } catch (err) {
      setHistoryRetrievalError((err as Error).message || 'History retrieval failed.');
    } finally {
      setHistoriesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (historyActive && currentProjectId !== 'dashboard' && !selectedHistoryId) {
      loadProjectHistory(currentProjectId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyActive, currentProjectId]);

  // Load the full detail for the selected record (Requirement 13.4).
  useEffect(() => {
    let active = true;
    if (historyActive && currentProjectId !== 'dashboard' && selectedHistoryId) {
      const cached = (histories[currentProjectId] || []).find((r) => r.id === selectedHistoryId);
      setDetailLoading(true);
      setDetailError(null);
      setDetailRecord(cached ?? null);
      getRemoteHistoryDetail(currentProjectId, selectedHistoryId)
        .then((full) => {
          if (active) setDetailRecord(full);
        })
        .catch((err) => {
          // Fall back to the cached summary if available; otherwise surface 13.6.
          if (active && !cached) setDetailError((err as Error).message || 'History retrieval failed.');
        })
        .finally(() => {
          if (active) setDetailLoading(false);
        });
    }
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyActive, currentProjectId, selectedHistoryId]);

  // Append a freshly created run to the in-app list (the backend persists it).
  const handleAddHistory = (record: HistoryRecord) => {
    setHistories((prev) => {
      const list = prev[record.projectId] || [];
      const filtered = list.filter((item) => item.id !== record.id);
      return { ...prev, [record.projectId]: [record, ...filtered] };
    });
  };

  const handleNavigate = (
    projectId: ProjectId | 'dashboard',
    historyMode = false,
    selectedHistId: string | null = null,
  ) => {
    setCurrentProjectId(projectId);
    setHistoryActive(historyMode);
    setSelectedHistoryId(selectedHistId);
    setHistoryRetrievalError(null);
    setDetailError(null);
  };

  const renderActiveScreen = () => {
    if (currentProjectId === 'dashboard') {
      return <DashboardScreen onNavigate={(pId) => handleNavigate(pId)} envWarning={envWarning} />;
    }

    // History views (list + detail).
    if (historyActive) {
      if (selectedHistoryId) {
        if (detailLoading && !detailRecord) {
          return (
            <div className="flex flex-col gap-4">
              <span className="text-xs font-semibold font-mono text-text-faint animate-pulse uppercase">
                Retrieving record...
              </span>
              <SkeletonHistoryRows />
            </div>
          );
        }
        if (detailError && !detailRecord) {
          return <ErrorBanner action="load_history_detail" reason={detailError} />;
        }
        if (detailRecord) {
          return (
            <HistoryViewDetail
              projectId={currentProjectId}
              record={detailRecord}
              onBack={() => setSelectedHistoryId(null)}
            />
          );
        }
      }

      if (historiesLoading) {
        return (
          <div className="flex flex-col gap-4">
            <span className="text-xs font-semibold font-mono text-text-faint animate-pulse uppercase">
              Retrieving history...
            </span>
            <SkeletonHistoryRows />
          </div>
        );
      }

      if (historyRetrievalError) {
        return <ErrorBanner action="load_history" reason={historyRetrievalError} />;
      }

      return (
        <HistoryList
          projectId={currentProjectId}
          records={histories[currentProjectId] || []}
          onSelect={(recId) => setSelectedHistoryId(recId)}
        />
      );
    }

    // Active project screens.
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
          <div className="text-center p-12 text-sm italic text-text-faint">Target screen unresolved.</div>
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
