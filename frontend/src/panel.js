/**
 * VisCode Detail Panel
 * Renders node details when a node is clicked on the canvas.
 */

export class DetailPanel {
    constructor() {
        this.panel = document.getElementById('detail-panel');
        this.title = document.getElementById('panel-title');
        this.content = document.getElementById('panel-content');
        this.closeBtn = document.getElementById('panel-close');
        this.projectData = null;

        this.closeBtn.addEventListener('click', () => this.hide());
    }

    setProjectData(data) {
        this.projectData = data;
    }

    show(node) {
        this.panel.classList.remove('hidden');
        this.title.textContent = node.label;
        this.content.innerHTML = this._renderNode(node);
    }

    hide() {
        this.panel.classList.add('hidden');
    }

    _renderNode(node) {
        const type = node.type;
        const meta = node.metadata || {};

        let html = '';

        // Type badge
        html += `<div class="panel-section">
            <span class="panel-badge badge-${type}">${this._typeIcon(type)} ${type.toUpperCase()}</span>
            ${this._renderConfidence(node.confidence)}
            ${meta.complexity ? this._renderComplexity(meta.complexity) : ''}
        </div>`;

        // Description
        if (node.description) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Description</div>
                <div class="panel-description">${this._escape(node.description)}</div>
            </div>`;
        }

        // Purpose
        if (meta.purpose) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Purpose</div>
                <div class="panel-description">${this._escape(meta.purpose)}</div>
            </div>`;
        }

        // File info
        if (node.file_path) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Location</div>
                <div class="panel-description" style="font-family: var(--font-mono); font-size: 12px;">
                    📄 ${this._escape(node.file_path)}${node.line_start ? `:${node.line_start}` : ''}${node.line_end ? `-${node.line_end}` : ''}
                </div>
            </div>`;
        }

        // Metadata
        if (meta.language) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Details</div>
                <table class="estimate-table">
                    ${meta.language ? `<tr><td>Language</td><td>${meta.language}</td></tr>` : ''}
                    ${meta.line_count ? `<tr><td>Lines</td><td>${meta.line_count}</td></tr>` : ''}
                    ${meta.function_count != null ? `<tr><td>Functions</td><td>${meta.function_count}</td></tr>` : ''}
                    ${meta.class_count != null ? `<tr><td>Classes</td><td>${meta.class_count}</td></tr>` : ''}
                    ${meta.endpoint_count != null ? `<tr><td>Endpoints</td><td>${meta.endpoint_count}</td></tr>` : ''}
                    ${meta.role ? `<tr><td>Role</td><td>${meta.role}</td></tr>` : ''}
                </table>
            </div>`;
        }

        // Calls
        if (meta.calls && meta.calls.length > 0) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Calls</div>
                <ul class="panel-connection-list">
                    ${meta.calls.map(c => `<li>→ ${this._escape(c)}</li>`).join('')}
                </ul>
            </div>`;
        }

        // Side effects
        if (meta.side_effects && meta.side_effects.length > 0) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Side Effects</div>
                <div class="panel-tags">
                    ${meta.side_effects.map(s => `<span class="panel-tag">${this._escape(s)}</span>`).join('')}
                </div>
            </div>`;
        }

        // Inherits from
        if (meta.inherits_from && meta.inherits_from.length > 0) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Inherits From</div>
                <ul class="panel-connection-list">
                    ${meta.inherits_from.map(c => `<li>↑ ${this._escape(c)}</li>`).join('')}
                </ul>
            </div>`;
        }

        // Endpoint specifics
        if (meta.handler) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Handler</div>
                <div class="panel-description" style="font-family: var(--font-mono);">${this._escape(meta.handler)}</div>
            </div>`;
        }
        if (meta.auth_required != null) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Auth Required</div>
                <div class="panel-description">${meta.auth_required ? '🔒 Yes' : '🔓 No'}</div>
            </div>`;
        }

        // Model fields
        if (meta.fields && meta.fields.length > 0) {
            html += `<div class="panel-section">
                <div class="panel-section-title">Fields</div>
                <table class="estimate-table">
                    ${meta.fields.map(f => `<tr><td style="font-family: var(--font-mono);">${this._escape(f.name)}</td><td>${this._escape(f.type || '')}</td></tr>`).join('')}
                </table>
            </div>`;
        }

        // Error state
        if (node.status === 'failed' && meta.error) {
            html += `<div class="panel-section">
                <div class="estimate-warning">⚠️ ${this._escape(meta.error)}</div>
            </div>`;
        }

        return html;
    }

    _typeIcon(type) {
        const icons = {
            file: '📄', folder: '📁', function: '⚡', method: '🔧',
            class: '🏗️', endpoint: '🔌', model: '📊', variable: '💎',
        };
        return icons[type] || '•';
    }

    _renderConfidence(confidence) {
        if (confidence == null) return '';
        let cls = 'confidence-high';
        let label = 'High';
        if (confidence <= 0.5) { cls = 'confidence-low'; label = 'Low'; }
        else if (confidence <= 0.8) { cls = 'confidence-mid'; label = 'Medium'; }
        return `<span class="confidence-dot ${cls}" title="Confidence: ${(confidence * 100).toFixed(0)}% (${label})"></span>`;
    }

    _renderComplexity(complexity) {
        return `<span class="complexity-badge complexity-${complexity}">${complexity}</span>`;
    }

    _escape(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }
}
