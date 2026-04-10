import { useState, useEffect, useRef, useCallback } from 'react'

const SKILL_COLORS = {
  security_denial: 'bg-red-900/60 text-red-300 border-red-800/50',
  inbox_processing: 'bg-blue-900/60 text-blue-300 border-blue-800/50',
  email_outbound: 'bg-purple-900/60 text-purple-300 border-purple-800/50',
  crm_lookup: 'bg-cyan-900/60 text-cyan-300 border-cyan-800/50',
  invoice_creation: 'bg-amber-900/60 text-amber-300 border-amber-800/50',
  followup_reschedule: 'bg-orange-900/60 text-orange-300 border-orange-800/50',
  knowledge_capture: 'bg-green-900/60 text-green-300 border-green-800/50',
  knowledge_cleanup: 'bg-yellow-900/60 text-yellow-300 border-yellow-800/50',
  knowledge_lookup: 'bg-teal-900/60 text-teal-300 border-teal-800/50',
  unsupported_capability: 'bg-gray-800/60 text-gray-400 border-gray-700/50',
  purchase_ops: 'bg-indigo-900/60 text-indigo-300 border-indigo-800/50',
  clarification: 'bg-slate-800/60 text-slate-400 border-slate-700/50',
}
function SkillBadge({ skillId }) {
  if (!skillId) return null
  return <span className={`text-[10px] px-2 py-0.5 rounded-full border ${SKILL_COLORS[skillId] || 'bg-slate-800 text-slate-400'}`}>{skillId.replace(/_/g, ' ')}</span>
}
function ScoreBadge({ score }) {
  if (score < 0) return <span className="text-slate-600 text-xs">--</span>
  if (score === 1) return <span className="bg-emerald-500/20 text-emerald-400 text-xs font-bold px-2 py-0.5 rounded">PASS</span>
  return <span className="bg-red-500/20 text-red-400 text-xs font-bold px-2 py-0.5 rounded">FAIL</span>
}
function StatusIndicator({ status }) {
  if (status === 'running') return <span className="relative flex h-2.5 w-2.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span><span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-400"></span></span>
  if (status === 'done') return <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 inline-block" />
  if (status === 'error') return <span className="h-2.5 w-2.5 rounded-full bg-red-500 inline-block" />
  return <span className="h-2.5 w-2.5 rounded-full bg-slate-700 inline-block" />
}
function EventLine({ ev }) {
  const t = ev.type
  if (t === 'llm_start') return <div className="flex gap-2 text-slate-500 py-0.5"><span className="w-5 text-center shrink-0">🧠</span><span>Step {ev.step}: thinking...</span></div>
  if (t === 'llm_end') return (<div className="py-0.5"><div className="flex gap-2 text-slate-400"><span className="w-5 text-center shrink-0">💬</span><span>Step {ev.step}: responded <span className="text-slate-600">({ev.elapsed_ms}ms)</span></span></div>{ev.output_preview && <pre className="ml-7 text-[10px] text-slate-600 whitespace-pre-wrap max-h-20 overflow-y-auto leading-relaxed">{ev.output_preview}</pre>}</div>)
  if (t === 'tool_start') return <div className="flex gap-2 text-cyan-400 py-0.5"><span className="w-5 text-center shrink-0">🔧</span><span className="font-semibold">{ev.tool}</span></div>
  if (t === 'tool_end') return (<div className="py-0.5"><div className="flex gap-2 text-slate-400"><span className="w-5 text-center shrink-0">📄</span><span>{ev.tool} <span className="text-slate-600">({ev.result_lines} lines)</span></span></div>{ev.result && <pre className="ml-7 text-[10px] text-slate-600 whitespace-pre-wrap max-h-40 overflow-y-auto bg-slate-950/50 rounded p-2 border border-slate-800/50 leading-relaxed">{ev.result}</pre>}</div>)
  if (t === 'task_classified') return <div className="flex gap-2 items-center text-purple-400 py-0.5"><span className="w-5 text-center shrink-0">🏷️</span><span>Classified:</span><SkillBadge skillId={ev.skill_id} /><span className="text-slate-600">({(ev.skill_confidence*100).toFixed(0)}%) [{ev.classifier||'regex'}]</span></div>
  if (t === 'agent_output') return (<div className="py-0.5"><div className="flex gap-2 text-emerald-400"><span className="w-5 text-center shrink-0">✅</span><span>Output{ev.completion_submitted?'':' ⚠️ no report_completion'}</span></div><pre className="ml-7 text-xs text-slate-400 whitespace-pre-wrap max-h-24 overflow-y-auto">{ev.output}</pre></div>)
  if (t === 'fallback_submit') return <div className="flex gap-2 text-amber-400 py-0.5"><span className="w-5 text-center shrink-0">⚠️</span><span>Fallback: {ev.outcome} — {ev.message?.substring(0,150)}</span></div>
  if (t === 'task_done') return <div className={`flex gap-2 font-bold py-1 ${ev.score===1?'text-emerald-400':'text-red-400'}`}><span className="w-5 text-center shrink-0">🏁</span><span>Score: {ev.score} ({ev.wall_time_ms}ms, {ev.tool_calls} tools)</span></div>
  if (t === 'task_error') return <div className="flex gap-2 text-red-400 py-0.5"><span className="w-5 text-center shrink-0">❌</span><span>{ev.error}</span></div>
  return null
}
function CopyButton({ runId, taskId }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async (e) => { e.stopPropagation(); try { const r = await fetch(`/api/runs/${runId}/tasks/${taskId}/log`); await navigator.clipboard.writeText(await r.text()); setCopied(true); setTimeout(()=>setCopied(false),2000) } catch{} }
  return <button onClick={handleCopy} className="text-[10px] px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 transition">{copied?'✓ Copied':'Copy log'}</button>
}
function TaskPanel({ task, events, runId }) {
  const taskEvents = events.filter(e=>e.task_id===task.task_id)
  const scrollRef = useRef(null)
  useEffect(()=>{const el=scrollRef.current;if(el)el.scrollTop=el.scrollHeight},[taskEvents.length])
  return (
    <div className="border-t border-slate-800 bg-slate-950/80">
      <div className="px-5 py-3 border-b border-slate-800/50 flex justify-between items-start">
        <div className="flex-1">
          <div className="text-[10px] uppercase tracking-wider text-slate-600 mb-1">Instruction</div>
          <div className="text-sm text-slate-300">{task.instruction||'Loading...'}</div>
          {task.harness_url && (
            <div className="mt-1.5 flex items-center gap-2">
              <a href={task.harness_url} target="_blank" rel="noopener" className="text-[10px] text-cyan-500 hover:text-cyan-400 underline">
                Platform log
              </a>
              <span className="text-[10px] text-slate-700 font-mono">{task.trial_id || ''}</span>
            </div>
          )}
        </div>
        <CopyButton runId={runId} taskId={task.task_id}/>
      </div>
      {task.score===0&&<div className="px-5 py-3 border-b border-slate-800/50 bg-red-950/20">
        <div className="text-[10px] uppercase tracking-wider text-red-400/60 mb-2">Failed — Expected vs Actual</div>
        {task.score_detail?.map((d,i)=><div key={i} className="text-xs text-red-400 mb-1">{d}</div>)}
        {(()=>{const out=taskEvents.find(e=>e.type==='agent_output');return out?<div className="mt-2"><div className="text-[10px] text-slate-600 mb-1">Agent answer:</div><pre className="text-xs text-slate-400 whitespace-pre-wrap max-h-24 overflow-y-auto bg-slate-950/50 rounded p-2 border border-slate-800/50">{out.output||'(empty)'}</pre></div>:null})()}
      </div>}
      <div ref={scrollRef} className="px-5 py-3 space-y-0.5 text-xs font-mono max-h-[600px] overflow-y-auto">
        {taskEvents.length===0&&<div className="text-slate-700 py-4 text-center">Waiting for events...</div>}
        {taskEvents.map((ev,i)=><EventLine key={i} ev={ev}/>)}
      </div>
    </div>
  )
}
function TaskRow({ task, isExpanded, onToggle }) {
  return (<div className={`grid grid-cols-[32px_52px_1fr_110px_60px_60px_64px_64px] gap-2 px-4 py-2 hover:bg-slate-800/40 cursor-pointer items-center text-sm transition ${isExpanded?'bg-slate-800/30':''}`} onClick={onToggle}>
    <span><StatusIndicator status={task.status}/></span><span className="font-mono text-slate-400 text-xs">{task.task_id}</span><span className="truncate text-slate-500 text-xs">{task.instruction||'...'}</span><span>{task.skill_id?<SkillBadge skillId={task.skill_id}/>:<span className="text-[10px] text-slate-700">—</span>}</span><span><ScoreBadge score={task.score}/></span><span className="text-slate-600 text-xs text-center">{task.tool_calls>0?task.tool_calls:''}</span><span className="text-slate-600 text-xs text-right">{task.total_tokens>0?`${(task.total_tokens/1000).toFixed(1)}k`:''}</span><span className="text-slate-600 text-xs text-right">{task.wall_time_ms>0?`${(task.wall_time_ms/1000).toFixed(1)}s`:''}</span>
  </div>)
}
function ProgressBar({ passed, failed, total }) {
  const p=total>0?(passed/total)*100:0, f=total>0?(failed/total)*100:0
  return <div className="h-2 bg-slate-800 rounded-full overflow-hidden flex"><div className="bg-emerald-500 transition-all duration-500" style={{width:`${p}%`}}/><div className="bg-red-500 transition-all duration-500" style={{width:`${f}%`}}/></div>
}
function StatCard({ value, label, color='text-white' }) {
  return <div className="bg-slate-900/80 rounded-xl p-4 border border-slate-800/50"><div className={`text-2xl font-bold ${color}`}>{value}</div><div className="text-[10px] text-slate-600 uppercase tracking-wider mt-1">{label}</div></div>
}
function formatRunTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getDate())}.${pad(d.getMonth()+1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function RunSidebar({ runs, activeRunId, onSelect, compareIds, onToggleCompare, onDelete }) {
  const sorted = [...runs].sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
  return (
    <div className="w-64 shrink-0 border-r border-slate-800/50 bg-slate-900/30 h-screen overflow-y-auto sticky top-0">
      <div className="px-3 py-3 border-b border-slate-800/50"><div className="text-[10px] uppercase tracking-wider text-slate-600">Run History</div></div>
      {sorted.length===0&&<div className="px-3 py-6 text-xs text-slate-700 text-center">No runs yet</div>}
      <div className="p-2 space-y-2">
        {sorted.map(r=>{
          const scored=Object.values(r.tasks||{}).filter(t=>t.score>=0)
          const passed=scored.filter(t=>t.score===1).length
          const pct=scored.length>0?(passed/scored.length)*100:0
          const isActive=r.run_id===activeRunId
          const isCompare=compareIds.includes(r.run_id)
          return (
            <div key={r.run_id} onClick={()=>onSelect(r.run_id)}
              className={`rounded-lg p-3 cursor-pointer transition-all border ${
                isActive
                  ? 'bg-cyan-950/40 border-cyan-500/50 shadow-lg shadow-cyan-500/10 ring-1 ring-cyan-500/20'
                  : isCompare
                    ? 'bg-purple-950/30 border-purple-500/40'
                    : 'bg-slate-900/60 border-slate-800/50 hover:bg-slate-800/60 hover:border-slate-700/60'
              }`}>
              <div className="flex items-center justify-between mb-2">
                <span className={`font-mono text-xs ${isActive?'text-cyan-400 font-bold':'text-slate-300'}`}>{r.run_id}</span>
                <div className="flex items-center gap-1" onClick={e=>e.stopPropagation()}>
                  <input type="checkbox" checked={isCompare} onChange={()=>onToggleCompare(r.run_id)} className="w-3 h-3 accent-purple-500" title="Compare"/>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${r.status==='done'?'bg-emerald-900/50 text-emerald-400':r.status==='running'?'bg-amber-900/50 text-amber-400':r.status==='error'?'bg-red-900/50 text-red-400':'bg-slate-800 text-slate-500'}`}>{r.status}</span>
                  {r.status!=='running'&&<button onClick={e=>{e.stopPropagation();onDelete(r.run_id)}} className="text-slate-700 hover:text-red-400 text-xs ml-0.5" title="Delete">x</button>}
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-slate-500">{r.total||0} tasks</span>
                <span className={`text-sm font-bold ${pct>=80?'text-emerald-400':pct>=60?'text-amber-400':'text-red-400'}`}>{(r.final_score||0).toFixed(1)}%</span>
              </div>
              <div className="flex items-center gap-2 mt-1 text-[10px] text-slate-600">
                {r.started_at>0&&<span>{formatRunTime(r.started_at)}</span>}
                {r.temperature!=null&&<span className="text-amber-500/60">t={r.temperature}</span>}
                {r.model&&<span className="text-slate-700 truncate">{r.model}</span>}
              </div>
              {scored.length>0&&<div className="h-1.5 bg-slate-800 rounded-full mt-2 overflow-hidden flex"><div className="bg-emerald-500 rounded-full" style={{width:`${pct}%`}}/></div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Heatmap Compare View ──────────────────────────────────

function HeatmapCell({ score }) {
  if (score < 0) return <div className="w-5 h-4 rounded-sm bg-slate-800/50" title="no data"/>
  if (score === 1) return <div className="w-5 h-4 rounded-sm bg-emerald-500/80" title="PASS"/>
  return <div className="w-5 h-4 rounded-sm bg-red-500/80" title="FAIL"/>
}

function CompareView({ compareIds, runs }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    if (compareIds.length < 2) { setData(null); return }
    // Sort by started_at: oldest first (left), newest last (right)
    const runsMap = Object.fromEntries((runs||[]).map(r=>[r.run_id, r.started_at||0]))
    const sorted = [...compareIds].sort((a,b)=>(runsMap[a]||0)-(runsMap[b]||0))
    fetch(`/api/compare?run_ids=${sorted.join(',')}`).then(r=>r.json()).then(setData).catch(()=>{})
  }, [compareIds])

  if (compareIds.length < 2) return <div className="text-center py-12 text-slate-600">Select 2+ runs in sidebar to compare</div>
  if (!data) return <div className="text-center py-12 text-slate-600">Loading...</div>

  // Sort: oldest left, newest right
  const runsMapLocal = Object.fromEntries((runs||[]).map(r=>[r.run_id, r.started_at||0]))
  const sortedIds = [...compareIds].sort((a,b)=>(runsMapLocal[a]||0)-(runsMapLocal[b]||0))

  const unstable = data.heatmap.filter(r => !r.stable)
  const alwaysFail = data.heatmap.filter(r => r.always_fail)

  return (
    <div>
      <div className="flex items-center gap-4 mb-4">
        <h2 className="text-sm font-semibold text-white">Heatmap: {compareIds.length} runs</h2>
        <div className="flex gap-3 text-[10px] text-slate-500">
          <span><span className="inline-block w-3 h-3 rounded bg-emerald-500/80 mr-1"/>PASS</span>
          <span><span className="inline-block w-3 h-3 rounded bg-red-500/80 mr-1"/>FAIL</span>
          <span><span className="inline-block w-3 h-3 rounded bg-slate-800/50 mr-1"/>No data</span>
        </div>
      </div>

      {/* Summary + Run scores inline */}
      <div className="flex items-center gap-4 mb-3 flex-wrap">
        <div className="flex gap-3 text-xs">
          <span className="text-amber-400 font-bold">{unstable.length} unstable</span>
          <span className="text-red-400 font-bold">{alwaysFail.length} always fail</span>
          <span className="text-slate-400">{data.heatmap.length} total</span>
        </div>
        <div className="flex gap-2 flex-wrap">
          {sortedIds.map(rid => (
            <div key={rid} className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">
              <span className="font-mono">{rid}</span>: <span className="font-bold text-white">{(data.run_scores[rid]||0).toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>

      {/* Heatmap grid */}
      <div className="bg-slate-900/50 rounded-xl border border-slate-800/50 overflow-x-auto p-2">
        <table className="text-[10px]">
          <thead>
            <tr>
              <th className="text-left text-slate-600 font-normal pr-2 pb-0.5">Task</th>
              {sortedIds.map(rid=><th key={rid} className="text-center text-slate-600 font-mono font-normal px-0.5 pb-0.5">{rid}</th>)}
              <th className="text-left text-slate-600 font-normal pl-2 pb-0.5">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.heatmap.map(row=>(
              <tr key={row.task_id} className={`${!row.stable?'bg-amber-900/10':''} leading-none`}>
                <td className="pr-2 py-px font-mono text-slate-400">{row.task_id}</td>
                {sortedIds.map(rid=><td key={rid} className="px-0.5 py-px"><HeatmapCell score={row.runs[rid]?.score ?? -1}/></td>)}
                <td className="pl-2 py-px">
                  {row.always_pass && <span className="text-emerald-500 text-[10px]">stable pass</span>}
                  {row.always_fail && <span className="text-red-400 text-[10px]">always fail</span>}
                  {!row.stable && !row.always_fail && !row.always_pass && <span className="text-amber-400 text-[10px]">unstable</span>}
                  {row.stable && !row.always_pass && !row.always_fail && <span className="text-slate-600 text-[10px]">-</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Skills View ───────────────────────────────────────────

function SkillsView() {
  const [skills, setSkills] = useState({})
  const [systemPrompt, setSystemPrompt] = useState('')
  const [testText, setTestText] = useState('')
  const [testResult, setTestResult] = useState(null)
  const [expandedSkill, setExpandedSkill] = useState(null)
  const [showPrompt, setShowPrompt] = useState(false)

  useEffect(() => {
    fetch('/api/skills').then(r => r.json()).then(setSkills).catch(() => {})
    fetch('/api/prompt').then(r => r.json()).then(d => setSystemPrompt(d.prompt)).catch(() => {})
  }, [])

  const testClassify = async () => {
    if (!testText.trim()) return
    const r = await fetch(`/api/classify?task_text=${encodeURIComponent(testText)}`)
    setTestResult(await r.json())
  }

  return (
    <div>
      {/* System Prompt */}
      <div className="mb-4">
        <button onClick={() => setShowPrompt(!showPrompt)} className="flex items-center gap-2 text-sm font-semibold text-white hover:text-cyan-400 transition">
          <span>{showPrompt ? '▼' : '▶'}</span>
          <span>System Prompt</span>
          <span className="text-[10px] text-slate-600 font-normal">({systemPrompt.length} chars)</span>
        </button>
        {showPrompt && (
          <div className="mt-2 bg-slate-900/80 rounded-xl border border-slate-800/50 overflow-hidden">
            <pre className="p-4 text-xs text-slate-300 whitespace-pre-wrap max-h-[600px] overflow-y-auto font-mono leading-relaxed">{systemPrompt}</pre>
          </div>
        )}
      </div>

      <h2 className="text-sm font-semibold text-white mb-4">Skills ({Object.keys(skills).length})</h2>

      {/* Test classifier */}
      <div className="bg-slate-900/80 rounded-xl p-4 border border-slate-800/50 mb-4">
        <div className="text-[10px] uppercase tracking-wider text-slate-600 mb-2">Test classifier</div>
        <div className="flex gap-2">
          <input
            className="flex-1 bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
            placeholder="Enter task text to classify..."
            value={testText}
            onChange={e => setTestText(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && testClassify()}
          />
          <button onClick={testClassify} className="bg-purple-600 hover:bg-purple-500 px-4 py-2 rounded-lg text-xs font-semibold text-white">Classify</button>
        </div>
        {testResult && (
          <div className="mt-2 flex items-center gap-2">
            <SkillBadge skillId={testResult.skill_id} />
            <span className="text-xs text-slate-400">confidence: {(testResult.confidence * 100).toFixed(0)}%</span>
          </div>
        )}
      </div>

      {/* Skills list */}
      <div className="space-y-2">
        {Object.values(skills).map(s => (
          <div key={s.id} className="bg-slate-900/80 rounded-xl border border-slate-800/50 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-slate-800/30" onClick={() => setExpandedSkill(expandedSkill === s.id ? null : s.id)}>
              <div className="flex items-center gap-3">
                <span className="text-slate-500 text-xs">{expandedSkill === s.id ? '▼' : '▶'}</span>
                <SkillBadge skillId={s.id} />
                <span className="text-xs text-slate-400">{s.description}</span>
              </div>
            </div>
            {expandedSkill === s.id && s.prompt && (
              <div className="border-t border-slate-800/50">
                <pre className="px-4 py-3 text-[11px] text-slate-400 whitespace-pre-wrap max-h-[400px] overflow-y-auto font-mono leading-relaxed">{s.prompt}</pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Settings View ────────────────────────────────────────

const LLM_PRESETS = [
  { name: 'gpt-oss-120b', model: 'gpt-oss-120b', baseUrl: 'http://109.230.162.92:44334/v1', apiKey: '', inputPrice: 0, outputPrice: 0 },
  { name: 'qwen3.5-35b-a3b (self-hosted)', model: 'qwen3.5-35b-a3b', baseUrl: 'https://4090-2-48.neuraldeep.tech/v1', apiKey: '', inputPrice: 0, outputPrice: 0 },
]

function SettingsView({ appConfig, onConfigUpdate }) {
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [bitgnKey, setBitgnKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetch('/api/config/llm').then(r => r.json()).then(d => {
      setModel(d.model || '')
      setBaseUrl(d.openai_base_url || '')
      setApiKey(d.openai_api_key || '')
      setBitgnKey(d.bitgn_api_key || '')
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [])

  const applyPreset = (preset) => {
    setModel(preset.model)
    setBaseUrl(preset.baseUrl)
    setApiKey(preset.apiKey)
  }

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const r = await fetch('/api/config/llm', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, openai_base_url: baseUrl, openai_api_key: apiKey, bitgn_api_key: bitgnKey })
      })
      const d = await r.json()
      if (d.error) { alert(d.error); return }
      setSaved(true)
      if (onConfigUpdate) onConfigUpdate(d)
      setTimeout(() => setSaved(false), 3000)
    } finally {
      setSaving(false)
    }
  }

  if (!loaded) return <div className="text-center py-12 text-slate-600">Loading...</div>

  const inputCls = "w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50 font-mono"

  return (
    <div className="max-w-xl">
      <h2 className="text-sm font-semibold text-white mb-4">LLM Configuration</h2>

      <div className="bg-slate-900/80 rounded-xl p-4 border border-slate-800/50 mb-4">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Presets</div>
        <div className="flex gap-2 flex-wrap">
          {LLM_PRESETS.map(p => (
            <button key={p.name} onClick={() => applyPreset(p)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${
                model === p.model && baseUrl === p.baseUrl
                  ? 'bg-cyan-900/50 border-cyan-500/50 text-cyan-400'
                  : 'bg-slate-800/50 border-slate-700/50 text-slate-400 hover:border-slate-600 hover:text-slate-300'
              }`}>
              {p.name}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-slate-900/80 rounded-xl p-5 border border-slate-800/50 space-y-4">
        <div>
          <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1.5">Model name</label>
          <input className={inputCls} placeholder="gpt-4.1-2025-04-14" value={model} onChange={e => setModel(e.target.value)} />
          <p className="text-[10px] text-slate-600 mt-1">Model ID passed to the API (e.g. gpt-4o, gpt-oss-120b, claude-sonnet-4-20250514)</p>
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1.5">API endpoint</label>
          <input className={inputCls} placeholder="https://api.openai.com/v1" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} />
          <p className="text-[10px] text-slate-600 mt-1">Base URL for the OpenAI-compatible API (vLLM, LiteLLM, OpenRouter, etc.)</p>
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1.5">API token</label>
          <input className={inputCls} type="password" placeholder="sk-..." value={apiKey} onChange={e => setApiKey(e.target.value)} />
          <p className="text-[10px] text-slate-600 mt-1">API key for authentication</p>
        </div>
        <div className="border-t border-slate-800/50 pt-4">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1.5">BitGN API key</label>
          <input className={inputCls} type="password" placeholder="bgn-..." value={bitgnKey} onChange={e => setBitgnKey(e.target.value)} />
          <p className="text-[10px] text-slate-600 mt-1">Key for the BitGN leaderboard (required for full runs)</p>
        </div>
        <div className="flex items-center gap-3 pt-2">
          <button onClick={handleSave} disabled={saving} className="bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-700 disabled:text-slate-500 px-5 py-2 rounded-lg text-xs font-semibold text-white transition-all">
            {saving ? 'Saving...' : 'Save'}
          </button>
          {saved && <span className="text-xs text-emerald-400">Settings saved. Next run will use the new configuration.</span>}
        </div>
      </div>
      <div className="mt-4 bg-slate-900/50 rounded-xl p-4 border border-slate-800/50">
        <div className="text-[10px] uppercase tracking-wider text-slate-600 mb-2">Current active config</div>
        <div className="space-y-1 text-xs font-mono">
          <div><span className="text-slate-600">model:</span> <span className="text-cyan-400">{appConfig?.model || '—'}</span></div>
          <div><span className="text-slate-600">endpoint:</span> <span className="text-slate-400">{appConfig?.openai_base_url || '—'}</span></div>
          <div><span className="text-slate-600">token:</span> <span className="text-slate-400">{appConfig?.openai_api_key ? '••••' + appConfig.openai_api_key.slice(-4) : '—'}</span></div>
        </div>
      </div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────

export default function App() {
  const [runs, setRuns] = useState([])
  const [activeRunId, setActiveRunId] = useState(null)
  const [activeRun, setActiveRun] = useState(null)
  const [events, setEvents] = useState([])
  const [expandedTask, setExpandedTask] = useState(null)
  const [starting, setStarting] = useState(false)
  const [taskFilter, setTaskFilter] = useState('')
  const [concurrency, setConcurrency] = useState(5)
  const [repeatCount, setRepeatCount] = useState(1)
  const [repeatRemaining, setRepeatRemaining] = useState(0)
  const [stopOnFail, setStopOnFail] = useState(false)
  const [autoSubmit, setAutoSubmit] = useState(true)
  const [tab, setTab] = useState('run') // 'run' | 'compare' | 'skills' | 'settings'
  const [compareIds, setCompareIds] = useState([])
  const [appConfig, setAppConfig] = useState(null)
  const esRef = useRef(null)

  useEffect(()=>{const p=new URLSearchParams(window.location.search);const r=p.get('run');if(r)setActiveRunId(r)},[])
  useEffect(()=>{if(activeRunId)window.history.replaceState(null,'',`?run=${activeRunId}`)},[activeRunId])
  useEffect(()=>{const load=()=>fetch('/api/runs').then(r=>r.json()).then(setRuns).catch(()=>{});load();const i=setInterval(load,5000);return()=>clearInterval(i)},[])
  useEffect(()=>{fetch('/api/config').then(r=>r.json()).then(setAppConfig).catch(()=>{})},[])



  useEffect(()=>{
    if(!activeRunId)return
    if(esRef.current){esRef.current.close();esRef.current=null}
    setEvents([])

    // Always use SSE — server handles done runs by replaying saved events
    const es=new EventSource(`/api/runs/${activeRunId}/stream`)
    esRef.current=es
    es.addEventListener('snapshot',e=>setActiveRun(JSON.parse(e.data)))
    es.addEventListener('replay_done',()=>{es.close();esRef.current=null})

    const types=['run_start','run_done','run_error','batch_start','batch_done','task_start','task_instruction','task_classified','task_done','task_error','tool_start','tool_end','llm_start','llm_end','agent_output','fallback_submit','benchmark_info']
    for(const type of types){
      es.addEventListener(type,e=>{
        const d=JSON.parse(e.data);setEvents(p=>[...p,d])
        if(d.task_id){setActiveRun(p=>{if(!p)return p;const ts={...p.tasks};const t=ts[d.task_id]||{task_id:d.task_id,status:'pending',score:-1,tool_calls:0,wall_time_ms:0,instruction:'',skill_id:'',score_detail:[],harness_url:'',trial_id:''}
          if(type==='task_start')t.status='running';if(type==='task_instruction'){t.instruction=d.instruction;t.harness_url=d.harness_url||'';t.trial_id=d.trial_id||''};if(type==='task_classified'){t.skill_id=d.skill_id}
          if(type==='task_done'){t.status='done';t.score=d.score;t.tool_calls=d.tool_calls;t.wall_time_ms=d.wall_time_ms;t.score_detail=d.score_detail||[];t.skill_id=d.skill_id||t.skill_id;t.total_tokens=d.total_tokens||0;t.input_tokens=d.input_tokens||0;t.output_tokens=d.output_tokens||0}
          if(type==='task_error'){t.status='error';t.score=0};ts[d.task_id]={...t};const sc=Object.values(ts).filter(x=>x.score>=0);const ps=sc.filter(x=>x.score===1).length
          return{...p,tasks:ts,passed:ps,final_score:sc.length>0?(ps/sc.length)*100:0}})}
        if(type==='run_done')setActiveRun(p=>p?{...p,status:'done',final_score:d.final_score,passed:d.passed,wall_time_ms:d.wall_time_ms}:p)
        if(type==='run_error')setActiveRun(p=>p?{...p,status:'error'}:p)
      })
    }
    return()=>{es.close();esRef.current=null}
  },[activeRunId])

  const launchOneRun = useCallback(async()=>{
    setEvents([]);setExpandedTask(null);setActiveRun(null);setTab('run')
    const filter=taskFilter.trim()?taskFilter.trim().split(/[\s,]+/):null
    const r=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_filter:filter,concurrency,stop_on_fail:stopOnFail,auto_submit:autoSubmit})})
    const d=await r.json()
    setActiveRunId(d.run_id)
    return d.run_id
  },[taskFilter,concurrency,stopOnFail])

  const startRun = useCallback(async()=>{
    setStarting(true)
    const total = repeatCount
    setRepeatRemaining(total)
    try {
      for (let i = 0; i < total; i++) {
        setRepeatRemaining(total - i)
        const runId = await launchOneRun()
        if (total > 1) {
          // Wait for run to finish before starting next
          await new Promise(resolve => {
            const poll = setInterval(async () => {
              try {
                const r = await fetch(`/api/runs/${runId}`).then(r=>r.json())
                if (r.status === 'done' || r.status === 'error') {
                  clearInterval(poll)
                  resolve()
                }
              } catch { clearInterval(poll); resolve() }
            }, 5000)
          })
        }
      }
    } finally { setStarting(false); setRepeatRemaining(0) }
  },[launchOneRun, repeatCount])

  const toggleCompare = useCallback((rid)=>{
    setCompareIds(prev=>prev.includes(rid)?prev.filter(x=>x!==rid):[...prev,rid])
  },[])
  const deleteRun = useCallback(async(rid)=>{
    await fetch(`/api/runs/${rid}`,{method:'DELETE'})
    setRuns(p=>p.filter(r=>r.run_id!==rid))
    setCompareIds(p=>p.filter(x=>x!==rid))
    if(activeRunId===rid){setActiveRunId(null);setActiveRun(null);setEvents([])}
  },[activeRunId])

  const sortedTasks=activeRun?Object.values(activeRun.tasks).sort((a,b)=>a.task_id.localeCompare(b.task_id,undefined,{numeric:true})):[]
  const scored=sortedTasks.filter(t=>t.score>=0), passed=scored.filter(t=>t.score===1).length, failed=scored.filter(t=>t.score===0).length, running=sortedTasks.filter(t=>t.status==='running').length

  // Cost calculation
  const runCost = (() => {
    if (!activeRun) return null
    const preset = LLM_PRESETS.find(p => p.model === activeRun.model)
    if (!preset || (!preset.inputPrice && !preset.outputPrice)) return null
    let totalIn = 0, totalOut = 0
    for (const t of Object.values(activeRun.tasks)) {
      totalIn += t.input_tokens || 0
      totalOut += t.output_tokens || 0
    }
    const cost = (totalIn / 1_000_000) * preset.inputPrice + (totalOut / 1_000_000) * preset.outputPrice
    return { cost, totalIn, totalOut }
  })()

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans flex">
      <RunSidebar runs={runs} activeRunId={activeRunId} onSelect={(id)=>{setActiveRunId(id);setTab('run')}} compareIds={compareIds} onToggleCompare={toggleCompare} onDelete={deleteRun}/>
      <div className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-800/50 bg-slate-900/30 backdrop-blur-xl sticky top-0 z-20">
          <div className="px-6 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-white font-bold text-sm">P1</div>
              <div>
                <h1 className="text-sm font-semibold text-white leading-none">PAC1 Agent Dashboard</h1>
                <p className="text-[10px] text-slate-600">{activeRunId?<span>Run: <span className="text-cyan-500 font-mono">{activeRunId}</span></span>:'OpenAI Agents SDK + Skills'}{appConfig&&<span className="ml-2 text-slate-600">{appConfig.model}</span>}</p>
              </div>
              {/* Tabs */}
              <div className="flex gap-1 ml-4">
                <button onClick={()=>setTab('run')} className={`text-[10px] px-3 py-1 rounded ${tab==='run'?'bg-cyan-900/50 text-cyan-400':'text-slate-600 hover:text-slate-400'}`}>Run</button>
                <button onClick={()=>setTab('compare')} className={`text-[10px] px-3 py-1 rounded ${tab==='compare'?'bg-purple-900/50 text-purple-400':'text-slate-600 hover:text-slate-400'}`}>Compare {compareIds.length>0&&`(${compareIds.length})`}</button>
                <button onClick={()=>{setCompareIds(runs.map(r=>r.run_id));setTab('compare')}} className="text-[10px] px-2 py-1 rounded text-slate-600 hover:text-purple-400">All</button>
                <button onClick={()=>setTab('skills')} className={`text-[10px] px-3 py-1 rounded ${tab==='skills'?'bg-green-900/50 text-green-400':'text-slate-600 hover:text-slate-400'}`}>Skills</button>
                <button onClick={()=>setTab('settings')} className={`text-[10px] px-3 py-1 rounded ${tab==='settings'?'bg-amber-900/50 text-amber-400':'text-slate-600 hover:text-slate-400'}`}>Settings</button>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <select value={appConfig?.model||''} onChange={e=>{
                const name=e.target.value
                const preset=LLM_PRESETS.find(p=>p.model===name)
                if(preset){
                  fetch('/api/config/llm',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:preset.model,openai_base_url:preset.baseUrl,openai_api_key:preset.apiKey})}).then(r=>r.json()).then(d=>setAppConfig(p=>({...p,model:d.model,openai_base_url:d.openai_base_url,openai_api_key:d.openai_api_key})))
                }
              }} className="bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-cyan-400 focus:outline-none focus:border-cyan-500/50 cursor-pointer">
                {LLM_PRESETS.map(p=><option key={p.model} value={p.model}>{p.name}</option>)}
              </select>
              <input className="bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 w-40 focus:outline-none focus:border-cyan-500/50" placeholder="t01 t02... or all" value={taskFilter} onChange={e=>setTaskFilter(e.target.value)}/>
              <div className="flex items-center gap-2 bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5">
                <label className="text-[10px] text-slate-500">Temp</label>
                <input type="range" min="0" max="2" step="0.1" value={appConfig?.temperature??1} onChange={e=>{const t=Number(e.target.value);setAppConfig(p=>({...p,temperature:t}));fetch('/api/config/temperature',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({temperature:t})})}} className="w-20 h-1.5 accent-amber-500"/>
                <input type="number" min="0" max="2" step="0.1" value={appConfig?.temperature??1} onChange={e=>{const t=Math.min(2,Math.max(0,Number(e.target.value)));setAppConfig(p=>({...p,temperature:t}));fetch('/api/config/temperature',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({temperature:t})})}} className="w-12 bg-transparent text-xs font-mono text-amber-400 text-center focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"/>
              </div>
              <div className="flex items-center gap-2 bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5">
                <label className="text-[10px] text-slate-500">Agents</label>
                <input type="range" min="1" max="30" value={concurrency} onChange={e=>setConcurrency(Number(e.target.value))} className="w-20 h-1.5 accent-cyan-500"/>
                <input type="number" min="1" max="30" value={concurrency} onChange={e=>setConcurrency(Math.min(30,Math.max(1,Number(e.target.value))))} className="w-10 bg-transparent text-xs font-mono text-cyan-400 text-center focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"/>
              </div>
              <div className="flex items-center gap-2 bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5">
                <label className="text-[10px] text-slate-500">Repeat</label>
                <input type="number" min="1" max="50" value={repeatCount} onChange={e=>setRepeatCount(Math.min(50,Math.max(1,Number(e.target.value))))} className="w-10 bg-transparent text-xs font-mono text-purple-400 text-center focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"/>
                <label className="flex items-center gap-1 cursor-pointer" title="Stop run on first task failure and start next">
                  <input type="checkbox" checked={stopOnFail} onChange={e=>setStopOnFail(e.target.checked)} className="w-3 h-3 accent-red-500"/>
                  <span className="text-[10px] text-slate-500">Fail→Next</span>
                </label>
                <label className="flex items-center gap-1 cursor-pointer" title="Auto-submit to leaderboard on completion">
                  <input type="checkbox" checked={autoSubmit} onChange={e=>setAutoSubmit(e.target.checked)} className="w-3 h-3 accent-emerald-500"/>
                  <span className="text-[10px] text-slate-500">Submit</span>
                </label>
              </div>
              {activeRun?.status==='done'&&!autoSubmit&&<button onClick={()=>fetch(`/api/runs/${activeRunId}/submit`,{method:'POST'}).then(r=>r.json()).then(d=>d.error?alert(d.error):alert(`Submitted! Score: ${d.score?.toFixed(1)}%`))} className="bg-emerald-600 hover:bg-emerald-500 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all">Submit</button>}
              {(activeRun?.status==='running'||runs.some(r=>r.run_id===activeRunId&&r.status==='running'))&&<button onClick={()=>fetch(`/api/runs/${activeRunId}/stop`,{method:'POST'}).then(()=>setActiveRun(p=>p?{...p,status:'error'}:p))} className="bg-red-600 hover:bg-red-500 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all">Stop</button>}
              <button onClick={startRun} disabled={starting} className="bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all">{starting?(repeatRemaining>1?`Run ${repeatCount-repeatRemaining+1}/${repeatCount}...`:'Running...'):'Run'}</button>
            </div>
          </div>
        </header>

        <main className="px-6 py-5 flex-1">
          {/* Compare tab */}
          {tab === 'compare' && <CompareView compareIds={compareIds} runs={runs}/>}

          {/* Skills tab */}
          {tab === 'skills' && <SkillsView/>}

          {/* Settings tab */}
          {tab === 'settings' && <SettingsView appConfig={appConfig} onConfigUpdate={(d) => setAppConfig(p => ({ ...p, model: d.model, openai_base_url: d.openai_base_url, openai_api_key: d.openai_api_key }))} />}

          {/* Run tab */}
          {tab === 'run' && activeRun && (
            <>
              {/* Share link */}
              <div className="flex items-center gap-2 mb-3">
                <span className="text-[10px] text-slate-600">Link:</span>
                <code className="text-[10px] text-cyan-500 bg-slate-900 px-2 py-0.5 rounded cursor-pointer hover:bg-slate-800" onClick={()=>{navigator.clipboard.writeText(window.location.href)}}>
                  {window.location.origin}?run={activeRunId}
                </code>
                <span className="text-[10px] text-slate-700">(click to copy)</span>
                {activeRun.wall_time_ms > 0 && <span className="text-[10px] text-slate-500 ml-auto">Total time: {(activeRun.wall_time_ms/1000).toFixed(1)}s</span>}
                {activeRun.status === 'running' && activeRun.started_at && <span className="text-[10px] text-amber-400 ml-auto animate-pulse">Running...</span>}
              </div>
              <div className={`grid gap-3 mb-4 ${runCost ? 'grid-cols-7' : 'grid-cols-6'}`}>
                <StatCard value={`${(activeRun.final_score||0).toFixed(1)}%`} label="Score"/><StatCard value={passed} label="Passed" color="text-emerald-400"/><StatCard value={failed} label="Failed" color="text-red-400"/><StatCard value={running} label="Running" color="text-amber-400"/><StatCard value={sortedTasks.length} label="Total" color="text-slate-300"/><StatCard value={activeRun.wall_time_ms>0?`${(activeRun.wall_time_ms/1000).toFixed(0)}s`:activeRun.status==='running'?'...':'--'} label="Wall Time" color="text-slate-300"/>
                {runCost && <StatCard value={`$${runCost.cost < 0.01 ? runCost.cost.toFixed(4) : runCost.cost.toFixed(2)}`} label="Cost" color="text-green-400"/>}
              </div>
              <div className="mb-5"><ProgressBar passed={passed} failed={failed} total={sortedTasks.length}/></div>
              <div className="bg-slate-900/50 rounded-xl border border-slate-800/50 overflow-hidden">
                <div className="grid grid-cols-[32px_52px_1fr_110px_60px_60px_64px_64px] gap-2 px-4 py-2 bg-slate-800/30 text-[10px] text-slate-600 uppercase tracking-wider"><span/><span>ID</span><span>Task</span><span>Skill</span><span>Score</span><span>Tools</span><span className="text-right">Tokens</span><span className="text-right">Time</span></div>
                {sortedTasks.map(task=>(<div key={task.task_id}><TaskRow task={task} isExpanded={expandedTask===task.task_id} onToggle={()=>setExpandedTask(expandedTask===task.task_id?null:task.task_id)}/>{expandedTask===task.task_id&&<TaskPanel task={task} events={events} runId={activeRunId}/>}</div>))}
              </div>
            </>
          )}

          {tab === 'run' && !activeRun && (
            <div className="flex flex-col items-center justify-center py-32 text-slate-700">
              <div className="h-20 w-20 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center mb-6"><svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg></div>
              <p className="text-lg text-slate-500">Select a run or start a new one</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
