/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { 
  Terminal, 
  MessageSquare, 
  Globe, 
  Search, 
  Image, 
  Briefcase, 
  Menu, 
  X, 
  Sun, 
  Moon, 
  History, 
  Cpu,
  CornerDownRight,
  Home
} from 'lucide-react';
import { ProjectId } from '../types';

interface SidebarItem {
  id: ProjectId;
  name: string;
  icon: React.ComponentType<any>;
  description: string;
}

export const NAV_ITEMS: SidebarItem[] = [
  { id: 'playground', name: 'LLM Playground', icon: Terminal, description: 'Test and tune model parameters' },
  { id: 'support', name: 'Support Chatbot', icon: MessageSquare, description: 'Contextual product help assistant' },
  { id: 'web-agent', name: 'Ask the Web', icon: Globe, description: 'Web-retrieved direct answering engine' },
  { id: 'deep-research', name: 'Deep Research', icon: Search, description: 'Multi-phased web report synthesizer' },
  { id: 'image', name: 'Image Service', icon: Image, description: 'Generate images from text prompts' },
  { id: 'capstone', name: 'Capstone Agent', icon: Briefcase, description: 'Multi-tool recursive file analyst' }
];

interface AppShellProps {
  currentProjectId: ProjectId | 'dashboard';
  onNavigate: (projectId: ProjectId | 'dashboard', historyMode?: boolean, selectedHistoryId?: string | null) => void;
  historyActive: boolean;
  selectedHistoryId: string | null;
  children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({
  currentProjectId,
  onNavigate,
  historyActive,
  selectedHistoryId,
  children
}) => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');

