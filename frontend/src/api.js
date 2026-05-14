/**
 * VisCode API Client
 * Handles all communication with the FastAPI backend.
 */

const API_BASE = '';  // Vite proxy routes /api/* and /health to backend

export const api = {
    /**
     * Health check
     */
    async health() {
        const res = await fetch(`${API_BASE}/health`);
        return res.json();
    },

    /**
     * Estimate analysis cost (no AI calls)
     */
    async estimate(path, modelTier = 'balanced') {
        const res = await fetch(`${API_BASE}/api/estimate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, model_tier: modelTier }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Estimate failed');
        }
        return res.json();
    },

    /**
     * Start analysis — returns project_id
     */
    async startAnalysis(path, modelTier = 'balanced', ignorePatterns = []) {
        const res = await fetch(`${API_BASE}/api/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path,
                model_tier: modelTier,
                ignore_patterns: ignorePatterns,
            }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Analysis start failed');
        }
        return res.json();
    },

    /**
     * Stream analysis progress via SSE
     * @param {string} projectId
     * @param {function} onProgress - called with {phase, message, percent}
     * @returns {Promise} resolves when analysis completes
     */
    streamProgress(projectId, onProgress) {
        return new Promise((resolve, reject) => {
            const source = new EventSource(`${API_BASE}/api/analyze/${projectId}/stream`);
            
            source.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    onProgress(data);
                } catch (e) {
                    // Ignore parse errors for heartbeats
                }
            };

            // Listen for specific event types
            const phases = ['scanning', 'cache_check', 'analyzing', 'cross_analysis',
                           'architecture', 'building_graph', 'complete', 'warning', 'error', 'done'];
            
            for (const phase of phases) {
                source.addEventListener(phase, (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        onProgress(data);
                        if (phase === 'done') {
                            source.close();
                            resolve(projectId);
                        }
                        if (phase === 'error') {
                            source.close();
                            reject(new Error(data.message || 'Analysis failed'));
                        }
                    } catch (e) {
                        // Ignore parse errors
                    }
                });
            }

            source.onerror = () => {
                source.close();
                reject(new Error('Connection to server lost'));
            };
        });
    },

    /**
     * Get complete project results
     */
    async getProject(projectId) {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}`);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to load project');
        }
        return res.json();
    },

    /**
     * Get graph data for visualization
     */
    async getGraph(projectId) {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/graph`);
        if (!res.ok) throw new Error('Failed to load graph');
        return res.json();
    },

    /**
     * Get file detail analysis + graph
     */
    async getFileDetail(projectId, filePath) {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/file/${filePath}`);
        if (!res.ok) throw new Error('Failed to load file detail');
        return res.json();
    },

    /**
     * Cache stats
     */
    async cacheStats() {
        const res = await fetch(`${API_BASE}/api/cache/stats`);
        return res.json();
    },
};
