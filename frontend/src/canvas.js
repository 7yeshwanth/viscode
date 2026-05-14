/**
 * VisCode Canvas Engine
 * D3.js-powered SVG canvas with zoom/pan and node rendering.
 * Renders GraphData from the backend into an interactive visualization.
 */

import * as d3 from 'd3';

// Node dimensions by type
const NODE_CONFIG = {
    file:     { w: 160, h: 40, icon: '📄', color: '#2d333b', border: '#444c56' },
    folder:   { w: 140, h: 36, icon: '📁', color: '#1c1c1c', border: '#484f58' },
    function: { w: 150, h: 36, icon: '⚡', color: '#1a3a2a', border: '#2ea04380' },
    method:   { w: 140, h: 34, icon: '🔧', color: '#1a2a2a', border: '#3fb95080' },
    class:    { w: 160, h: 42, icon: '🏗️', color: '#1a2744', border: '#388bfd80' },
    endpoint: { w: 180, h: 38, icon: '🔌', color: '#2a1a3a', border: '#a371f780' },
    model:    { w: 150, h: 38, icon: '📊', color: '#2a2a1a', border: '#d29922' },
    variable: { w: 120, h: 30, icon: '💎', color: '#2a2a1a', border: '#e3b341' },
    import:   { w: 130, h: 30, icon: '📦', color: '#1c2128', border: '#30363d' },
};

const EDGE_COLORS = {
    imports: '#58a6ff60',
    calls: '#3fb95060',
    extends: '#a371f760',
    implements: '#a371f760',
    data_flow: '#d2992260',
    contains: '#30363d40',
};

export class CanvasEngine {
    constructor(svgSelector) {
        this.svg = d3.select(svgSelector);
        this.container = this.svg.append('g').attr('class', 'canvas-root');
        this.nodesGroup = this.container.append('g').attr('class', 'nodes-layer');
        this.edgesGroup = this.container.append('g').attr('class', 'edges-layer');
        // Ensure edges render below nodes
        this.container.node().insertBefore(this.edgesGroup.node(), this.nodesGroup.node());

        this.zoom = null;
        this.graphData = null;
        this.nodePositions = {};
        this.onNodeClick = null;
        this.onNodeDoubleClick = null;
        this.selectedNodeId = null;

        this._setupZoom();
        this._setupDefs();
    }

    _setupZoom() {
        this.zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on('zoom', (event) => {
                this.container.attr('transform', event.transform);
            });
        this.svg.call(this.zoom);
    }

    _setupDefs() {
        const defs = this.svg.append('defs');

        // Arrow markers for edges
        for (const [type, color] of Object.entries(EDGE_COLORS)) {
            defs.append('marker')
                .attr('id', `arrow-${type}`)
                .attr('viewBox', '0 -5 10 10')
                .attr('refX', 8)
                .attr('refY', 0)
                .attr('markerWidth', 6)
                .attr('markerHeight', 6)
                .attr('orient', 'auto')
                .append('path')
                .attr('d', 'M0,-4L8,0L0,4')
                .attr('fill', color.replace('60', 'aa'));
        }

        // Glow filter
        const glow = defs.append('filter').attr('id', 'glow');
        glow.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur');
        glow.append('feMerge').selectAll('feMergeNode')
            .data(['blur', 'SourceGraphic'])
            .enter().append('feMergeNode')
            .attr('in', d => d);
    }

    /**
     * Render graph data on the canvas.
     * Uses a simple force-directed layout for positioning.
     */
    render(graphData) {
        this.graphData = graphData;
        this.nodesGroup.selectAll('*').remove();
        this.edgesGroup.selectAll('*').remove();

        if (!graphData || !graphData.nodes || graphData.nodes.length === 0) return;

        const nodes = graphData.nodes;
        const edges = graphData.edges;

        // Filter out containment edges for cleaner viz (show structural edges only)
        const visibleEdges = edges.filter(e => e.type !== 'contains');

        // Layout: simple dagre-like positioning
        this._layoutNodes(nodes, edges);

        // Render edges first (behind nodes)
        this._renderEdges(visibleEdges);

        // Render nodes
        this._renderNodes(nodes);

        // Fit to view
        this.fitToView();

        // Update status
        this._updateCounts(nodes, visibleEdges);
    }