  // Load physical theme class to HTML root
  useEffect(() => {
    const documentRoot = document.documentElement;
    if (theme === 'light') {
      documentRoot.classList.add('light');
    } else {
      documentRoot.classList.remove('light');
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  // Safe names lookup
  const currentItem = NAV_ITEMS.find(item => item.id === currentProjectId);
  const titleString = currentProjectId === 'dashboard' ? 'Overview' : currentItem?.name || '';

  return (
    <div className="min-h-screen bg-bg text-text-main flex flex-col md:flex-row font-sans relative antialiased selection:bg-primary-main/20 selection:text-white">
      
      {/* 1. SIDEBAR: FIXED 248px FOR DESKTOP */}
      <aside className={`fixed top-0 bottom-0 left-0 w-[248px] bg-surface border-r border-border-dim flex flex-col z-40 transition-transform duration-200 md:translate-x-0 ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full md:block'}`}>
        
        {/* Brand / Logo */}
        <div className="h-14 border-b border-border-dim px-5 flex items-center justify-between select-none shrink-0 cursor-pointer" onClick={() => { onNavigate('dashboard'); setIsSidebarOpen(false); }}>
          <div className="flex items-center gap-2.5">
            <Cpu className="w-5 h-5 text-primary-main" />
            <span className="font-semibold font-sans text-sm tracking-wide text-white">
              AI Monorepo UI
            </span>
          </div>
          {/* Close drawer on mobile */}
          <button onClick={(e) => { e.stopPropagation(); setIsSidebarOpen(false); }} className="p-1 text-text-faint hover:text-text-main md:hidden cursor-pointer rounded hover:bg-surface-2">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Sidebar Nav items */}
        <nav className="flex-1 overflow-y-auto py-4 px-3 flex flex-col gap-1 select-none">
          {/* Home items */}
          <button
            onClick={() => { onNavigate('dashboard'); setIsSidebarOpen(false); }}
            aria-current={currentProjectId === 'dashboard' ? 'page' : undefined}
            className={`flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors relative cursor-pointer ${currentProjectId === 'dashboard' && !historyActive ? 'bg-surface-3 text-white font-semibold' : 'text-text-muted hover:bg-surface-2 hover:text-text-main'}`}
          >
            {/* Active primary border identifier */}
            {currentProjectId === 'dashboard' && !historyActive && (
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-6 bg-primary-main rounded-r" />
            )}
            <Home className="w-4 h-4 shrink-0" />
            <span>Dashboard</span>
          </button>

          <div className="h-px bg-border-dim my-3" />
          
          <span className="text-[10px] font-bold font-mono tracking-wider text-text-faint px-3 uppercase mb-1">
            Projects Sandbox
          </span>

          {NAV_ITEMS.map(item => {
            const isItemActive = currentProjectId === item.id && !historyActive;
            const IconComponent = item.icon;
            
            return (
              <button
                key={item.id}
                onClick={() => { onNavigate(item.id); setIsSidebarOpen(false); }}
                aria-current={isItemActive ? 'page' : undefined}
                className={`flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-all relative group cursor-pointer ${isItemActive ? 'bg-surface-3 text-white font-semibold' : 'text-text-muted hover:bg-surface-2 hover:text-text-main'}`}
              >
                {/* Active marker left border ribbon */}
                {isItemActive && (
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-[22px] bg-primary-main rounded-r" />
                )}
                <IconComponent className="w-4 h-4 shrink-0 group-hover:text-primary-main transition-colors" />
                <span className="truncate">{item.name}</span>
              </button>
            );
          })}
        </nav>

        {/* Sidebar Footer */}
        <div className="p-4 border-t border-border-dim bg-surface/50 text-[11px] font-mono select-none flex flex-col gap-2 shrink-0">
          <div className="flex items-center gap-2 justify-between">
            <span className="text-text-faint">System Context: Isomorphic</span>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 bg-accent-subtle rounded-full animate-pulse" />
              <span className="text-accent-subtle font-semibold">Active</span>
            </div>
          </div>
          <div className="text-text-faint flex items-center justify-between mt-1">
            <span>Theme Control:</span>
            <button 
              onClick={toggleTheme}
              aria-label="Toggle visual theme" 
              className="p-1 hover:bg-surface-3 text-text-muted hover:text-white rounded cursor-pointer transition-colors"
            >
              {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>
      </aside>

      {/* BACKDROP FOR DRAWER UNDER MOBILE */}
      {isSidebarOpen && (
        <div 
          onClick={() => setIsSidebarOpen(false)} 
          className="fixed inset-0 bg-black/60 z-30 md:hidden transition-opacity"
        />
      )}

      {/* 2. MAIN WORKSPACE AND HEADERS IN DECK */}
      <div className="flex-1 flex flex-col min-h-screen md:pl-[248px] overflow-hidden">
        
        {/* TOPBAR HEADER 56px */}
        <header className="h-14 border-b border-border-dim px-4 md:px-6 flex items-center justify-between shrink-0 select-none bg-surface/50 backdrop-blur-sm sticky top-0 z-20">
          
          {/* Breadcrumb line on Left */}
          <div className="flex items-center gap-3">
            {/* Hamburger for mobile */}
            <button 
              onClick={() => setIsSidebarOpen(true)}
              aria-label="Open navigation menu"
              className="p-1.5 -ml-1.5 hover:bg-surface-2 text-text-muted hover:text-white rounded md:hidden cursor-pointer shrink-0"
            >
              <Menu className="w-4 h-4" />
            </button>
            
            <div className="flex items-center gap-1.5 text-xs font-mono text-text-muted">
              <span className="hover:text-text-main cursor-pointer" onClick={() => onNavigate('dashboard')}>App</span>
              <span>/</span>
              <span className="text-text-main font-medium capitalize">{titleString}</span>
              {historyActive && (
                <>
                  <span>/</span>
                  <div className="flex items-center text-primary-main font-semibold gap-1">
                    <CornerDownRight className="w-3 h-3" />
                    <span>History Data</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Quick-actions section on Right Header */}
          <div className="flex items-center gap-2">
            {/* History Toggle clock button, visible for active projects */}
            {currentProjectId !== 'dashboard' && (
              <button
                onClick={() => onNavigate(currentProjectId, !historyActive, null)}
                title={historyActive ? "Return to active playground sandbox" : "Open historic execution logs"}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded border transition-colors cursor-pointer ${historyActive ? 'bg-primary-main/15 border-primary-main/20 text-primary-main font-semibold hover:bg-primary-main/25' : 'bg-surface border-border-dim text-text-muted hover:bg-surface-2 hover:border-border-strong hover:text-text-main'}`}
              >
                <History className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">{historyActive ? 'Close Log' : 'History'}</span>
              </button>
            )}

            {/* Quick Sun Toggle at right */}
            <button 
              onClick={toggleTheme}
              aria-label="Quick Toggle visual theme" 
              className="p-2 border border-border-dim bg-surface hover:bg-surface-2 text-text-muted hover:text-text-main rounded cursor-pointer transition-colors"
            >
              {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
            </button>
          </div>
        </header>

        {/* 3. SCROLLING MAIN CONTAINER */}
        <main className="flex-1 overflow-y-auto px-4 py-6 md:p-8 flex flex-col items-center">
          <div className="w-full max-w-[1240px] flex-1 flex flex-col gap-6">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};
