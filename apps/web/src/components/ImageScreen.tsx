/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { Sparkles, Image as ImageIcon, Download } from 'lucide-react';
import {
  Card,
  Button,
  Textarea,
  Select,
  ErrorBanner,
  PersistenceIndicator,
} from './SharedComponents';
import { generateImage, getImageModels, SERVICE_URLS, PROJECT_ENV_VARS } from '../lib/api';
import { HistoryRecord } from '../types';

interface ImageScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

export const ImageScreen: React.FC<ImageScreenProps> = ({ onAddHistory }) => {
  const [prompt, setPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [models, setModels] = useState<string[]>([]);

  const [generating, setGenerating] = useState(false);
  const [imageUrl, setImageUrl] = useState('');
  const [persistenceMeta, setPersistenceMeta] = useState<{ ok: boolean; operation_id?: string } | null>(null);

  const [validationError, setValidationError] = useState('');
  const [generationError, setGenerationError] = useState<{ action: string; reason: string } | null>(null);

  const configured = !!SERVICE_URLS.image;

  // Load the selectable model list from the backend (Requirement 8.3).
  useEffect(() => {
    let active = true;
    const fetchModels = async () => {
      try {
        const list = await getImageModels();
        if (!active) return;
        setModels(list);
        // The backend applies its own default when none is selected; we default
        // the dropdown to the first offered model for convenience.
        if (list.length > 0) setSelectedModel(list[0]);
      } catch {
        // Listing failure is non-fatal; the user can still submit (backend default).
        if (active) setModels([]);
      }
    };
    fetchModels();
    return () => {
      active = false;
    };
  }, []);

  const handleGenerate = async () => {
    if (generating) return;

    const trimmed = prompt.trim();
    if (!trimmed) {
      setValidationError('Art generation text prompt is required.');
      return;
    }
    if (trimmed.length > 1000) {
      setValidationError(`Prompt exceeds 1000 max limit (${trimmed.length} characters).`);
      return;
    }

    setValidationError('');
    setImageUrl('');
    setGenerationError(null);
    setPersistenceMeta(null);

    if (!configured) {
      setGenerationError({
        action: 'image_generate',
        reason: `Image Service backend is not configured. Set ${PROJECT_ENV_VARS.image} to its base URL.`,
      });
      return;
    }

    setGenerating(true);

    try {
      // Send the selected model, or undefined so the backend applies its default.
      const result = await generateImage(trimmed, selectedModel || undefined);

      const combinedDataUrl = `data:${result.mime_type};base64,${result.data_base64}`;
      setImageUrl(combinedDataUrl);
      setPersistenceMeta(result.persistence ?? null);

      const histRecord: HistoryRecord = {
        id: `img_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        projectId: 'image',
        created_at: new Date().toISOString(),
        label: trimmed.length > 50 ? `${trimmed.substring(0, 50)}...` : trimmed,
        inputs: { prompt: trimmed, model: selectedModel || undefined },
        outputs: { imageUrl: combinedDataUrl, metadata: result as unknown as HistoryRecord['outputs']['metadata'] },
      };
      onAddHistory(histRecord);
    } catch (err) {
      setGenerationError({
        action: 'image_generate',
        reason: (err as Error).message || 'The image provider failed to return an image.',
      });
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = () => {
    if (!imageUrl) return;
    const a = document.createElement('a');
    a.href = imageUrl;
    a.download = `art_${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">

      {/* Parameters Controls Column (5 cols) */}
      <div className="lg:col-span-5 flex flex-col gap-5">
        <Card title="Image Canvas parameters">
          <div className="flex flex-col gap-4 select-none">

            <Textarea
              id="image-prompt-textarea-id"
              label="Creative Design Text Prompt"
              placeholder="Describe the subject and aesthetic, e.g. 'A futuristic city in neon rain, detailed digital painting'..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={generating}
              maxLength={1000}
              error={validationError}
              mono
            />

            <Select
              id="image-model-selector-id"
              label="Generative Model"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={generating}
              options={
                models.length > 0
                  ? models.map((m) => ({ value: m, label: m }))
                  : [{ value: '', label: 'Backend default' }]
              }
            />

            <Button
              variant="primary"
              onClick={handleGenerate}
              disabled={generating || !prompt.trim()}
              isLoading={generating}
              className="w-full gap-2 text-xs font-semibold py-5 select-none"
            >
              <Sparkles className="w-3.5 h-3.5 shrink-0" />
              <span>Generate Design Frame</span>
            </Button>

          </div>
        </Card>
      </div>

      {/* Render Canvas outcome columns (7 cols) */}
      <div className="lg:col-span-7 flex flex-col gap-5">
        <Card title="Generated Art canvas">
          <div className="flex flex-col gap-4 min-h-[440px] items-stretch justify-center relative bg-surface">

            {/* Idle state blank banner */}
            {!generating && !imageUrl && !generationError && (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-24 select-none">
                <ImageIcon className="w-9 h-9 text-text-faint mb-2" />
                <span className="text-xs font-semibold text-text-muted">Canvas pristine</span>
                <span className="text-[11px] text-text-faint mt-1 max-w-xs">Primed parameters are ready. Execute and generate custom frames.</span>
              </div>
            )}

            {/* Loading indicator while generating (Requirement 8.4) */}
            {generating && (
              <div
                role="status"
                aria-label="Loading"
                className="flex-1 flex flex-col items-center justify-center text-center p-12 select-none border border-border-dim/50 border-double rounded-lg bg-surface-2 bg-opacity-45 animate-pulse"
              >
                <div className="w-20 h-20 bg-surface-3 rounded-full flex items-center justify-center mb-4 text-primary-main animate-spin">
                  <Sparkles className="w-6 h-6 animate-pulse" />
                </div>
                <span className="text-xs font-semibold text-text-main">Synthesizing image...</span>
                <span className="text-[10px] text-text-faint font-mono mt-1 select-all">Requesting the image provider</span>
              </div>
            )}

            {/* In-case compile errored */}
            {generationError && !generating && (
              <div className="my-1 select-none">
                <ErrorBanner
                  action={generationError.action}
                  reason={generationError.reason}
                  onRetry={handleGenerate}
                />
              </div>
            )}

            {/* Successful frame outcomes */}
            {imageUrl && !generating && (
              <div className="flex-1 flex flex-col gap-4 select-text">
                <div className="border border-border-strong bg-surface-2 rounded-lg overflow-hidden flex items-center justify-center relative group max-w-full">
                  <img
                    src={imageUrl}
                    alt={prompt}
                    referrerPolicy="no-referrer"
                    className="max-h-[450px] object-contain rounded w-full h-auto"
                  />

                  <div className="absolute inset-x-0 bottom-0 bg-black/75 p-3 select-none flex items-center justify-between opacity-0 group-hover:opacity-100 transition-opacity">
                    <span className="text-xs font-mono text-text-muted truncate select-none max-w-[70%]">{selectedModel || 'backend default'}</span>
                    <button
                      onClick={handleDownload}
                      className="flex items-center gap-1 bg-primary-main hover:bg-primary-hover text-primary-contrast px-3 py-1 font-semibold text-xs rounded transition-colors cursor-pointer"
                    >
                      <Download className="w-3 h-3" />
                      <span>Export File</span>
                    </button>
                  </div>
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-t border-border-dim pt-4 mt-2 select-none">
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] font-mono text-text-faint uppercase font-bold tracking-wider">Canvas details:</span>
                    <p className="text-xs text-text-muted font-sans italic truncate max-w-xs">{prompt}</p>
                  </div>

                  {persistenceMeta && !persistenceMeta.ok && (
                    <PersistenceIndicator ok={persistenceMeta.ok} operationId={persistenceMeta.operation_id} />
                  )}
                </div>
              </div>
            )}

          </div>
        </Card>
      </div>

    </div>
  );
};
