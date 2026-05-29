/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { motion } from 'motion/react';
import { Cpu } from 'lucide-react';
import { ProjectId } from '../types';
import { Card, Badge } from './SharedComponents';
import { NAV_ITEMS } from './AppShell';

interface DashboardScreenProps {
  onNavigate: (projectId: ProjectId) => void;
  envWarning: string | null;
}

const PROVIDERS_MAP: Record<ProjectId, string[]> = {
  playground: ['LLM Model Gateway', 'Isomorphic Node API'],
  support: ['Gemini API', 'Session Store'],
  'web-agent': ['Google Search API', 'Retrieval Synthesizer'],
  'deep-research': ['Gemini Model', 'Google Search Grounding', 'Multi-Phase Stepper'],
  image: ['Imagen Model', 'Base64 Stream'],
  capstone: ['Recursive Agent Core', 'Multipart File Ingestion', 'Tool Sandbox'],
};

export const DashboardScreen: React.FC<DashboardScreenProps> = ({
  onNavigate,
  envWarning
}) => {
  return (
    <div className="flex flex-col gap-8 py-2">
      
      {/* Page Title display */}
      <div className="flex flex-col gap-2.5">
        <h1 className="text-3xl font-extrabold font-sans tracking-tight text-white sm:text-4xl">
          AI Engineer Practice Monorepo
        </h1>
        <p className="text-sm font-sans text-text-muted max-w-2xl leading-relaxed">
          The single central dashboard for six advanced standalone sandboxes. Build and test model prompts, search embeddings, synthetic research threads, generated canvases, and nested multi-tool agents in real-time.
        </p>
      </div>

      {/* Env Warning banner if any */}
      {envWarning && (
        <div className="border border-orange-500/10 bg-[rgba(242,181,68,0.06)] rounded-lg p-4 flex gap-3 text-xs leading-relaxed max-w-3xl">
          <span className="text-warning-subtle font-bold shrink-0 self-start select-none">SYSTEM ADVISORY:</span>
          <div>
            <p className="text-text-muted">{envWarning}</p>
          </div>
        </div>
      )}

      {/* Grid containing Project cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {NAV_ITEMS.map((item, idx) => {
          const IconComponent = item.icon;
          const providers = PROVIDERS_MAP[item.id] || [];
          
          return (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: idx * 0.04 }}
              onClick={() => onNavigate(item.id)}
              className="cursor-pointer group"
            >
              <Card className="h-full hover:border-primary-main/35 hover:bg-surface-2 hover:-translate-y-0.5 hover:shadow-md transition-all duration-200 flex flex-col justify-between py-6">
                <div>
                  <div className="flex items-center justify-between mb-4 select-none">
                    <div className="p-2.5 bg-surface-2 group-hover:bg-primary-main/10 rounded-md text-text-muted group-hover:text-primary-main transition-all border border-border-dim shadow-inner">
                      <IconComponent className="w-5 h-5 shrink-0" />
                    </div>
                    <span className="text-[10px] font-mono font-semibold text-text-faint bg-surface-2 px-2 py-0.5 rounded tracking-wider uppercase border border-border-dim group-hover:border-primary-main/20">
                      Sandbox #{idx + 1}
                    </span>
                  </div>

                  <h3 className="text-md font-bold font-sans tracking-tight text-white mb-1.5 group-hover:text-primary-main transition-colors">
                    {item.name}
                  </h3>
                  
                  <p className="text-xs font-sans text-text-muted leading-relaxed mb-6 group-hover:text-text-main transition-colors">
                    {item.description}
                  </p>
                </div>

                <div className="flex flex-wrap gap-1.5 pt-3 border-t border-border-dim/75">
                  {providers.map((p, pIdx) => (
                    <Badge key={pIdx} variant="neutral" className="text-[10px] py-0 px-1.5 border-border-dim group-hover:bg-surface-3 transition-colors">
                      {p}
                    </Badge>
                  ))}
                </div>
              </Card>
            </motion.div>
          );
        })}
      </div>

    </div>
  );
};
