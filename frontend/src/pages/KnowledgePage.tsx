import {
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useDeferredValue,
  type CSSProperties,
  type ReactNode,
} from 'react'
import type {
  EdgeData as G6EdgeData,
  GraphData as G6GraphData,
  NodeData as G6NodeData,
} from '@antv/g6'
import {
  Activity,
  BrainCircuit,
  CircleDot,
  Layers3,
  Link2,
  Loader2,
  Maximize2,
  Move,
  Network,
  PanelRight,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useGraph, useJob, useNodeDetail, useStartGraphRebuild } from '../hooks/queries'
import type { GraphData, KGEdge, KGNode } from '../types'

const TYPE_COLORS: Record<KGNode['type'], string> = {
  project: '#3367e8',
  person: '#159875',
  concept: '#7a4cf4',
  tool: '#d97706',
  topic: '#0f98b5',
}

const TYPE_PASTELS: Record<KGNode['type'], string> = {
  project: '#e9f0ff',
  person: '#e8fbf6',
  concept: '#f2ecff',
  tool: '#fff2df',
  topic: '#e3f7fb',
}

const TYPE_BORDERS: Record<KGNode['type'], string> = {
  project: '#bdd0ff',
  person: '#b8eee0',
  concept: '#dacbff',
  tool: '#ffd8a6',
  topic: '#b5e8f2',
}

const TYPE_LABELS: Record<KGNode['type'], string> = {
  project: '项目',
  person: '人物',
  concept: '概念',
  tool: '工具',
  topic: '主题',
}

const TYPE_ORDER: KGNode['type'][] = ['project', 'concept', 'tool', 'topic', 'person']

const TYPE_CLUSTER_ANCHORS: Record<KGNode['type'], { x: number; y: number }> = {
  project: { x: -0.35, y: -0.24 },
  concept: { x: 0.32, y: -0.22 },
  tool: { x: 0.28, y: 0.32 },
  topic: { x: -0.32, y: 0.32 },
  person: { x: -0.03, y: 0.02 },
}

const GRAPH_SURFACE_STYLE: CSSProperties = {
  backgroundColor: '#f8fafc',
  backgroundImage: [
    'linear-gradient(135deg, rgba(51,103,232,0.08), rgba(248,250,252,0.76) 44%, rgba(15,152,181,0.07))',
    'linear-gradient(rgba(148,163,184,0.13) 1px, transparent 1px)',
    'linear-gradient(90deg, rgba(148,163,184,0.13) 1px, transparent 1px)',
  ].join(', '),
  backgroundSize: 'auto, 34px 34px, 34px 34px',
}

const CORE_NODE_LIMIT = 54
const CORE_EDGE_LIMIT = 118
const SEARCH_NODE_LIMIT = 82
const FOCUS_NODE_LIMIT = 92

type ViewMode = 'core' | 'all'
type G6GraphInstance = {
  rendered: boolean
  setSize: (width: number, height: number) => void
  setLayout: (layout: unknown) => void
  setElementState: (state: Record<string, string[]>, animation?: boolean) => Promise<void>
  focusElement: (id: string, animation?: { duration?: number; easing?: string }) => Promise<void>
  fitView: (options?: { when?: 'overflow' | 'always'; direction?: 'x' | 'y' | 'both' }, animation?: { duration?: number; easing?: string }) => Promise<void>
  render: () => Promise<void>
  destroy: () => void
  on: (eventName: string, handler: (event: unknown) => void) => void
}

type GraphNodeMeta = {
  label: string
  entityType: KGNode['type']
  mentionCount: number
  degree: number
  score: number
  size: number
  color: string
  pastel: string
  border: string
  labelVisible: boolean
}

type GraphEdgeMeta = {
  relation: string
  weight: number
  source: string
  target: string
}

type GraphPayload = G6GraphData & {
  nodes: Array<G6NodeData & { id: string; data: GraphNodeMeta }>
  edges: Array<G6EdgeData & { id: string; source: string; target: string; data: GraphEdgeMeta }>
}

