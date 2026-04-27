import { useDeferredValue, useEffect, useMemo, useRef, useState, startTransition } from 'react'
import { Layers3, Loader2, Maximize2, Move, Network, RefreshCw, Search, Sparkles, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { useGraph, useJob, useNodeDetail, useStartGraphRebuild } from '../hooks/queries'
import type { GraphData, KGEdge, KGNode } from '../types'

const TYPE_COLORS: Record<KGNode['type'], string> = {
  project: '#2f6fed',
  person: '#159875',
  concept: '#7a4cf4',
  tool: '#d97706',
  topic: '#0f98b5',
}

const TYPE_PASTELS: Record<KGNode['type'], string> = {
  project: '#e8f0ff',
  person: '#e8fbf6',
  concept: '#f1ebff',
  tool: '#fff2df',
  topic: '#e3f7fb',
}

const TYPE_LABELS: Record<KGNode['type'], string> = {
  project: '项目',
  person: '人物',
  concept: '概念',
  tool: '工具',
  topic: '主题',
}

const TYPE_ORDER: KGNode['type'][] = ['project', 'concept', 'tool', 'topic', 'person']

const CORE_NODE_LIMIT = 42
const CORE_EDGE_LIMIT = 80
const SEARCH_NODE_LIMIT = 70
const FOCUS_NODE_LIMIT = 80

type ViewMode = 'core' | 'all'

type SigmaNodeAttrs = {
  id: string
  label: string
  type: KGNode['type']
  mentionCount: number
  x: number
  y: number
  size: number
  color: string
}

type SigmaEdgeAttrs = {
  id: string
  source: string
  target: string
  relation: string
  weight: number
  size: number
  color: string
}

type ForceLayoutState = {
  velocities: Map<string, { x: number; y: number }>
}

function hashNumber(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return hash
}

function buildClusterPositions(nodes: KGNode[]) {
  const grouped = new Map<KGNode['type'], KGNode[]>()
  for (const type of TYPE_ORDER) grouped.set(type, [])
  for (const node of nodes) grouped.get(node.type)?.push(node)

  const clusterRadius = 9
  const centers = new Map<KGNode['type'], { x: number; y: number }>()
  TYPE_ORDER.forEach((type, index) => {
    const angle = (Math.PI * 2 * index) / TYPE_ORDER.length - Math.PI / 2
    centers.set(type, {
      x: Math.cos(angle) * clusterRadius,
      y: Math.sin(angle) * clusterRadius,
    })
  })

  const positions = new Map<string, { x: number; y: number }>()
  for (const type of TYPE_ORDER) {
    const cluster = (grouped.get(type) ?? [])
      .slice()
      .sort((left, right) => (right.mention_count ?? 0) - (left.mention_count ?? 0))
    const center = centers.get(type) ?? { x: 0, y: 0 }

    cluster.forEach((node, index) => {
      const jitter = hashNumber(node.id) / 0xffffffff
      const angle = index * 2.399963229728653 + jitter * 0.7
      const distance = 1.4 + Math.sqrt(index + 1) * 0.9
      positions.set(node.id, {
        x: center.x + Math.cos(angle) * distance,
        y: center.y + Math.sin(angle) * distance,
      })
    })
  }

  return positions
}

function buildSigmaData(graphData: GraphData) {
  const positions = buildClusterPositions(graphData.nodes)

  const nodes: SigmaNodeAttrs[] = graphData.nodes.map(node => {
    const position = positions.get(node.id) ?? { x: 0, y: 0 }
    return {
      id: node.id,
      label: node.name,
      type: node.type,
      mentionCount: node.mention_count,
      x: position.x,
      y: position.y,
      size: Math.max(4, Math.sqrt(node.mention_count || 1) * 1.7),
      color: TYPE_COLORS[node.type],
    }
  })

  const edges: SigmaEdgeAttrs[] = graphData.edges.map((edge, index) => ({
    id: `${edge.source}-${edge.target}-${edge.relation}-${index}`,
    source: edge.source,
    target: edge.target,
    relation: edge.relation,
    weight: edge.weight,
    size: Math.max(1, Math.min(5, 0.8 + edge.weight * 0.35)),
    color: '#d7dce5',
  }))

  return { nodes, edges }
}

function getNeighborhoodNodeIds(nodeId: string | null, neighborMap: Map<string, Set<string>>) {
  const ids = new Set<string>()
  if (!nodeId) return ids

  ids.add(nodeId)
  for (const neighborId of neighborMap.get(nodeId) ?? []) ids.add(neighborId)

  return ids
}

function buildNeighborMap(nodes: KGNode[], edges: KGEdge[]) {
  const map = new Map<string, Set<string>>()
  for (const node of nodes) map.set(node.id, new Set())
  for (const edge of edges) {
    map.get(edge.source)?.add(edge.target)
    map.get(edge.target)?.add(edge.source)
  }
  return map
}

function buildDegreeMap(nodes: KGNode[], edges: KGEdge[]) {
  const map = new Map<string, number>()
  for (const node of nodes) map.set(node.id, 0)
  for (const edge of edges) {
    map.set(edge.source, (map.get(edge.source) ?? 0) + 1)
    map.set(edge.target, (map.get(edge.target) ?? 0) + 1)
  }
  return map
}

function nodeImportance(node: KGNode, degreeMap: Map<string, number>) {
  return (node.mention_count ?? 0) * 3 + (degreeMap.get(node.id) ?? 0) * 2
}

function sortedNodesByImportance(nodes: KGNode[], degreeMap: Map<string, number>) {
  return nodes.slice().sort((left, right) => {
    const scoreDiff = nodeImportance(right, degreeMap) - nodeImportance(left, degreeMap)
    if (scoreDiff !== 0) return scoreDiff
    return left.name.localeCompare(right.name)
  })
}

function selectEdges(
  edges: KGEdge[],
  visibleNodeIds: Set<string>,
  scoreMap: Map<string, number>,
  limit?: number,
) {
  const selected = edges
    .filter(edge => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
    .sort((left, right) => {
      const leftScore = left.weight * 6 + (scoreMap.get(left.source) ?? 0) + (scoreMap.get(left.target) ?? 0)
      const rightScore = right.weight * 6 + (scoreMap.get(right.source) ?? 0) + (scoreMap.get(right.target) ?? 0)
      return rightScore - leftScore
    })

  return typeof limit === 'number' ? selected.slice(0, limit) : selected
}

function capNodeSet(
  candidateIds: Set<string>,
  pinnedIds: Set<string>,
  nodesById: Map<string, KGNode>,
  degreeMap: Map<string, number>,
  limit: number,
) {
  const result = new Set<string>()
  for (const id of pinnedIds) {
    if (nodesById.has(id)) result.add(id)
  }

  const candidates = Array.from(candidateIds)
    .filter(id => !result.has(id))
    .map(id => nodesById.get(id))
    .filter((node): node is KGNode => Boolean(node))

  for (const node of sortedNodesByImportance(candidates, degreeMap)) {
    if (result.size >= limit) break
    result.add(node.id)
  }

  return result
}

function buildDisplayBounds(
  points: Array<{ x: number; y: number }>,
  options?: { minSpan?: number; paddingRatio?: number },
) {
  const minSpan = options?.minSpan ?? 0.14
  const paddingRatio = options?.paddingRatio ?? 0.24

  if (points.length === 0) {
    return { x: 0.5, y: 0.5, ratio: 1 }
  }

  const xs = points.map(point => point.x)
  const ys = points.map(point => point.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const span = Math.max(maxX - minX, maxY - minY, minSpan)
  const paddedSpan = span * (1 + paddingRatio * 2)

  return {
    x: (minX + maxX) / 2,
    y: (minY + maxY) / 2,
    ratio: paddedSpan,
  }
}

function focusNodesInViewport(renderer: any, nodeIds: Iterable<string>) {
  if (!renderer) return

  const points = Array.from(nodeIds)
    .map(nodeId => renderer.getNodeDisplayData?.(nodeId))
    .filter((node): node is { x: number; y: number } => Boolean(node))

  if (points.length === 0) return

  const camera = renderer.getCamera()
  const nextState = buildDisplayBounds(points)
  const ratio = typeof camera.getBoundedRatio === 'function'
    ? camera.getBoundedRatio(nextState.ratio)
    : nextState.ratio

  if (typeof camera.animate === 'function') {
    camera.animate({ x: nextState.x, y: nextState.y, ratio }, { duration: 350 })
    return
  }

  if (typeof camera.setState === 'function') {
    camera.setState({ x: nextState.x, y: nextState.y, ratio })
  }
}

function resetViewport(renderer: any) {
  const camera = renderer?.getCamera?.()
  if (!camera) return

  if (typeof camera.animatedReset === 'function') {
    camera.animatedReset({ duration: 250 })
    return
  }

  if (typeof camera.animate === 'function') {
    camera.animate({ x: 0.5, y: 0.5, ratio: 1, angle: 0 }, { duration: 250 })
    return
  }

  if (typeof camera.setState === 'function') {
    camera.setState({ x: 0.5, y: 0.5, ratio: 1, angle: 0 })
  }
}

function getGraphPosition(graph: any, nodeId: string) {
  return {
    x: Number(graph.getNodeAttribute(nodeId, 'x') ?? 0),
    y: Number(graph.getNodeAttribute(nodeId, 'y') ?? 0),
  }
}

function runForceLayoutFrame(graph: any, state: ForceLayoutState, pinnedNodeId: string | null) {
  const nodes = graph.nodes() as string[]
  if (nodes.length < 2) return

  const positions = new Map<string, { x: number; y: number }>()
  const forces = new Map<string, { x: number; y: number }>()
  for (const nodeId of nodes) {
    positions.set(nodeId, getGraphPosition(graph, nodeId))
    forces.set(nodeId, { x: 0, y: 0 })
  }

  const repulsion = nodes.length > 120 ? 5.4 : 7.2
  const maxStep = nodes.length > 120 ? 0.42 : 0.62
  const damping = 0.72

  for (let i = 0; i < nodes.length; i += 1) {
    const source = nodes[i]
    const sourcePos = positions.get(source)!
    for (let j = i + 1; j < nodes.length; j += 1) {
      const target = nodes[j]
      const targetPos = positions.get(target)!
      const dx = sourcePos.x - targetPos.x
      const dy = sourcePos.y - targetPos.y
      const distanceSq = Math.max(dx * dx + dy * dy, 0.35)
      const distance = Math.sqrt(distanceSq)
      const force = repulsion / distanceSq
      const fx = (dx / distance) * force
      const fy = (dy / distance) * force
      const sourceForce = forces.get(source)!
      const targetForce = forces.get(target)!
      sourceForce.x += fx
      sourceForce.y += fy
      targetForce.x -= fx
      targetForce.y -= fy
    }
  }

  for (const edgeId of graph.edges() as string[]) {
    const source = graph.source(edgeId)
    const target = graph.target(edgeId)
    const sourcePos = positions.get(source)
    const targetPos = positions.get(target)
    if (!sourcePos || !targetPos) continue

    const dx = targetPos.x - sourcePos.x
    const dy = targetPos.y - sourcePos.y
    const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01)
    const weight = Number(graph.getEdgeAttribute(edgeId, 'weight') ?? 1)
    const targetLength = 2.2 + Math.min(2.4, 1.8 / Math.max(weight, 1))
    const force = (distance - targetLength) * 0.018 * Math.min(weight, 5)
    const fx = (dx / distance) * force
    const fy = (dy / distance) * force
    const sourceForce = forces.get(source)!
    const targetForce = forces.get(target)!
    sourceForce.x += fx
    sourceForce.y += fy
    targetForce.x -= fx
    targetForce.y -= fy
  }

  for (const nodeId of nodes) {
    if (nodeId === pinnedNodeId) continue
    const position = positions.get(nodeId)!
    const force = forces.get(nodeId)!
    force.x += -position.x * 0.004
    force.y += -position.y * 0.004

    const previousVelocity = state.velocities.get(nodeId) ?? { x: 0, y: 0 }
    const nextVelocity = {
      x: (previousVelocity.x + force.x) * damping,
      y: (previousVelocity.y + force.y) * damping,
    }
    const velocityLength = Math.max(Math.sqrt(nextVelocity.x * nextVelocity.x + nextVelocity.y * nextVelocity.y), 0.001)
    const stepScale = Math.min(1, maxStep / velocityLength)
    nextVelocity.x *= stepScale
    nextVelocity.y *= stepScale
    state.velocities.set(nodeId, nextVelocity)

    graph.mergeNodeAttributes(nodeId, {
      x: position.x + nextVelocity.x,
      y: position.y + nextVelocity.y,
    })
  }
}

export default function KnowledgePage() {
  const { data: graphData, isLoading, refetch } = useGraph()
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('core')
  const [filters, setFilters] = useState<Record<KGNode['type'], boolean>>({
    project: true,
    person: true,
    concept: true,
    tool: true,
    topic: true,
  })
  const deferredSearch = useDeferredValue(searchInput.trim().toLowerCase())
  const [rendererReady, setRendererReady] = useState(false)
  const [layoutRunning, setLayoutRunning] = useState(false)
  const [useSvgFallback, setUseSvgFallback] = useState(false)
  const { data: nodeDetail } = useNodeDetail(selectedNode)
  const rebuildMut = useStartGraphRebuild()
  const { data: rebuildJob } = useJob(jobId, !!jobId)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const sigmaRef = useRef<any>(null)
  const graphRef = useRef<any>(null)
  const baseNodeAttrsRef = useRef<Map<string, SigmaNodeAttrs>>(new Map())
  const baseEdgeAttrsRef = useRef<Map<string, SigmaEdgeAttrs>>(new Map())
  const draggedNodeRef = useRef<string | null>(null)
  const dragStartViewportRef = useRef<{ x: number; y: number } | null>(null)
  const dragMovedRef = useRef(false)
  const layoutFrameRef = useRef<number | null>(null)
  const forceLayoutStateRef = useRef<ForceLayoutState>({ velocities: new Map() })

  const filteredBaseData = useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] }

    const nodes = graphData.nodes.filter(node => filters[node.type])
    const visibleNodeIds = new Set(nodes.map(node => node.id))
    const edges = graphData.edges.filter(
      edge => visibleNodeIds.has(String(edge.source)) && visibleNodeIds.has(String(edge.target)),
    )

    return { nodes, edges }
  }, [filters, graphData])

  const baseNeighborMap = useMemo(
    () => buildNeighborMap(filteredBaseData.nodes, filteredBaseData.edges),
    [filteredBaseData.edges, filteredBaseData.nodes],
  )

  const baseDegreeMap = useMemo(
    () => buildDegreeMap(filteredBaseData.nodes, filteredBaseData.edges),
    [filteredBaseData.edges, filteredBaseData.nodes],
  )

  const scoreMap = useMemo(() => {
    const map = new Map<string, number>()
    for (const node of filteredBaseData.nodes) map.set(node.id, nodeImportance(node, baseDegreeMap))
    return map
  }, [baseDegreeMap, filteredBaseData.nodes])

  const nodeStats = useMemo(() => {
    return TYPE_ORDER.map(type => ({
      type,
      label: TYPE_LABELS[type],
      count: filteredBaseData.nodes.filter(node => node.type === type).length,
    }))
  }, [filteredBaseData.nodes])

  const searchMatches = useMemo(() => {
    if (!deferredSearch) return []
    return filteredBaseData.nodes
      .filter(node => node.name.toLowerCase().includes(deferredSearch))
      .sort((left, right) => nodeImportance(right, baseDegreeMap) - nodeImportance(left, baseDegreeMap))
      .slice(0, 8)
  }, [baseDegreeMap, deferredSearch, filteredBaseData.nodes])
  const searchHighlightIds = useMemo(
    () => new Set(searchMatches.map(node => node.id)),
    [searchMatches],
  )

  const displayData = useMemo(() => {
    const nodesById = new Map(filteredBaseData.nodes.map(node => [node.id, node]))
    let visibleNodeIds: Set<string>
    let edgeLimit: number | undefined

    if (selectedNode && nodesById.has(selectedNode)) {
      visibleNodeIds = capNodeSet(
        getNeighborhoodNodeIds(selectedNode, baseNeighborMap),
        new Set([selectedNode]),
        nodesById,
        baseDegreeMap,
        FOCUS_NODE_LIMIT,
      )
      edgeLimit = 140
    } else if (searchHighlightIds.size > 0) {
      const candidateIds = new Set<string>()
      for (const nodeId of searchHighlightIds) {
        candidateIds.add(nodeId)
        for (const neighborId of baseNeighborMap.get(nodeId) ?? []) candidateIds.add(neighborId)
      }
      visibleNodeIds = capNodeSet(candidateIds, searchHighlightIds, nodesById, baseDegreeMap, SEARCH_NODE_LIMIT)
      edgeLimit = 120
    } else if (viewMode === 'core') {
      visibleNodeIds = new Set(
        sortedNodesByImportance(filteredBaseData.nodes, baseDegreeMap)
          .slice(0, CORE_NODE_LIMIT)
          .map(node => node.id),
      )
      edgeLimit = CORE_EDGE_LIMIT
    } else {
      visibleNodeIds = new Set(filteredBaseData.nodes.map(node => node.id))
    }

    const nodes = filteredBaseData.nodes.filter(node => visibleNodeIds.has(node.id))
    const edges = selectEdges(filteredBaseData.edges, visibleNodeIds, scoreMap, edgeLimit)

    return { nodes, edges }
  }, [
    baseDegreeMap,
    baseNeighborMap,
    filteredBaseData.edges,
    filteredBaseData.nodes,
    scoreMap,
    searchHighlightIds,
    selectedNode,
    viewMode,
  ])

  const sigmaData = useMemo(() => buildSigmaData(displayData), [displayData])

  const neighborMap = baseNeighborMap
  const focusedNodeIds = useMemo(
    () => getNeighborhoodNodeIds(selectedNode, neighborMap),
    [neighborMap, selectedNode],
  )

  useEffect(() => {
    if (!selectedNode || filteredBaseData.nodes.some(node => node.id === selectedNode)) return
    setSelectedNode(null)
  }, [filteredBaseData.nodes, selectedNode])

  useEffect(() => {
    if (sigmaData.nodes.length === 0) {
      setRendererReady(false)
      setUseSvgFallback(false)
      return
    }

    if (!containerRef.current) return

    if (typeof window === 'undefined' || typeof window.WebGL2RenderingContext === 'undefined') {
      setRendererReady(false)
      setUseSvgFallback(true)
      return
    }

    let disposed = false
    setRendererReady(false)
    setUseSvgFallback(false)

    const loadRenderer = async () => {
      try {
        const [sigmaModule, graphologyModule] = await Promise.all([
          import('sigma'),
          import('graphology'),
        ])
        const SigmaClass = (sigmaModule.default ?? (sigmaModule as { Sigma?: unknown }).Sigma) as any
        const GraphClass = (graphologyModule.default ?? (graphologyModule as { Graph?: unknown }).Graph) as any
        if (!SigmaClass || !GraphClass || disposed || !containerRef.current) return

        const graph = new GraphClass({ multi: true })
        const nodeAttrs = new Map<string, SigmaNodeAttrs>()
        const edgeAttrs = new Map<string, SigmaEdgeAttrs>()

        for (const node of sigmaData.nodes) {
          nodeAttrs.set(node.id, node)
          graph.addNode(node.id, {
            x: node.x,
            y: node.y,
            size: node.size,
            color: node.color,
            label: node.label,
            type: 'circle',
            zIndex: Math.round(node.mentionCount || 1),
          })
        }

        for (const edge of sigmaData.edges) {
          if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue
          edgeAttrs.set(edge.id, edge)
          graph.addEdgeWithKey(edge.id, edge.source, edge.target, {
            size: edge.size,
            color: edge.color,
            label: edge.relation,
            weight: edge.weight,
            zIndex: Math.round(edge.weight || 1),
          })
        }

        const renderer = new SigmaClass(graph, containerRef.current, {
          allowInvalidContainer: true,
          defaultEdgeColor: '#d7dce5',
          defaultNodeColor: '#9ca3af',
          labelDensity: 0.08,
          labelGridCellSize: 120,
          labelRenderedSizeThreshold: 11,
          renderEdgeLabels: false,
          zIndex: true,
        })

        renderer.on('clickNode', ({ node }: { node: string }) => {
          if (dragMovedRef.current) {
            dragMovedRef.current = false
            return
          }
          startTransition(() => setSelectedNode(node))
          focusNodesInViewport(renderer, getNeighborhoodNodeIds(node, neighborMap))
        })
        renderer.on('enterNode', ({ node }: { node: string }) => setHoveredNode(node))
        renderer.on('leaveNode', () => setHoveredNode(null))
        renderer.on('clickStage', () => {
          setSelectedNode(null)
          setHoveredNode(null)
          resetViewport(renderer)
        })

        const startNodeDrag = (node: string, event?: any) => {
          if (!graph.hasNode(node)) return
          draggedNodeRef.current = node
          dragStartViewportRef.current = typeof event?.x === 'number' && typeof event?.y === 'number'
            ? { x: event.x, y: event.y }
            : null
          dragMovedRef.current = false
          graph.mergeNodeAttributes(node, { highlighted: true })
          event?.preventSigmaDefault?.()
          event?.original?.preventDefault?.()
          event?.original?.stopPropagation?.()
        }

        const finishNodeDrag = () => {
          const node = draggedNodeRef.current
          if (!node) return
          graph.mergeNodeAttributes(node, { highlighted: false })
          draggedNodeRef.current = null
          dragStartViewportRef.current = null
          renderer.refresh()
          window.setTimeout(() => {
            dragMovedRef.current = false
          }, 0)
        }

        renderer.on('downNode', ({ node, event }: { node: string; event?: any }) => {
          startNodeDrag(node, event)
        })

        const mouseCaptor = renderer.getMouseCaptor?.()
        mouseCaptor?.on?.('mousedown', (event: any) => {
          if (draggedNodeRef.current) return
          const node = renderer.getNodeAtPosition?.(event)
          if (node) startNodeDrag(node, event)
        })
        mouseCaptor?.on?.('mousemovebody', (event: any) => {
          const node = draggedNodeRef.current
          if (!node) return
          const position = renderer.viewportToGraph?.(event)
          if (!position) return

          const dragStart = dragStartViewportRef.current
          if (!dragStart || Math.hypot(event.x - dragStart.x, event.y - dragStart.y) > 3) {
            dragMovedRef.current = true
          }
          graph.mergeNodeAttributes(node, {
            x: position.x,
            y: position.y,
            highlighted: true,
          })
          forceLayoutStateRef.current.velocities.set(node, { x: 0, y: 0 })
          renderer.refresh()
          event?.preventSigmaDefault?.()
          event?.original?.preventDefault?.()
          event?.original?.stopPropagation?.()
        })
        mouseCaptor?.on?.('mouseup', finishNodeDrag)
        mouseCaptor?.on?.('mouseleave', finishNodeDrag)

        sigmaRef.current = renderer
        graphRef.current = graph
        baseNodeAttrsRef.current = nodeAttrs
        baseEdgeAttrsRef.current = edgeAttrs
        forceLayoutStateRef.current = { velocities: new Map() }
        setRendererReady(true)
      } catch (error) {
        console.error('Failed to initialize Sigma renderer', error)
        if (!disposed) {
          setRendererReady(false)
          setUseSvgFallback(true)
        }
      }
    }

    loadRenderer()

    return () => {
      disposed = true
      setRendererReady(false)
      if (layoutFrameRef.current !== null) {
        cancelAnimationFrame(layoutFrameRef.current)
        layoutFrameRef.current = null
      }
      setLayoutRunning(false)
      draggedNodeRef.current = null
      sigmaRef.current?.kill?.()
      sigmaRef.current = null
      graphRef.current = null
    }
  }, [neighborMap, sigmaData])

  useEffect(() => {
    const graph = graphRef.current
    const renderer = sigmaRef.current
    if (!graph || !renderer) return

    const activeNodeId = selectedNode ?? hoveredNode
    const emphasizedNodeIds = activeNodeId
      ? getNeighborhoodNodeIds(activeNodeId, neighborMap)
      : new Set<string>()

    if (!activeNodeId && searchHighlightIds.size > 0) {
      for (const nodeId of searchHighlightIds) emphasizedNodeIds.add(nodeId)
    }

    const shouldDim = emphasizedNodeIds.size > 0

    for (const [nodeId, base] of baseNodeAttrsRef.current.entries()) {
      const isSelected = nodeId === selectedNode
      const isHovered = nodeId === hoveredNode
      const isMatch = searchHighlightIds.has(nodeId)
      const isEmphasized = emphasizedNodeIds.has(nodeId)

      graph.mergeNodeAttributes(nodeId, {
        color: shouldDim && !isEmphasized ? '#d9dee7' : base.color,
        label: isSelected || isHovered || isMatch || base.mentionCount >= 10 ? base.label : '',
        size: isSelected ? base.size * 1.45 : isHovered || isMatch ? base.size * 1.2 : shouldDim && !isEmphasized ? Math.max(2.5, base.size * 0.8) : base.size,
        zIndex: isSelected ? 1000 : isHovered ? 900 : Math.round(base.mentionCount || 1),
      })
    }

    for (const [edgeId, base] of baseEdgeAttrsRef.current.entries()) {
      const touchesActive = activeNodeId
        ? base.source === activeNodeId || base.target === activeNodeId
        : searchHighlightIds.has(base.source) && searchHighlightIds.has(base.target)

      graph.mergeEdgeAttributes(edgeId, {
        color: activeNodeId
          ? touchesActive ? '#9fb4ff' : '#edf1f6'
          : searchHighlightIds.size > 0
            ? touchesActive ? '#aac7ff' : '#edf1f6'
            : base.color,
        size: touchesActive ? Math.min(base.size * 1.8, 6) : base.size,
        hidden: shouldDim && !touchesActive && !!activeNodeId,
        zIndex: touchesActive ? 500 : Math.round(base.weight || 1),
      })
    }

    renderer.refresh()
  }, [hoveredNode, neighborMap, searchHighlightIds, selectedNode])

  useEffect(() => {
    if (!jobId || !rebuildJob) return

    if (rebuildJob.status === 'completed') {
      setJobId(null)
      refetch()
      toast.success('图谱重建完成')
      return
    }

    if (rebuildJob.status === 'failed') {
      setJobId(null)
      toast.error(rebuildJob.error || '图谱重建失败')
    }
  }, [jobId, rebuildJob, refetch])

  const handleRebuild = async () => {
    try {
      const job = await rebuildMut.mutateAsync()
      setJobId(job.id)
      if (job.status === 'pending' || job.status === 'running') {
        toast.success('图谱已进入后台重建')
      } else if (job.status === 'completed') {
        setJobId(null)
        refetch()
        toast.success('图谱重建完成')
      }
    } catch {
      toast.error('图谱重建失败')
    }
  }

  const focusNode = (nodeId: string) => {
    startTransition(() => setSelectedNode(nodeId))
    focusNodesInViewport(sigmaRef.current, getNeighborhoodNodeIds(nodeId, neighborMap))
  }

  const runInteractiveLayout = () => {
    const graph = graphRef.current
    const renderer = sigmaRef.current
    if (!graph || !renderer || sigmaData.nodes.length < 2) return

    if (layoutFrameRef.current !== null) {
      cancelAnimationFrame(layoutFrameRef.current)
      layoutFrameRef.current = null
    }

    forceLayoutStateRef.current = { velocities: new Map() }
    setLayoutRunning(true)
    let frame = 0
    const maxFrames = sigmaData.nodes.length > 120 ? 80 : 120

    const tick = () => {
      frame += 1
      runForceLayoutFrame(graph, forceLayoutStateRef.current, draggedNodeRef.current)
      renderer.refresh()

      if (frame < maxFrames) {
        layoutFrameRef.current = requestAnimationFrame(tick)
        return
      }

      layoutFrameRef.current = null
      setLayoutRunning(false)
    }

    layoutFrameRef.current = requestAnimationFrame(tick)
  }

  const clearSelection = () => {
    setSelectedNode(null)
    setHoveredNode(null)
    resetViewport(sigmaRef.current)
  }

  const switchViewMode = (nextMode: ViewMode) => {
    setViewMode(nextMode)
    setSelectedNode(null)
    setHoveredNode(null)
    resetViewport(sigmaRef.current)
  }

  const activeViewLabel = selectedNode
    ? '邻域'
    : searchHighlightIds.size > 0
      ? '搜索'
      : viewMode === 'core'
        ? '核心'
        : '全部'

  useEffect(() => {
    if (!selectedNode || !rendererReady) return
    requestAnimationFrame(() => {
      focusNodesInViewport(sigmaRef.current, getNeighborhoodNodeIds(selectedNode, neighborMap))
    })
  }, [neighborMap, rendererReady, selectedNode, sigmaData])

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">沉淀下</h1>
          <p className="text-sm text-gray-500 mt-1">核心实体、关系邻域与证据链。</p>
        </div>

        <button
          onClick={handleRebuild}
          disabled={rebuildMut.isPending || !!jobId}
          className="px-3 py-2 bg-white border border-gray-200 text-sm rounded-xl hover:border-gray-300 disabled:opacity-50 flex items-center gap-1.5 text-gray-700"
        >
          {rebuildMut.isPending || jobId ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          {jobId ? '图谱重建中...' : '重建图谱'}
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex-1">
                <div className="relative">
                  <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    value={searchInput}
                    onChange={event => setSearchInput(event.target.value)}
                    placeholder="搜索节点名称，例如 DeepSeek、Q2 OKR、Transformer"
                    className="w-full pl-9 pr-9 py-2.5 rounded-xl border border-gray-200 text-sm outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  {searchInput && (
                    <button
                      onClick={() => setSearchInput('')}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
                {searchMatches.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {searchMatches.map(node => (
                      <button
                        key={node.id}
                        onClick={() => focusNode(node.id)}
                        className="px-2.5 py-1 rounded-full text-xs border border-gray-200 bg-gray-50 text-gray-700 hover:bg-white"
                      >
                        {node.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-2 xl:items-end">
                <div className="flex rounded-xl border border-gray-200 bg-gray-50 p-1">
                  <button
                    onClick={() => switchViewMode('core')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors ${
                      viewMode === 'core' && !selectedNode && searchHighlightIds.size === 0
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    <Layers3 className="w-3.5 h-3.5" />
                    核心
                  </button>
                  <button
                    onClick={() => switchViewMode('all')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors ${
                      viewMode === 'all' && !selectedNode && searchHighlightIds.size === 0
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    <Maximize2 className="w-3.5 h-3.5" />
                    全部
                  </button>
                </div>

                <button
                  onClick={runInteractiveLayout}
                  disabled={!rendererReady || useSvgFallback || sigmaData.nodes.length < 2}
                  className="flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700 transition-colors hover:border-gray-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {layoutRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Move className="w-3.5 h-3.5" />}
                  整理布局
                </button>

                <div className="flex flex-wrap gap-2 xl:justify-end">
                  {TYPE_ORDER.map(type => (
                    <button
                      key={type}
                      onClick={() => setFilters(current => ({ ...current, [type]: !current[type] }))}
                      className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs border transition-colors ${
                        filters[type] ? 'border-gray-300 bg-white text-gray-700' : 'border-gray-100 bg-gray-50 text-gray-400'
                      }`}
                    >
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: filters[type] ? TYPE_COLORS[type] : '#d1d5db' }} />
                      {TYPE_LABELS[type]}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-5 mt-4">
              {nodeStats.map(item => (
                <div key={item.type} className="rounded-2xl px-3 py-3 border border-transparent" style={{ backgroundColor: TYPE_PASTELS[item.type] }}>
                  <p className="text-xs text-gray-500">{item.label}</p>
                  <p className="text-lg font-semibold text-gray-900 mt-1">{item.count}</p>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-2 text-xs text-gray-500 mt-4">
              <Sparkles className="w-3.5 h-3.5 text-blue-500" />
              {activeViewLabel}视图展示 {displayData.nodes.length}/{filteredBaseData.nodes.length} 个节点，{displayData.edges.length}/{filteredBaseData.edges.length} 条关系。
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden relative" style={{ height: 'calc(100vh - 270px)', minHeight: 560 }}>
            {isLoading ? (
              <div className="flex items-center justify-center h-full"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
            ) : filteredBaseData.nodes.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-gray-400">
                <Network className="w-12 h-12 mb-3 text-gray-300" />
                <p className="text-sm">暂无图谱数据</p>
                <p className="text-xs mt-1">生成每日总结后自动构建知识图谱</p>
              </div>
            ) : useSvgFallback ? (
              <GraphFallback
                data={sigmaData}
                selectedNode={selectedNode}
                hoveredNode={hoveredNode}
                searchHighlightIds={searchHighlightIds}
                neighborMap={neighborMap}
                focusedNodeIds={focusedNodeIds}
                onNodeSelect={focusNode}
                onNodeEnter={setHoveredNode}
                onNodeLeave={() => setHoveredNode(null)}
              />
            ) : (
              <>
                <div
                  ref={containerRef}
                  className={`w-full h-full bg-[radial-gradient(circle_at_top,#f8fbff,white_45%,#f8fafc)] transition-opacity ${
                    rendererReady ? 'opacity-100' : 'opacity-0'
                  }`}
                />
                {!rendererReady && (
                  <div className="absolute inset-0 flex items-center justify-center bg-white/70">
                    <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-gray-200 p-5 self-start max-h-[calc(100vh-220px)] overflow-y-auto">
          {selectedNode && nodeDetail ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-lg font-semibold text-gray-900">{nodeDetail.node.name}</p>
                  <span
                    className="inline-flex items-center mt-2 px-2.5 py-1 rounded-full text-xs font-medium"
                    style={{
                      backgroundColor: TYPE_PASTELS[nodeDetail.node.type],
                      color: TYPE_COLORS[nodeDetail.node.type],
                    }}
                  >
                    {TYPE_LABELS[nodeDetail.node.type]}
                  </span>
                </div>
                <button onClick={clearSelection} className="text-gray-400 hover:text-gray-600">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <InfoCard label="出现次数" value={String(nodeDetail.node.mention_count)} />
                <InfoCard label="关联节点" value={String(nodeDetail.connected_nodes.length)} />
                <InfoCard label="首次出现" value={nodeDetail.node.first_seen || '-'} />
                <InfoCard label="最近出现" value={nodeDetail.node.last_seen || '-'} />
              </div>

              {nodeDetail.connected_nodes.length > 0 && (
                <section>
                  <p className="text-xs font-medium text-gray-500 mb-2">关联节点</p>
                  <div className="space-y-1.5">
                    {nodeDetail.connected_nodes.map(connectedNode => (
                      <button
                        key={connectedNode.id}
                        onClick={() => focusNode(connectedNode.id)}
                        className="flex items-center gap-2 w-full px-3 py-2 rounded-xl hover:bg-gray-50 text-left text-sm text-gray-700"
                      >
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: TYPE_COLORS[connectedNode.type as KGNode['type']] || '#94a3b8' }}
                        />
                        <span className="truncate">{connectedNode.name}</span>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {nodeDetail.evidences.length > 0 && (
                <section>
                  <p className="text-xs font-medium text-gray-500 mb-2">证据链</p>
                  <div className="space-y-2">
                    {nodeDetail.evidences.map((evidence, index) => (
                      <article
                        key={`${evidence.source_type}-${evidence.event_id ?? evidence.summary_id ?? index}`}
                        className="rounded-2xl border border-gray-100 bg-gray-50/80 p-3"
                      >
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                            evidence.source_type === 'event' ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700'
                          }`}>
                            {evidence.source_type === 'event' ? '事件' : '总结'}
                          </span>
                          {evidence.mention_date && <span className="text-[10px] text-gray-400">{evidence.mention_date}</span>}
                        </div>
                        {evidence.title && <p className="text-sm font-medium text-gray-800">{evidence.title}</p>}
                        {evidence.excerpt && <p className="text-xs text-gray-500 mt-1 leading-relaxed">{evidence.excerpt}</p>}
                      </article>
                    ))}
                  </div>
                </section>
              )}
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-center text-gray-400">
              <Network className="w-10 h-10 text-gray-300 mb-3" />
              <p className="text-sm text-gray-500">点击一个节点查看详情</p>
              <p className="text-xs mt-1 max-w-[220px]">会展示节点属性、邻居节点和证据链。搜索结果也可以直接跳转。</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-gray-50/80 px-3 py-2.5">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className="text-sm font-medium text-gray-800 mt-1">{value}</p>
    </div>
  )
}

function GraphFallback({
  data,
  selectedNode,
  hoveredNode,
  searchHighlightIds,
  neighborMap,
  focusedNodeIds,
  onNodeSelect,
  onNodeEnter,
  onNodeLeave,
}: {
  data: { nodes: SigmaNodeAttrs[]; edges: SigmaEdgeAttrs[] }
  selectedNode: string | null
  hoveredNode: string | null
  searchHighlightIds: Set<string>
  neighborMap: Map<string, Set<string>>
  focusedNodeIds: Set<string>
  onNodeSelect: (nodeId: string) => void
  onNodeEnter: (nodeId: string) => void
  onNodeLeave: () => void
}) {
  const nodeMap = useMemo(
    () => new Map(data.nodes.map(node => [node.id, node])),
    [data.nodes],
  )

  const bounds = useMemo(() => {
    const sourceNodes = focusedNodeIds.size > 0
      ? data.nodes.filter(node => focusedNodeIds.has(node.id))
      : data.nodes
    const displayBounds = buildDisplayBounds(
      sourceNodes.map(node => ({ x: node.x, y: node.y })),
      { minSpan: 4.5, paddingRatio: 0.28 },
    )

    return {
      minX: displayBounds.x - displayBounds.ratio / 2,
      minY: displayBounds.y - displayBounds.ratio / 2,
      width: displayBounds.ratio,
      height: displayBounds.ratio,
    }
  }, [data.nodes, focusedNodeIds])

  const activeNodeId = selectedNode ?? hoveredNode
  const emphasizedNodeIds = useMemo(() => {
    const ids = activeNodeId
      ? getNeighborhoodNodeIds(activeNodeId, neighborMap)
      : new Set<string>()
    if (!activeNodeId) {
      for (const nodeId of searchHighlightIds) ids.add(nodeId)
    }
    return ids
  }, [activeNodeId, neighborMap, searchHighlightIds])
  const shouldDim = emphasizedNodeIds.size > 0

  return (
    <div className="relative w-full h-full bg-[radial-gradient(circle_at_top,#f8fbff,white_45%,#f8fafc)]">
      <svg
        viewBox={`${bounds.minX} ${bounds.minY} ${bounds.width} ${bounds.height}`}
        className="w-full h-full"
        preserveAspectRatio="xMidYMid meet"
      >
        {data.edges.map(edge => {
          const source = nodeMap.get(edge.source)
          const target = nodeMap.get(edge.target)
          if (!source || !target) return null

          const touchesActive = activeNodeId
            ? edge.source === activeNodeId || edge.target === activeNodeId
            : searchHighlightIds.has(edge.source) && searchHighlightIds.has(edge.target)

          const stroke = activeNodeId
            ? touchesActive ? '#9fb4ff' : '#edf1f6'
            : searchHighlightIds.size > 0
              ? touchesActive ? '#aac7ff' : '#edf1f6'
              : edge.color

          return (
            <line
              key={edge.id}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke={stroke}
              strokeWidth={Math.max(0.16, edge.size * (touchesActive ? 0.32 : 0.2))}
              opacity={activeNodeId && !touchesActive ? 0.35 : 0.8}
            />
          )
        })}

        {data.nodes.map(node => {
          const isSelected = node.id === selectedNode
          const isHovered = node.id === hoveredNode
          const isMatch = searchHighlightIds.has(node.id)
          const isEmphasized = emphasizedNodeIds.has(node.id)
          const radius = isSelected
            ? node.size * 0.42
            : isHovered || isMatch
              ? node.size * 0.34
              : shouldDim && !isEmphasized
                ? Math.max(0.7, node.size * 0.18)
                : node.size * 0.28
          const showLabel = isSelected || isHovered || isMatch || node.mentionCount >= 10

          return (
            <g
              key={node.id}
              onClick={() => onNodeSelect(node.id)}
              onMouseEnter={() => onNodeEnter(node.id)}
              onMouseLeave={onNodeLeave}
              className="cursor-pointer"
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={radius}
                fill={shouldDim && !isEmphasized ? '#d9dee7' : node.color}
                stroke={isSelected ? '#1f2937' : '#ffffff'}
                strokeWidth={isSelected ? 0.36 : 0.18}
              />
              {showLabel && (
                <text
                  x={node.x}
                  y={node.y + radius + 0.8}
                  textAnchor="middle"
                  fontSize={Math.max(0.85, node.size * 0.21)}
                  fill="#334155"
                >
                  {node.label}
                </text>
              )}
            </g>
          )
        })}
      </svg>

      <div className="pointer-events-none absolute bottom-3 left-3 rounded-full border border-gray-200 bg-white/85 px-3 py-1 text-[11px] text-gray-500">
        当前环境不支持 WebGL，已切换兼容视图
      </div>
    </div>
  )
}
