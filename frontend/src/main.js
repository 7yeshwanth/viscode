/**
 * VisCode Main Application
 * Wires together: API client, Canvas Engine, Detail Panel
 */

import './styles/index.css';
import { api } from './api.js';
import { CanvasEngine } from './canvas.js';
import { DetailPanel } from './panel.js';

// ── State ──
let canvas;
let panel;
let currentProjectId = null;
let currentProjectData = null;
let currentOverviewGraph = null;  // Stored for back-navigation

// ── DOM Elements ──
const pathInput = document.getElementById('path-input');
const analyzeBtn = document.getElementById('analyze-btn');
const estimateBtn = document.getElementById('estimate-btn');
const searchBtn = document.getElementById('search-btn');
const zoomFitBtn = document.getElementById('zoom-fit-btn');
const apiStatus = document.getElementById('api-status');
const statusMessage = document.getElementById('status-message');
const cacheInfo = document.getElementById('cache-info');
const welcomeScreen = document.getElementById('welcome-screen');
const progressOverlay = document.getElementById('progress-overlay');
const progressBar = document.getElementById('progress-bar');
const progressPercent = document.getElementById('progress-percent');
const progressPhase = document.getElementById('progress-phase');
const progressLog = document.getElementById('progress-log');
const estimateModal = document.getElementById('estimate-modal');
const estimateBody = document.getElementById('estimate-body');
const estimateProceedBtn = document.getElementById('estimate-proceed-btn');
const privacyModal = document.getElementById('privacy-modal');
const consentCheckbox = document.getElementById('consent-checkbox');
const consentProceedBtn = document.getElementById('consent-proceed-btn');
const searchOverlay = document.getElementById('search-overlay');
const searchInput = document.getElementById('search-input');
const searchResults = document.getElementById('search-results');

// ── Initialize ──
function init() {
    canvas = new CanvasEngine('#canvas');
    panel = new DetailPanel();

    // Wire canvas events
    canvas.onNodeClick = (node) => panel.show(node);
    canvas.onNodeDoubleClick = (node) => handleDrillDown(node);

    // Wire button events
    analyzeBtn.addEventListener('click', handleAnalyze);
    estimateBtn.addEventListener('click', handleEstimate);
    searchBtn.addEventListener('click', toggleSearch);
    zoomFitBtn.addEventListener('click', () => canvas.fitToView());
    estimateProceedBtn.addEventListener('click', () => {
        estimateModal.classList.add('hidden');
        startAnalysis();
    });

    // Privacy consent
    consentCheckbox.addEventListener('change', () => {
        consentProceedBtn.disabled = !consentCheckbox.checked;
    });
    consentProceedBtn.addEventListener('click', () => {
        localStorage.setItem('viscode_consent', 'true');
        privacyModal.classList.add('hidden');
        startAnalysis();
    });

    // Search
    searchInput.addEventListener('input', handleSearch);

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            toggleSearch();
        }
        if (e.key === 'Escape') {
            searchOverlay.classList.add('hidden');
            panel.hide();
        }
    });

    // Enter key on path input
    pathInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleAnalyze();
    });

    // Back button (hidden initially)
    const backBtn = document.createElement('button');
    backBtn.id = 'back-btn';
    backBtn.className = 'btn btn-ghost';
    backBtn.textContent = '← Overview';
    backBtn.style.display = 'none';
    backBtn.addEventListener('click', handleBackToOverview);
    document.querySelector('.topbar-left').appendChild(backBtn);

    // Check API health
    checkHealth();
}

// ── API Health ──
async function checkHealth() {
    try {
        const health = await api.health();
        apiStatus.classList.toggle('connected', health.status === 'ok');
        apiStatus.title = health.api_key_valid
            ? 'Connected — API key valid'
            : 'Connected — API key not set';
        statusMessage.textContent = 'Ready';

        // Cache info
        const stats = await api.cacheStats();
        cacheInfo.textContent = `Cache: ${stats.entries} entries`;
    } catch {
        apiStatus.classList.remove('connected');
        apiStatus.title = 'Backend not reachable';
        statusMessage.textContent = 'Backend not connected — start with: cd backend && python main.py';
    }
}

// ── Estimate ──
async function handleEstimate() {
    const path = pathInput.value.trim();
    if (!path) {
        statusMessage.textContent = '⚠️ Enter a project path first';
        return;
    }

    statusMessage.textContent = 'Estimating...';
    estimateBtn.disabled = true;

    try {
        const est = await api.estimate(path);

        estimateBody.innerHTML = `
            <div style="text-align: center; margin-bottom: 16px;">
                <div class="estimate-cost">$${est.estimated_cost_usd.toFixed(4)}</div>
                <div style="color: var(--text-muted); font-size: 11px;">estimated cost</div>
            </div>
            <table class="estimate-table">
                <tr><td>Files to analyze</td><td>${est.total_files}</td></tr>
                <tr><td>Total lines</td><td>${est.total_lines.toLocaleString()}</td></tr>
                <tr><td>Estimated tokens</td><td>${est.estimated_tokens.toLocaleString()}</td></tr>
                <tr><td>Estimated time</td><td>~${est.estimated_time_seconds}s</td></tr>
                <tr><td>Model tier</td><td>${est.model_tier}</td></tr>
                <tr><td>Languages</td><td>${Object.entries(est.languages).map(([l, c]) => `${l}: ${c}`).join(', ')}</td></tr>
            </table>
            ${est.warnings.map(w => `<div class="estimate-warning">⚠️ ${w}</div>`).join('')}
        `;
        estimateModal.classList.remove('hidden');
        statusMessage.textContent = 'Estimate ready';
    } catch (err) {
        statusMessage.textContent = `⚠️ ${err.message}`;
    } finally {
        estimateBtn.disabled = false;
    }
}