    _layoutNodes(nodes, edges) {
        const nodeMap = new Map(nodes.map(n => [n.id, n]));
        
        // Separate by type for layering
        const folders = nodes.filter(n => n.type === 'folder');
        const files = nodes.filter(n => n.type === 'file');
        const others = nodes.filter(n => n.type !== 'file' && n.type !== 'folder');

        // Build containment tree
        const containEdges = edges.filter(e => e.type === 'contains');
        const children = {};
        for (const edge of containEdges) {
            if (!children[edge.source]) children[edge.source] = [];
            children[edge.source].push(edge.target);
        }

        // Position files in a grid layout, grouped by folder
        const GRID_GAP_X = 220;
        const GRID_GAP_Y = 70;

        // Group files by their parent folder
        const folderFiles = {};
        for (const file of files) {
            const parts = file.file_path ? file.file_path.split('/') : [];
            const folderKey = parts.length > 1 ? parts.slice(0, -1).join('/') : '__root__';
            if (!folderFiles[folderKey]) folderFiles[folderKey] = [];
            folderFiles[folderKey].push(file);
        }

        let currentY = 60;
        const COLS = 4;

        for (const [folder, folderFileList] of Object.entries(folderFiles)) {
            // Position folder label
            const folderNode = folders.find(f => f.id === `folder:${folder}`);
            if (folderNode) {
                this.nodePositions[folderNode.id] = { x: 40, y: currentY - 30 };
            }

            // Position files in grid
            for (let i = 0; i < folderFileList.length; i++) {
                const col = i % COLS;
                const row = Math.floor(i / COLS);
                this.nodePositions[folderFileList[i].id] = {
                    x: 60 + col * GRID_GAP_X,
                    y: currentY + row * GRID_GAP_Y,
                };
            }

            currentY += Math.ceil(folderFileList.length / COLS) * GRID_GAP_Y + 40;
        }

        // Position "detail" nodes (for file detail view)
        if (others.length > 0 && files.length <= 1) {
            let detailY = 80;
            for (const node of others) {
                const cfg = NODE_CONFIG[node.type] || NODE_CONFIG.function;
                this.nodePositions[node.id] = {
                    x: 200,
                    y: detailY,
                };
                detailY += cfg.h + 20;
            }
        }
    }

    _renderNodes(nodes) {
        const self = this;

        const nodeGroups = this.nodesGroup.selectAll('.node-group')
            .data(nodes, d => d.id)
            .enter()
            .append('g')
            .attr('class', 'node-group')
            .attr('transform', d => {
                const pos = this.nodePositions[d.id] || { x: 0, y: 0 };
                return `translate(${pos.x}, ${pos.y})`;
            })
            .on('click', function (event, d) {
                event.stopPropagation();
                self._selectNode(d.id);
                if (self.onNodeClick) self.onNodeClick(d);
            })
            .on('dblclick', function (event, d) {
                event.stopPropagation();
                if (self.onNodeDoubleClick) self.onNodeDoubleClick(d);
            });

        // Make nodes draggable
        nodeGroups.call(
            d3.drag()
                .on('start', function (event) {
                    d3.select(this).raise();
                })
                .on('drag', function (event, d) {
                    const pos = self.nodePositions[d.id] || { x: 0, y: 0 };
                    pos.x = event.x;
                    pos.y = event.y;
                    d3.select(this).attr('transform', `translate(${pos.x}, ${pos.y})`);
                    self._updateEdges();
                })
        );

        // Background rect
        nodeGroups.append('rect')
            .attr('class', 'node-rect')
            .attr('width', d => (NODE_CONFIG[d.type] || NODE_CONFIG.file).w)
            .attr('height', d => (NODE_CONFIG[d.type] || NODE_CONFIG.file).h)
            .attr('fill', d => {
                if (d.status === 'failed') return NODE_CONFIG.file.color;
                return (NODE_CONFIG[d.type] || NODE_CONFIG.file).color;
            })
            .attr('stroke', d => {
                if (d.status === 'failed') return '#f85149';
                return (NODE_CONFIG[d.type] || NODE_CONFIG.file).border;
            })
            .attr('stroke-width', d => d.id === self.selectedNodeId ? 2.5 : 1.5);

        // Icon
        nodeGroups.append('text')
            .attr('class', 'node-icon')
            .attr('x', 14)
            .attr('y', d => (NODE_CONFIG[d.type] || NODE_CONFIG.file).h / 2)
            .text(d => {
                if (d.status === 'failed') return '⚠️';
                return (NODE_CONFIG[d.type] || NODE_CONFIG.file).icon;
            });

        // Label
        nodeGroups.append('text')
            .attr('class', 'node-label')
            .attr('x', d => (NODE_CONFIG[d.type] || NODE_CONFIG.file).w / 2 + 8)
            .attr('y', d => (NODE_CONFIG[d.type] || NODE_CONFIG.file).h / 2)
            .text(d => {
                const maxLen = 18;
                return d.label.length > maxLen ? d.label.slice(0, maxLen) + '…' : d.label;
            })
            .attr('text-anchor', 'middle');

        // Native tooltip on hover
        nodeGroups.append('title')
            .text(d => {
                let tip = `${d.label} (${d.type})`;
                if (d.description) tip += `\n${d.description}`;
                if (d.confidence != null) tip += `\nConfidence: ${(d.confidence * 100).toFixed(0)}%`;
                return tip;
            });

        // Confidence indicator (small dot)
        nodeGroups.filter(d => d.confidence != null)
            .append('circle')
            .attr('cx', d => (NODE_CONFIG[d.type] || NODE_CONFIG.file).w - 10)
            .attr('cy', 10)
            .attr('r', 4)
            .attr('fill', d => {
                if (d.confidence > 0.8) return '#3fb950';
                if (d.confidence > 0.5) return '#d29922';
                return '#f85149';
            })
            .attr('opacity', 0.8);
    }

