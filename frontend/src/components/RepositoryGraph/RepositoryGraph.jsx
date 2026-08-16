import { useEffect, useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react'
import dagre from '@dagrejs/dagre'

import '@xyflow/react/dist/style.css'
import './RepositoryGraph.css'

const NODE_WIDTH = 190
const NODE_HEIGHT = 52

function layoutNodes(nodes, edges, direction) {
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({ rankdir: direction, nodesep: 32, ranksep: 72 })
  graph.setDefaultEdgeLabel(() => ({}))

  nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }))
  edges.forEach((edge) => {
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
      graph.setEdge(edge.source, edge.target)
    }
  })

  dagre.layout(graph)

  return nodes.map((node) => {
    const position = graph.node(node.id)
    return { ...node, position: { x: position.x - NODE_WIDTH / 2, y: position.y - NODE_HEIGHT / 2 } }
  })
}

function nodeClassName(type, selected, dimmed) {
  return ['graph-node', `graph-node-${type}`, selected ? 'graph-node-selected' : '', dimmed ? 'graph-node-dimmed' : '']
    .filter(Boolean)
    .join(' ')
}

function FileNode({ data, selected }) {
  return (
    <div className={nodeClassName('file', selected, data.dimmed)}>
      <Handle type="target" position={Position.Top} />
      <span className="graph-node-label">{data.label}</span>
      {data.language && <span className="graph-node-meta">{data.language}</span>}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function FolderNode({ data, selected }) {
  return (
    <div className={nodeClassName('folder', selected, data.dimmed)}>
      <Handle type="target" position={Position.Top} />
      <span className="graph-node-label">{data.label}</span>
      {data.file_count != null && <span className="graph-node-meta">{data.file_count} files</span>}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function ExternalNode({ data, selected }) {
  return (
    <div className={nodeClassName('external', selected, data.dimmed)}>
      <Handle type="target" position={Position.Top} />
      <span className="graph-node-label">{data.label}</span>
      <span className="graph-node-meta">external</span>
    </div>
  )
}

const nodeTypes = { file: FileNode, folder: FolderNode, external: ExternalNode }

function edgeColor(type) {
  return type === 'calls' ? 'var(--success)' : 'var(--accent)'
}

function GraphCanvas({ nodes, edges, direction, selectedNodeId, highlightedIds, onNodeClick, fitSignal, centerRequest }) {
  const { fitView, setCenter } = useReactFlow()

  const positionedNodes = useMemo(() => {
    const decorated = nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        dimmed: Boolean(highlightedIds && highlightedIds.size > 0 && !highlightedIds.has(node.id)),
      },
      selected: node.id === selectedNodeId,
    }))
    return layoutNodes(decorated, edges, direction)
  }, [nodes, edges, direction, highlightedIds, selectedNodeId])

  const styledEdges = useMemo(
    () =>
      edges.map((edge) => {
        const dimmed = Boolean(
          highlightedIds && highlightedIds.size > 0 && !(highlightedIds.has(edge.source) && highlightedIds.has(edge.target)),
        )
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          style: {
            stroke: edgeColor(edge.type),
            strokeWidth: Math.min(1 + Math.log2(edge.weight + 1), 4),
            strokeDasharray: edge.type === 'calls' ? '4 3' : undefined,
            opacity: dimmed ? 0.12 : 0.55,
          },
        }
      }),
    [edges, highlightedIds],
  )

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(positionedNodes)
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(styledEdges)

  useEffect(() => setRfNodes(positionedNodes), [positionedNodes, setRfNodes])
  useEffect(() => setRfEdges(styledEdges), [styledEdges, setRfEdges])

  useEffect(() => {
    if (fitSignal === undefined) return
    const timer = setTimeout(() => fitView({ padding: 0.2, duration: 300, minZoom: 0.5 }), 0)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitSignal])

  useEffect(() => {
    if (!centerRequest?.nodeId) return
    const node = positionedNodes.find((n) => n.id === centerRequest.nodeId)
    if (!node) return
    const timer = setTimeout(
      () => setCenter(node.position.x + NODE_WIDTH / 2, node.position.y + NODE_HEIGHT / 2, { zoom: 1.1, duration: 400 }),
      0,
    )
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerRequest])

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onNodeClick?.(node)}
      fitView
      fitViewOptions={{ padding: 0.2, minZoom: 0.5 }}
      minZoom={0.1}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={24} size={1} color="var(--card-border)" />
      <MiniMap
        pannable
        zoomable
        className="graph-minimap"
        bgColor="#111114"
        maskColor="rgba(110, 123, 242, 0.15)"
        nodeColor={() => '#6e7bf2'}
        nodeStrokeWidth={0}
      />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}

export function RepositoryGraph({
  nodes,
  edges,
  direction = 'TB',
  selectedNodeId,
  highlightedIds,
  onNodeClick,
  fitSignal,
  centerRequest,
}) {
  return (
    <div className="repository-graph">
      <ReactFlowProvider>
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          direction={direction}
          selectedNodeId={selectedNodeId}
          highlightedIds={highlightedIds}
          onNodeClick={onNodeClick}
          fitSignal={fitSignal}
          centerRequest={centerRequest}
        />
      </ReactFlowProvider>
    </div>
  )
}