// ── Analyze ──
async function handleAnalyze() {
    const path = pathInput.value.trim();
    if (!path) {
        statusMessage.textContent = '⚠️ Enter a project path first';
        return;
    }

    // Check privacy consent
    if (!localStorage.getItem('viscode_consent')) {
        privacyModal.classList.remove('hidden');
        return;
    }

    startAnalysis();
}

async function startAnalysis() {
    const path = pathInput.value.trim();
    if (!path) return;

    analyzeBtn.disabled = true;
    estimateBtn.disabled = true;
    welcomeScreen.classList.add('hidden');
    progressOverlay.classList.remove('hidden');
    progressLog.innerHTML = '';
    progressBar.style.width = '0%';
    progressPercent.textContent = '0%';

    try {
        // Start analysis
        const { project_id } = await api.startAnalysis(path);
        currentProjectId = project_id;
        statusMessage.textContent = `Analyzing... (${project_id})`;

        // Stream progress
        await api.streamProgress(project_id, (data) => {
            const pct = data.percent || 0;
            progressBar.style.width = `${pct}%`;
            progressPercent.textContent = `${Math.round(pct)}%`;
            progressPhase.textContent = data.message || data.phase || '';

            // Add to log
            const cls = data.phase === 'warning' ? 'log-warning' : (data.phase === 'error' ? 'log-error' : '');
            progressLog.innerHTML += `<div class="${cls}">[${data.phase}] ${data.message}</div>`;
            progressLog.scrollTop = progressLog.scrollHeight;
        });

        // Load results
        statusMessage.textContent = 'Loading results...';
        const results = await api.getProject(project_id);
        currentProjectData = results;

        // Render graph
        if (results.graph) {
            currentOverviewGraph = results.graph;
            canvas.render(results.graph);
            panel.setProjectData(results);

            // Show architecture summary if available
            if (results.graph.architecture) {
                showArchSummary(results.graph.architecture);
            }
        }

        statusMessage.textContent = `✅ Analysis complete — ${project_id}`;
    } catch (err) {
        statusMessage.textContent = `❌ ${err.message}`;
    } finally {
        progressOverlay.classList.add('hidden');
        analyzeBtn.disabled = false;
        estimateBtn.disabled = false;
    }
}

// ── Drill Down ──
async function handleDrillDown(node) {
    if (node.type !== 'file' || !currentProjectId) return;

    statusMessage.textContent = `Loading detail for ${node.label}...`;

    try {
        const detail = await api.getFileDetail(currentProjectId, node.file_path);
        if (detail.graph) {
            canvas.render(detail.graph);
            document.getElementById('back-btn').style.display = 'inline-flex';
        }
        statusMessage.textContent = `Viewing: ${node.file_path}`;
    } catch (err) {
        statusMessage.textContent = `⚠️ ${err.message}`;
    }
}

// ── Back Navigation ──
function handleBackToOverview() {
    if (currentOverviewGraph) {
        canvas.render(currentOverviewGraph);
        document.getElementById('back-btn').style.display = 'none';
        statusMessage.textContent = 'Overview';
        panel.hide();
    }
}

// ── Search ──
function toggleSearch() {
    searchOverlay.classList.toggle('hidden');
    if (!searchOverlay.classList.contains('hidden')) {
        searchInput.focus();
        searchInput.select();
    }
}

function handleSearch() {
    const query = searchInput.value.trim();
    const matches = canvas.highlightSearch(query);

    if (!query) {
        searchResults.innerHTML = '';
        return;
    }

    searchResults.innerHTML = matches.slice(0, 20).map(node => {
        const icon = { file: '📄', function: '⚡', class: '🏗️', endpoint: '🔌', method: '🔧', model: '📊' };
        return `<div class="search-result-item" data-id="${node.id}">
            <span>${icon[node.type] || '•'}</span>
            <span>${node.label}</span>
            <span style="color: var(--text-muted); font-size: 11px;">${node.type}</span>
        </div>`;
    }).join('');

    // Click on search result
    searchResults.querySelectorAll('.search-result-item').forEach(el => {
        el.addEventListener('click', () => {
            const nodeId = el.dataset.id;
            const node = canvas.graphData?.nodes.find(n => n.id === nodeId);
            if (node) {
                canvas._selectNode(nodeId);
                panel.show(node);
            }
            searchOverlay.classList.add('hidden');
        });
    });
}

// ── Architecture Summary ──
function showArchSummary(arch) {
    if (!arch || !arch.summary) return;

    // Remove previous summary if exists (prevents duplicates on re-analysis)
    const existing = document.querySelector('.arch-summary');
    if (existing) existing.remove();

    const archHtml = document.createElement('div');
    archHtml.className = 'arch-summary';
    archHtml.style.cssText = 'position:absolute; top:8px; left:8px; z-index:5; max-width:360px;';
    archHtml.innerHTML = `
        <h4>🏗️ ${arch.project_type || 'Project'} ${arch.framework ? `• ${arch.framework}` : ''}</h4>
        <p>${arch.summary}</p>
        ${arch.tech_stack ? `<div class="arch-stack">${arch.tech_stack.map(t => `<span class="arch-stack-item">${t}</span>`).join('')}</div>` : ''}
    `;

    const canvasContainer = document.querySelector('.canvas-container');
    canvasContainer.appendChild(archHtml);
}

// ── Boot ──
document.addEventListener('DOMContentLoaded', init);