    _renderEdges(edges) {
        const self = this;

        this.edgesGroup.selectAll('.edge-line')
            .data(edges, d => d.id)
            .enter()
            .append('line')
            .attr('class', d => `edge-line ${d.animated ? 'animated' : ''}`)
            .attr('x1', d => {
                const pos = self.nodePositions[d.source];
                const cfg = self._getNodeConfig(d.source);
                return pos ? pos.x + cfg.w : 0;
            })
            .attr('y1', d => {
                const pos = self.nodePositions[d.source];
                const cfg = self._getNodeConfig(d.source);
                return pos ? pos.y + cfg.h / 2 : 0;
            })
            .attr('x2', d => {
                const pos = self.nodePositions[d.target];
                return pos ? pos.x : 0;
            })
            .attr('y2', d => {
                const pos = self.nodePositions[d.target];
                const cfg = self._getNodeConfig(d.target);
                return pos ? pos.y + cfg.h / 2 : 0;
            })
            .attr('stroke', d => EDGE_COLORS[d.type] || EDGE_COLORS.imports)
            .attr('marker-end', d => `url(#arrow-${d.type || 'imports'})`);
    }

    _getNodeConfig(nodeId) {
        if (!this.graphData) return NODE_CONFIG.file;
        const node = this.graphData.nodes.find(n => n.id === nodeId);
        if (!node) return NODE_CONFIG.file;
        return NODE_CONFIG[node.type] || NODE_CONFIG.file;
    }

    _updateEdges() {
        const self = this;
        this.edgesGroup.selectAll('.edge-line')
            .attr('x1', d => {
                const pos = self.nodePositions[d.source];
                const cfg = self._getNodeConfig(d.source);
                return pos ? pos.x + cfg.w : 0;
            })
            .attr('y1', d => {
                const pos = self.nodePositions[d.source];
                const cfg = self._getNodeConfig(d.source);
                return pos ? pos.y + cfg.h / 2 : 0;
            })
            .attr('x2', d => {
                const pos = self.nodePositions[d.target];
                return pos ? pos.x : 0;
            })
            .attr('y2', d => {
                const pos = self.nodePositions[d.target];
                const cfg = self._getNodeConfig(d.target);
                return pos ? pos.y + cfg.h / 2 : 0;
            });
    }

    _selectNode(nodeId) {
        this.selectedNodeId = nodeId;
        this.nodesGroup.selectAll('.node-rect')
            .attr('stroke-width', d => d.id === nodeId ? 2.5 : 1.5)
            .attr('filter', d => d.id === nodeId ? 'url(#glow)' : null);
    }

    fitToView(padding = 60) {
        const bbox = this.container.node().getBBox();
        if (bbox.width === 0 || bbox.height === 0) return;

        const svgEl = this.svg.node();
        const { width, height } = svgEl.getBoundingClientRect();

        const scale = Math.min(
            (width - padding * 2) / bbox.width,
            (height - padding * 2) / bbox.height,
            1.5
        );
        const tx = (width - bbox.width * scale) / 2 - bbox.x * scale;
        const ty = (height - bbox.height * scale) / 2 - bbox.y * scale;

        this.svg.transition().duration(500)
            .call(this.zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }

    _updateCounts(nodes, edges) {
        const nodeCount = document.getElementById('node-count');
        const edgeCount = document.getElementById('edge-count');
        if (nodeCount) nodeCount.textContent = `${nodes.length} nodes`;
        if (edgeCount) edgeCount.textContent = `${edges.length} edges`;
    }

    clear() {
        this.nodesGroup.selectAll('*').remove();
        this.edgesGroup.selectAll('*').remove();
        this.graphData = null;
        this.nodePositions = {};
    }

    /**
     * Highlight nodes matching a search query.
     */
    highlightSearch(query) {
        if (!query) {
            this.nodesGroup.selectAll('.node-rect').attr('opacity', 1);
            return [];
        }

        const lower = query.toLowerCase();
        const matches = [];

        this.nodesGroup.selectAll('.node-group').each(function (d) {
            const match = d.label.toLowerCase().includes(lower) ||
                          (d.description && d.description.toLowerCase().includes(lower));
            d3.select(this).select('.node-rect').attr('opacity', match ? 1 : 0.2);
            if (match) matches.push(d);
        });

        return matches;
    }
}