function hashNumber(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return hash
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

function getClusterPoint(type: KGNode['type'], width: number, height: number) {
  const anchor = TYPE_CLUSTER_ANCHORS[type]
  return {
    x: width / 2 + anchor.x * width * 0.78,
    y: height / 2 + anchor.y * height * 0.72,
  }
}

function getInitialPoint(node: KGNode, index: number, width: number, height: number) {
  const center = getClusterPoint(node.type, width, height)
  const jitter = hashNumber(node.id) / 0xffffffff
  const angle = index * 2.399963229728653 + jitter * 0.8
  const distance = 18 + Math.sqrt(index + 1) * 14
  return {
    x: center.x + Math.cos(angle) * distance,
    y: center.y + Math.sin(angle) * distance,
  }
}

function getNodeSize(node: KGNode, degree: number) {
  return Math.max(18, Math.min(54, 16 + Math.sqrt(node.mention_count || 1) * 4.2 + Math.sqrt(degree) * 2.8))
}

function getNodeMeta(datum: G6NodeData): GraphNodeMeta {
  return datum.data as GraphNodeMeta
}

function getEdgeMeta(datum: G6EdgeData): GraphEdgeMeta {
  return datum.data as GraphEdgeMeta
}

function buildG6Payload(graphData: GraphData, degreeMap: Map<string, number>, width: number, height: number): GraphPayload {
  const sorted = sortedNodesByImportance(graphData.nodes, degreeMap)
  const nodeRank = new Map(sorted.map((node, index) => [node.id, index]))
  const visibleLabelCount = graphData.nodes.length <= 42 ? graphData.nodes.length : 14

  const nodes = graphData.nodes.map((node, index) => {
    const degree = degreeMap.get(node.id) ?? 0
    const size = getNodeSize(node, degree)
    const score = nodeImportance(node, degreeMap)
    const initialPoint = getInitialPoint(node, index, width, height)

    return {
      id: node.id,
      type: 'circle',
      data: {
        label: node.name,
        entityType: node.type,
        mentionCount: node.mention_count,
        degree,
        score,
        size,
        color: TYPE_COLORS[node.type],
        pastel: TYPE_PASTELS[node.type],
        border: TYPE_BORDERS[node.type],
        labelVisible: (nodeRank.get(node.id) ?? 999) < visibleLabelCount,
      },
      style: {
        x: initialPoint.x,
        y: initialPoint.y,
      },
    }
  })

  const edges = graphData.edges.map((edge, index) => ({
    id: `${edge.source}-${edge.target}-${edge.relation}-${index}`,
    source: edge.source,
    target: edge.target,
    type: 'line',
    data: {
      relation: edge.relation,
      weight: edge.weight,
      source: edge.source,
      target: edge.target,
    },
  }))

  return { nodes, edges }
}

function createForceLayout(width: number, height: number) {
  return {
    type: 'd3-force',
    iterations: 420,
    alpha: 0.9,
    alphaMin: 0.001,
    alphaDecay: 0.022,
    velocityDecay: 0.34,
    center: {
      x: width / 2,
      y: height / 2,
      strength: 0.045,
    },
    manyBody: {
      strength: (node: { data?: GraphNodeMeta }) => -220 - (node.data?.size ?? 24) * 8,
      distanceMin: 22,
      distanceMax: 520,
    },
    link: {
      distance: (edge: { data?: GraphEdgeMeta }) => 136 - Math.min(54, (edge.data?.weight ?? 1) * 6),
      strength: (edge: { data?: GraphEdgeMeta }) => Math.min(0.82, 0.22 + (edge.data?.weight ?? 1) * 0.055),
      iterations: 2,
    },
    collide: {
      radius: (node: { data?: GraphNodeMeta }) => (node.data?.size ?? 24) * 0.74 + 20,
      strength: 0.92,
      iterations: 2,
    },
    x: {
      strength: (node: { data?: GraphNodeMeta }) => (node.data?.entityType === 'person' ? 0.018 : 0.045),
      x: (node: { data?: GraphNodeMeta }) => getClusterPoint(node.data?.entityType ?? 'topic', width, height).x,
    },
    y: {
      strength: (node: { data?: GraphNodeMeta }) => (node.data?.entityType === 'person' ? 0.018 : 0.045),
      y: (node: { data?: GraphNodeMeta }) => getClusterPoint(node.data?.entityType ?? 'topic', width, height).y,
    },
    preventOverlap: true,
  }
}

function getEventElementId(event: unknown) {
  const target = (event as { target?: { id?: string } })?.target
  return target?.id ? String(target.id) : null
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
  const [graphReady, setGraphReady] = useState(false)
  const [layoutRunning, setLayoutRunning] = useState(false)
  const [layoutVersion, setLayoutVersion] = useState(0)
  const deferredSearch = useDeferredValue(searchInput.trim().toLowerCase())
  const { data: nodeDetail } = useNodeDetail(selectedNode)
  const rebuildMut = useStartGraphRebuild()
  const { data: rebuildJob } = useJob(jobId, !!jobId)

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

  const topNodes = useMemo(
    () => sortedNodesByImportance(filteredBaseData.nodes, baseDegreeMap).slice(0, 7),
    [baseDegreeMap, filteredBaseData.nodes],
  )

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
      edgeLimit = 150
    } else if (searchHighlightIds.size > 0) {
      const candidateIds = new Set<string>()
      for (const nodeId of searchHighlightIds) {
        candidateIds.add(nodeId)
        for (const neighborId of baseNeighborMap.get(nodeId) ?? []) candidateIds.add(neighborId)
      }
      visibleNodeIds = capNodeSet(candidateIds, searchHighlightIds, nodesById, baseDegreeMap, SEARCH_NODE_LIMIT)
      edgeLimit = 140
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

  useEffect(() => {
    if (!selectedNode || filteredBaseData.nodes.some(node => node.id === selectedNode)) return
    setSelectedNode(null)
  }, [filteredBaseData.nodes, selectedNode])

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

  const focusNode = useCallback((nodeId: string) => {
    startTransition(() => setSelectedNode(nodeId))
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedNode(null)
    setHoveredNode(null)
  }, [])

  const switchViewMode = (nextMode: ViewMode) => {
    setViewMode(nextMode)
    setSelectedNode(null)
    setHoveredNode(null)
  }

  const activeViewLabel = selectedNode
    ? '邻域'
    : searchHighlightIds.size > 0
      ? '搜索'
      : viewMode === 'core'
        ? '核心'
        : '全部'

  const handleGraphSelect = useCallback((nodeId: string) => {
    startTransition(() => setSelectedNode(nodeId))
  }, [])

  const handleGraphHover = useCallback((nodeId: string | null) => {
    setHoveredNode(nodeId)
  }, [])

  const handleGraphReady = useCallback((ready: boolean) => {
    setGraphReady(ready)
  }, [])

  const handleLayoutRunning = useCallback((running: boolean) => {
    setLayoutRunning(running)
  }, [])

  return (
    <div className="min-w-0 max-w-full space-y-4 overflow-hidden">
      <section className="rounded-lg border border-slate-200 bg-white px-4 py-4 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
              <BrainCircuit className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-slate-950">沉淀下</h1>
              <p className="mt-1 text-sm text-slate-500">核心实体、关系邻域与证据链</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <MetricBadge icon={<CircleDot className="h-3.5 w-3.5" />} label="节点" value={graphData?.nodes.length ?? 0} />
            <MetricBadge icon={<Link2 className="h-3.5 w-3.5" />} label="关系" value={graphData?.edges.length ?? 0} />
            <MetricBadge icon={<Target className="h-3.5 w-3.5" />} label={activeViewLabel} value={displayData.nodes.length} />
            <button
              onClick={handleRebuild}
              disabled={rebuildMut.isPending || !!jobId}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {rebuildMut.isPending || jobId ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              {jobId ? '重建中' : '重建图谱'}
            </button>
          </div>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-3">
          <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex flex-col gap-3 2xl:flex-row 2xl:items-center">
              <div className="relative min-w-0 flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={searchInput}
                  onChange={event => setSearchInput(event.target.value)}
                  placeholder="搜索节点名称，例如 DeepSeek、Q2 OKR、Transformer"
                  className="h-10 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-9 text-sm text-slate-800 outline-none transition focus:border-blue-300 focus:bg-white focus:ring-2 focus:ring-blue-100"
                />
                {searchInput && (
                  <button
                    onClick={() => setSearchInput('')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md text-slate-300 transition-colors hover:text-slate-600"
                    aria-label="清空搜索"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>

              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <div className="flex rounded-lg border border-slate-200 bg-slate-100 p-1">
                  <button
                    onClick={() => switchViewMode('core')}
                    className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors ${
                      viewMode === 'core' && !selectedNode && searchHighlightIds.size === 0
                        ? 'bg-white text-slate-900 shadow-sm'
                        : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <Layers3 className="h-3.5 w-3.5" />
                    核心
                  </button>
                  <button
                    onClick={() => switchViewMode('all')}
                    className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors ${
                      viewMode === 'all' && !selectedNode && searchHighlightIds.size === 0
                        ? 'bg-white text-slate-900 shadow-sm'
                        : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <Maximize2 className="h-3.5 w-3.5" />
                    全部
                  </button>
                </div>

                <button
                  onClick={() => setLayoutVersion(version => version + 1)}
                  disabled={!graphReady || displayData.nodes.length < 2}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {layoutRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Move className="h-3.5 w-3.5" />}
                  {layoutRunning ? '力导计算中' : '力导重排'}
                </button>
              </div>
            </div>

            {searchMatches.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {searchMatches.map(node => (
                  <button
                    key={node.id}
                    onClick={() => focusNode(node.id)}
                    className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: TYPE_COLORS[node.type] }}
                    />
                    <span className="truncate">{node.name}</span>
                  </button>
                ))}
              </div>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
              {TYPE_ORDER.map(type => (
                <button
                  key={type}
                  onClick={() => setFilters(current => ({ ...current, [type]: !current[type] }))}
                  className={`inline-flex h-8 items-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors ${
                    filters[type] ? 'bg-white text-slate-800 shadow-sm' : 'bg-slate-50 text-slate-400'
                  }`}
                  style={{
                    borderColor: filters[type] ? TYPE_BORDERS[type] : '#e5e7eb',
                  }}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: filters[type] ? TYPE_COLORS[type] : '#cbd5e1' }}
                  />
                  {TYPE_LABELS[type]}
                  <span className="text-[11px] text-slate-400">{nodeStats.find(item => item.type === type)?.count ?? 0}</span>
                </button>
              ))}

              <div className="ml-auto flex items-center gap-1.5 text-xs text-slate-500">
                <Sparkles className="h-3.5 w-3.5 text-blue-500" />
                {displayData.nodes.length}/{filteredBaseData.nodes.length} 节点 · {displayData.edges.length}/{filteredBaseData.edges.length} 关系
              </div>
            </div>
          </section>

          <section className="relative overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm" style={{ height: 'calc(100vh - 286px)', minHeight: 590 }}>
            {!isLoading && filteredBaseData.nodes.length > 0 && (
              <>
                <div className="pointer-events-none absolute left-4 top-4 z-10 flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-lg border border-white/80 bg-white/90 px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm backdrop-blur">
                    <Activity className="h-3.5 w-3.5 text-blue-500" />
                    {activeViewLabel}视图
                  </span>
                  <span className="rounded-lg border border-white/80 bg-white/90 px-2.5 py-1.5 text-xs text-slate-500 shadow-sm backdrop-blur">
                    {displayData.nodes.length} 节点 · {displayData.edges.length} 关系
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-lg border border-white/80 bg-white/90 px-2.5 py-1.5 text-xs text-slate-500 shadow-sm backdrop-blur">
                    {layoutRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" /> : <Move className="h-3.5 w-3.5 text-slate-400" />}
                    G6 力导
                  </span>
                </div>

                <div className="pointer-events-none absolute bottom-4 left-4 z-10 flex flex-wrap gap-2">
                  {TYPE_ORDER.map(type => (
                    <span key={type} className="inline-flex items-center gap-1.5 rounded-lg border border-white/80 bg-white/90 px-2.5 py-1.5 text-[11px] font-medium text-slate-600 shadow-sm backdrop-blur">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: TYPE_COLORS[type] }} />
                      {TYPE_LABELS[type]}
                    </span>
                  ))}
                </div>
              </>
            )}

            {isLoading ? (
              <div className="flex h-full items-center justify-center" style={GRAPH_SURFACE_STYLE}>
                <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
              </div>
            ) : filteredBaseData.nodes.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-slate-400" style={GRAPH_SURFACE_STYLE}>
                <Network className="mb-3 h-12 w-12 text-slate-300" />
                <p className="text-sm font-medium text-slate-500">暂无图谱数据</p>
                <p className="mt-1 text-xs text-slate-400">生成每日总结后自动构建知识图谱</p>
              </div>
            ) : (
              <ElegantForceGraph
                data={displayData}
                degreeMap={baseDegreeMap}
                selectedNode={selectedNode}
                hoveredNode={hoveredNode}
                searchHighlightIds={searchHighlightIds}
                neighborMap={baseNeighborMap}
                layoutVersion={layoutVersion}
                onNodeSelect={handleGraphSelect}
                onNodeHover={handleGraphHover}
                onCanvasClear={clearSelection}
                onReady={handleGraphReady}
                onLayoutRunning={handleLayoutRunning}
              />
            )}
          </section>
        </div>

        <aside className="self-start overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm xl:sticky xl:top-6">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <div className="flex items-center gap-2">
              <PanelRight className="h-4 w-4 text-slate-400" />
              <p className="text-sm font-semibold text-slate-800">节点详情</p>
            </div>
            {selectedNode && (
              <button onClick={clearSelection} className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700" aria-label="关闭详情">
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          <div className="max-h-[calc(100vh-210px)] overflow-y-auto">
            {selectedNode && nodeDetail ? (
              <div>
                <div className="border-b border-slate-100 px-4 py-4">
                  <div className="flex items-start gap-3">
                    <span
                      className="mt-1 h-3 w-3 shrink-0 rounded-full"
                      style={{
                        backgroundColor: TYPE_COLORS[nodeDetail.node.type],
                        boxShadow: `0 0 0 4px ${TYPE_PASTELS[nodeDetail.node.type]}, 0 0 0 5px ${TYPE_BORDERS[nodeDetail.node.type]}`,
                      }}
                    />
                    <div className="min-w-0">
                      <p className="break-words text-lg font-semibold leading-snug text-slate-950">{nodeDetail.node.name}</p>
                      <span
                        className="mt-2 inline-flex items-center rounded-md px-2 py-1 text-xs font-medium"
                        style={{
                          backgroundColor: TYPE_PASTELS[nodeDetail.node.type],
                          color: TYPE_COLORS[nodeDetail.node.type],
                        }}
                      >
                        {TYPE_LABELS[nodeDetail.node.type]}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 border-b border-slate-100">
                  <DetailStat label="出现次数" value={String(nodeDetail.node.mention_count)} />
                  <DetailStat label="关联节点" value={String(nodeDetail.connected_nodes.length)} />
                  <DetailStat label="首次出现" value={nodeDetail.node.first_seen || '-'} />
                  <DetailStat label="最近出现" value={nodeDetail.node.last_seen || '-'} />
                </div>

                {nodeDetail.connected_nodes.length > 0 && (
                  <section className="border-b border-slate-100 px-4 py-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">关联节点</p>
                    <div className="space-y-1">
                      {nodeDetail.connected_nodes.map(connectedNode => (
                        <button
                          key={connectedNode.id}
                          onClick={() => focusNode(connectedNode.id)}
                          className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
                        >
                          <span
                            className="h-2.5 w-2.5 shrink-0 rounded-full"
                            style={{ backgroundColor: TYPE_COLORS[connectedNode.type as KGNode['type']] || '#94a3b8' }}
                          />
                          <span className="truncate">{connectedNode.name}</span>
                        </button>
                      ))}
                    </div>
                  </section>
                )}

                {nodeDetail.evidences.length > 0 && (
                  <section className="px-4 py-4">
                    <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">证据链</p>
                    <div className="space-y-3">
                      {nodeDetail.evidences.map((evidence, index) => (
                        <article
                          key={`${evidence.source_type}-${evidence.event_id ?? evidence.summary_id ?? index}`}
                          className="border-l-2 border-slate-200 pl-3"
                        >
                          <div className="mb-1.5 flex items-center gap-2">
                            <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${
                              evidence.source_type === 'event' ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700'
                            }`}>
                              {evidence.source_type === 'event' ? '事件' : '总结'}
                            </span>
                            {evidence.mention_date && <span className="text-[10px] text-slate-400">{evidence.mention_date}</span>}
                          </div>
                          {evidence.title && <p className="text-sm font-medium leading-snug text-slate-800">{evidence.title}</p>}
                          {evidence.excerpt && <p className="mt-1 text-xs leading-relaxed text-slate-500">{evidence.excerpt}</p>}
                        </article>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            ) : selectedNode ? (
              <div className="flex min-h-[260px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
              </div>
            ) : (
              <div className="px-4 py-4">
                <div className="flex items-center gap-3 border-b border-slate-100 pb-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                    <Network className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-800">图谱概览</p>
                    <p className="mt-0.5 text-xs text-slate-500">{filteredBaseData.nodes.length} 个可见节点</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 border-b border-slate-100">
                  <DetailStat label="当前视图" value={activeViewLabel} />
                  <DetailStat label="可见关系" value={String(displayData.edges.length)} />
                </div>

                {topNodes.length > 0 && (
                  <section className="py-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">高频节点</p>
                    <div className="space-y-1">
                      {topNodes.map(node => (
                        <button
                          key={node.id}
                          onClick={() => focusNode(node.id)}
                          className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
                        >
                          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: TYPE_COLORS[node.type] }} />
                          <span className="min-w-0 flex-1 truncate">{node.name}</span>
                          <span className="text-xs text-slate-400">{node.mention_count}</span>
                        </button>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

function ElegantForceGraph({
  data,
  degreeMap,
  selectedNode,
  hoveredNode,
  searchHighlightIds,
  neighborMap,
  layoutVersion,
  onNodeSelect,
  onNodeHover,
  onCanvasClear,
  onReady,
  onLayoutRunning,
}: {
  data: GraphData
  degreeMap: Map<string, number>
  selectedNode: string | null
  hoveredNode: string | null
  searchHighlightIds: Set<string>
  neighborMap: Map<string, Set<string>>
  layoutVersion: number
  onNodeSelect: (nodeId: string) => void
  onNodeHover: (nodeId: string | null) => void
  onCanvasClear: () => void
  onReady: (ready: boolean) => void
  onLayoutRunning: (running: boolean) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const graphRef = useRef<G6GraphInstance | null>(null)
  const [containerSize, setContainerSize] = useState({ width: 960, height: 640 })

  const payload = useMemo(
    () => buildG6Payload(data, degreeMap, containerSize.width, containerSize.height),
    [containerSize.height, containerSize.width, data, degreeMap],
  )

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const updateSize = () => {
      const rect = container.getBoundingClientRect()
      if (rect.width < 20 || rect.height < 20) return
      setContainerSize({
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      })
      graphRef.current?.setSize(Math.round(rect.width), Math.round(rect.height))
    }

    updateSize()
    const resizeObserver = new ResizeObserver(updateSize)
    resizeObserver.observe(container)

    return () => resizeObserver.disconnect()
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!container || payload.nodes.length === 0) return

    let disposed = false
    let graph: G6GraphInstance | null = null
    let settleTimer: number | null = null
    onReady(false)
    onLayoutRunning(true)

    const renderGraph = async () => {
      try {
        const { Graph } = await import('@antv/g6')
        if (disposed) return

        graph = new Graph({
          container,
          width: containerSize.width,
          height: containerSize.height,
          autoResize: true,
          autoFit: {
            type: 'view',
            options: { when: 'always' },
            animation: { duration: 420 },
          },
          padding: [88, 64, 72, 64],
          zoomRange: [0.25, 3],
          background: 'transparent',
          data: payload,
          layout: createForceLayout(containerSize.width, containerSize.height),
          animation: { duration: 520, easing: 'ease-out' },
          node: {
            type: 'circle',
            style: (datum: G6NodeData) => {
              const meta = getNodeMeta(datum)
              return {
                size: meta.size,
                fill: meta.color,
                fillOpacity: 0.92,
                stroke: '#ffffff',
                lineWidth: 2.2,
                shadowColor: `${meta.color}44`,
                shadowBlur: 14,
                shadowOffsetX: 0,
                shadowOffsetY: 6,
                labelText: meta.labelVisible ? meta.label : '',
                labelPlacement: 'bottom',
                labelOffsetY: 7,
                labelFill: '#334155',
                labelFontSize: 12,
                labelFontWeight: 600,
                labelBackground: true,
                labelBackgroundFill: 'rgba(255,255,255,0.88)',
                labelBackgroundRadius: 5,
                labelPadding: [3, 6],
                labelWordWrap: true,
                labelMaxWidth: 148,
                halo: true,
                haloStroke: meta.color,
                haloStrokeOpacity: 0.08,
                haloLineWidth: 18,
                zIndex: Math.round(meta.score),
              }
            },
            state: {
              selected: {
                fillOpacity: 1,
                lineWidth: 4,
                stroke: '#ffffff',
                halo: true,
                haloStrokeOpacity: 0.22,
                haloLineWidth: 34,
                labelText: (datum: G6NodeData) => getNodeMeta(datum).label,
                labelFill: '#0f172a',
                labelFontSize: 13,
                labelFontWeight: 700,
                zIndex: 1000,
              },
              active: {
                fillOpacity: 1,
                lineWidth: 3.2,
                halo: true,
                haloStrokeOpacity: 0.18,
                haloLineWidth: 28,
                labelText: (datum: G6NodeData) => getNodeMeta(datum).label,
                labelFill: '#0f172a',
                zIndex: 900,
              },
              related: {
                fillOpacity: 0.94,
                lineWidth: 2.8,
                halo: true,
                haloStrokeOpacity: 0.12,
                haloLineWidth: 22,
              },
              search: {
                fillOpacity: 1,
                lineWidth: 3.4,
                halo: true,
                haloStrokeOpacity: 0.2,
                haloLineWidth: 30,
                labelText: (datum: G6NodeData) => getNodeMeta(datum).label,
                labelFill: '#0f172a',
                labelFontWeight: 700,
                zIndex: 920,
              },
              dim: {
                fillOpacity: 0.18,
                strokeOpacity: 0.35,
                shadowBlur: 0,
                halo: false,
                labelText: '',
              },
            },
          },
          edge: {
            type: 'line',
            style: (datum: G6EdgeData) => {
              const meta = getEdgeMeta(datum)
              return {
                stroke: '#c5ccd8',
                strokeOpacity: 0.42,
                lineWidth: Math.max(1, Math.min(4.2, 0.8 + meta.weight * 0.26)),
                lineCap: 'round',
                labelText: '',
                zIndex: Math.round(meta.weight),
              }
            },
            state: {
              related: {
                stroke: '#6f8cff',
                strokeOpacity: 0.72,
                lineWidth: (datum: G6EdgeData) => Math.max(1.6, Math.min(5, 1.4 + getEdgeMeta(datum).weight * 0.3)),
                labelText: (datum: G6EdgeData) => getEdgeMeta(datum).relation,
                labelFill: '#475569',
                labelFontSize: 11,
                labelBackground: true,
                labelBackgroundFill: 'rgba(255,255,255,0.86)',
                labelBackgroundRadius: 4,
                labelPadding: [2, 5],
                zIndex: 700,
              },
              dim: {
                strokeOpacity: 0.08,
                lineWidth: 1,
                labelText: '',
              },
            },
          },
          transforms: [{ type: 'process-parallel-edges', mode: 'bundle', distance: 18 }],
          behaviors: [
            'drag-canvas',
            { type: 'zoom-canvas', sensitivity: 1.08 },
            { type: 'drag-element-force', fixed: false },
            { type: 'auto-adapt-label', throttle: 100 },
          ],
        }) as G6GraphInstance

        if (disposed || !graph) {
          graph?.destroy()
          return
        }

        graph.on('node:click', event => {
          const nodeId = getEventElementId(event)
          if (!nodeId) return
          onNodeSelect(nodeId)
        })
        graph.on('node:pointerenter', event => {
          const nodeId = getEventElementId(event)
          if (!nodeId) return
          onNodeHover(nodeId)
        })
        graph.on('node:pointerleave', () => onNodeHover(null))
        graph.on('canvas:click', () => onCanvasClear())

        graphRef.current = graph
        const renderPromise = graph.render()
        settleTimer = window.setTimeout(() => {
          if (disposed) return
          onReady(true)
          onLayoutRunning(false)
        }, 2600)
        await renderPromise
        if (disposed) return
        if (settleTimer !== null) {
          window.clearTimeout(settleTimer)
          settleTimer = null
        }
        onReady(true)
        await graph.fitView({ when: 'always' }, { duration: 420 })
      } catch (error) {
        console.error('Failed to render G6 knowledge graph', error)
        toast.error('图谱渲染失败')
      } finally {
        if (!disposed) onLayoutRunning(false)
      }
    }

    renderGraph()

    return () => {
      disposed = true
      if (settleTimer !== null) window.clearTimeout(settleTimer)
      onReady(false)
      onLayoutRunning(false)
      graph?.destroy()
      if (graphRef.current === graph) graphRef.current = null
    }
  }, [
    containerSize.height,
    containerSize.width,
    onCanvasClear,
    onLayoutRunning,
    onNodeHover,
    onNodeSelect,
    onReady,
    payload,
  ])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph || !graph.rendered) return

    const activeNode = selectedNode ?? hoveredNode
    const emphasizedNodeIds = activeNode
      ? getNeighborhoodNodeIds(activeNode, neighborMap)
      : new Set<string>()

    if (!activeNode && searchHighlightIds.size > 0) {
      for (const nodeId of searchHighlightIds) emphasizedNodeIds.add(nodeId)
      for (const nodeId of searchHighlightIds) {
        for (const neighborId of neighborMap.get(nodeId) ?? []) emphasizedNodeIds.add(neighborId)
      }
    }

    const shouldDim = emphasizedNodeIds.size > 0
    const stateMap: Record<string, string[]> = {}

    for (const node of payload.nodes) {
      const nodeId = node.id
      if (nodeId === selectedNode) {
        stateMap[nodeId] = ['selected']
      } else if (nodeId === hoveredNode) {
        stateMap[nodeId] = ['active']
      } else if (searchHighlightIds.has(nodeId)) {
        stateMap[nodeId] = ['search']
      } else if (shouldDim && !emphasizedNodeIds.has(nodeId)) {
        stateMap[nodeId] = ['dim']
      } else if (activeNode && emphasizedNodeIds.has(nodeId)) {
        stateMap[nodeId] = ['related']
      } else {
        stateMap[nodeId] = []
      }
    }

    for (const edge of payload.edges) {
      const touchesActive = activeNode
        ? edge.source === activeNode || edge.target === activeNode
        : searchHighlightIds.has(edge.source) || searchHighlightIds.has(edge.target)
      stateMap[edge.id] = shouldDim
        ? touchesActive ? ['related'] : ['dim']
        : []
    }

    graph.setElementState(stateMap, true)

    if (selectedNode) {
      graph.focusElement(selectedNode, { duration: 360, easing: 'ease-in-out' }).catch(() => undefined)
    }
  }, [hoveredNode, neighborMap, payload.edges, payload.nodes, searchHighlightIds, selectedNode])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph || !graph.rendered || layoutVersion === 0) return

    onLayoutRunning(true)
    const settleTimer = window.setTimeout(() => onLayoutRunning(false), 2400)
    graph.setLayout(createForceLayout(containerSize.width, containerSize.height))
    graph.render()
      .then(() => graph.fitView({ when: 'always' }, { duration: 420 }))
      .finally(() => {
        window.clearTimeout(settleTimer)
        onLayoutRunning(false)
      })
    return () => window.clearTimeout(settleTimer)
  }, [containerSize.height, containerSize.width, layoutVersion, onLayoutRunning])

  return (
    <div className="h-full w-full" style={GRAPH_SURFACE_STYLE}>
      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}

function MetricBadge({ icon, label, value }: { icon: ReactNode; label: string; value: number | string }) {
  return (
    <div className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm text-slate-700">
      <span className="text-slate-400">{icon}</span>
      <span className="text-xs text-slate-500">{label}</span>
      <span className="font-semibold text-slate-900">{value}</span>
    </div>
  )
}

function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-r border-t border-slate-100 px-4 py-3 even:border-r-0">
      <p className="text-[11px] text-slate-400">{label}</p>
      <p className="mt-1 break-words text-sm font-medium text-slate-800">{value}</p>
    </div>
  )
}
