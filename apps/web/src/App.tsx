import { Clipboard, ExternalLink, FileCode2, FolderTree, Github, Info, Play, RefreshCw, Smartphone } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createGenerationJob, createProjectionJob, getGenerationJob, getProjectionJob } from "./api";
import type { GenerationResult, JobResponse, MediaType, ProjectionItem, ProjectionMedia, ProjectionNode, ProjectionResult, RuntimeNotice } from "./types";

const sampleRule = `source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
media_type=video
max_items=30
`;

const emptyProjection: ProjectionResult = {
  tree: [],
  items: [],
  media: [],
  debug_events: [],
  warnings: []
};

export function App() {
  const [url, setUrl] = useState("https://example.com/videos");
  const [mediaType, setMediaType] = useState<MediaType>("video");
  const [job, setJob] = useState<JobResponse | null>(null);
  const [ruleText, setRuleText] = useState(sampleRule);
  const [projection, setProjection] = useState<ProjectionResult>(emptyProjection);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [forceNetworkSniff, setForceNetworkSniff] = useState(false);
  const [fastMode, setFastMode] = useState(true);
  const [maxItems, setMaxItems] = useState(30);
  const [sampleItems, setSampleItems] = useState(8);
  const [candidateGroups, setCandidateGroups] = useState(6);
  const [validateHypotheses, setValidateHypotheses] = useState(5);
  const [validationLimit, setValidationLimit] = useState(24);
  const [detailProbes, setDetailProbes] = useState(3);
  const [scrollSteps, setScrollSteps] = useState(3);
  const [desktopMode, setDesktopMode] = useState(false);
  const [runtimeNotices, setRuntimeNotices] = useState<RuntimeNotice[]>([]);

  const generationResult = job?.result && "rule_text" in job.result ? (job.result as GenerationResult) : null;
  const selectedItem = projection.items.find((item) => item.id === selectedItemId) ?? projection.items[0] ?? null;
  const selectedMedia = selectedItem ? projection.media.find((entry) => selectedItem.media_ids.includes(entry.id)) ?? null : null;

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = job.type === "generation" ? await getGenerationJob(job.id) : await getProjectionJob(job.id);
        setJob(next);
        if (next.status === "succeeded" && next.result) {
          if ("rule_text" in next.result) {
            const result = next.result as GenerationResult;
            setRuleText(result.rule_text);
            setProjection(result.projection_preview);
            setRuntimeNotices(result.runtime_notices ?? []);
            setSelectedItemId(result.projection_preview.items[0]?.id ?? null);
          } else if ("projection" in next.result) {
            setProjection(next.result.projection);
            setRuntimeNotices(next.result.runtime_notices ?? []);
            setSelectedItemId(next.result.projection.items[0]?.id ?? null);
          }
        }
        if (next.status === "failed") setError(next.error ?? "Job failed");
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : String(pollError));
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [job]);

  const progressStyle = useMemo(() => ({ width: `${Math.round((job?.progress ?? 0) * 100)}%` }), [job?.progress]);

  async function generate() {
    setError(null);
    setProjection(emptyProjection);
    setRuntimeNotices([]);
    const created = await createGenerationJob(url, mediaType, {
      force_refresh: forceRefresh,
      force_network_sniff: forceNetworkSniff,
      fast_mode: fastMode,
      max_items: maxItems,
      sample_items: sampleItems,
      max_candidate_groups: candidateGroups,
      validate_hypotheses: validateHypotheses,
      validation_limit: validationLimit,
      detail_probes: detailProbes,
      scroll_steps: scrollSteps,
      desktop: desktopMode
    });
    setJob(created);
  }

  async function previewEditedRule() {
    setError(null);
    const created = await createProjectionJob(ruleText);
    setJob(created);
  }

  async function copyRule() {
    await navigator.clipboard.writeText(ruleText);
  }

  return (
    <main className="shell">
      <nav className="topbar">
        <div className="brand">
          <span className="mark">ZW</span>
          <span>
            <strong>ZWMP</strong>
            <small>Web Media Projection</small>
          </span>
        </div>
        <div className="links">
          <a href="https://github.com/zwind-app/zwmp" target="_blank" rel="noreferrer"><Github size={16} /> GitHub</a>
          <a href="https://apps.apple.com/us/app/zwind-webdav-server-player/id6755239096" target="_blank" rel="noreferrer"><Smartphone size={16} /> Zwind</a>
        </div>
      </nav>

      <section className="workspace">
        <aside className="controlPane">
          <div className="panelTitle">
            <Play size={18} />
            <span>Generate Rule</span>
          </div>
          <label className="field">
            <span>Source URL</span>
            <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/videos" />
          </label>
          <div className="field">
            <span>Media Type</span>
            <div className="segments">
              {(["video", "audio", "image", "all"] as MediaType[]).map((type) => (
                <button className={mediaType === type ? "active" : ""} key={type} onClick={() => setMediaType(type)}>
                  {type}
                </button>
              ))}
            </div>
          </div>
          <div className="options">
            <OptionToggle
              label="Force refresh"
              checked={forceRefresh}
              onChange={setForceRefresh}
              tooltip="Ignore rule generation cache and analyze the URL again."
            />
            <OptionToggle
              label="Network sniff"
              checked={forceNetworkSniff}
              onChange={setForceNetworkSniff}
              tooltip="Capture browser network requests to find preloaded media URLs. Requires Playwright for full results."
            />
            <OptionToggle
              label="Fast mode"
              checked={fastMode}
              onChange={setFastMode}
              tooltip="Emit v3 fast_mode=true in generated rules. The reference v3 runtime enforces this for generated rules."
              disabled
            />
            <label className="numberOption">
              <span>Max items <Tooltip text="Limit how many listing items are parsed and previewed." /></span>
              <input type="number" min={1} max={200} value={maxItems} onChange={(event) => setMaxItems(Number(event.target.value) || 30)} />
            </label>
            <details className="advancedOptions">
              <summary>v3 advanced</summary>
              <NumberOption label="Samples" value={sampleItems} min={1} max={20} onChange={setSampleItems} tooltip="Card samples collected per candidate group." />
              <NumberOption label="Groups" value={candidateGroups} min={1} max={12} onChange={setCandidateGroups} tooltip="Top visual/repeated candidate groups to analyze." />
              <NumberOption label="Hypotheses" value={validateHypotheses} min={1} max={8} onChange={setValidateHypotheses} tooltip="Rule hypotheses validated before finalization." />
              <NumberOption label="Validation limit" value={validationLimit} min={1} max={100} onChange={setValidationLimit} tooltip="Candidate nodes inspected per selector during dry-run validation." />
              <NumberOption label="Detail probes" value={detailProbes} min={0} max={12} onChange={setDetailProbes} tooltip="Detail/intermediate pages opened for each hypothesis." />
              <NumberOption label="Scroll steps" value={scrollSteps} min={0} max={10} onChange={setScrollSteps} tooltip="Auto-scroll passes for lazy-loaded listing pages." />
              <OptionToggle label="Desktop viewport" checked={desktopMode} onChange={setDesktopMode} tooltip="Use desktop viewport instead of the default mobile viewport." />
            </details>
          </div>
          <button className="primary" onClick={generate} disabled={job?.status === "running"}>
            <RefreshCw size={16} />
            Generate
          </button>
          <div className="progress">
            <div style={progressStyle} />
          </div>
          <Status job={job} error={error} cacheHit={generationResult?.cache_hit} />
          <RuntimeNotices notices={generationResult?.runtime_notices ?? runtimeNotices} />
          <V3Summary result={generationResult} />
          <DebugTimeline events={[...(job?.debug_events ?? []), ...projection.debug_events]} />
        </aside>

        <section className="rulePane">
          <div className="paneHeader">
            <span><FileCode2 size={18} /> Rule</span>
            <div>
              <button className="ghost" onClick={copyRule}><Clipboard size={15} /> Copy</button>
              <button className="ghost" onClick={previewEditedRule}><Play size={15} /> Preview</button>
            </div>
          </div>
          <textarea spellCheck={false} value={ruleText} onChange={(event) => setRuleText(event.target.value)} />
          <div className="warnings">
            {projection.warnings.map((warning) => <p key={warning}>{warning}</p>)}
          </div>
        </section>

        <section className="previewPane">
          <div className="paneHeader">
            <span><FolderTree size={18} /> Resources</span>
            <span className="meta">{projection.items.length} items / {projection.media.length} resources</span>
          </div>
          <div className="previewGrid">
            <Tree nodes={projection.tree} onSelect={setSelectedItemId} selectedItemId={selectedItem?.id ?? null} />
            <MediaPanel item={selectedItem} media={selectedMedia} sessionId={job?.id ?? ""} />
          </div>
        </section>
      </section>
    </main>
  );
}

function NumberOption({ label, value, min, max, onChange, tooltip }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void; tooltip: string }) {
  return (
    <label className="numberOption compact">
      <span>{label} <Tooltip text={tooltip} /></span>
      <input type="number" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value) || min)} />
    </label>
  );
}

function OptionToggle({ label, checked, onChange, tooltip, disabled = false }: { label: string; checked: boolean; onChange: (value: boolean) => void; tooltip: string; disabled?: boolean }) {
  return (
    <label className={`toggleOption${disabled ? " disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
      <Tooltip text={tooltip} />
    </label>
  );
}

function Tooltip({ text }: { text: string }) {
  return (
    <span className="tooltip" title={text} aria-label={text}>
      <Info size={13} />
    </span>
  );
}

function Status({ job, error, cacheHit }: { job: JobResponse | null; error: string | null; cacheHit?: boolean }) {
  return (
    <div className="status">
      <strong>{job ? `${job.status} · ${job.phase}` : "idle"}</strong>
      <span>{cacheHit ? "cache hit" : job ? `${Math.round(job.progress * 100)}%` : "ready"}</span>
      {error ? <p>{error}</p> : null}
    </div>
  );
}

function RuntimeNotices({ notices }: { notices: RuntimeNotice[] }) {
  if (!notices.length) return null;
  return (
    <div className="runtimeNotices">
      {notices.map((notice) => (
        <div className="notice" key={`${notice.kind}-${notice.message}`}>
          <strong>{notice.kind.replace("_", " ")}</strong>
          <p>{notice.message}</p>
          <small>{notice.action}</small>
        </div>
      ))}
    </div>
  );
}

function V3Summary({ result }: { result: GenerationResult | null }) {
  if (!result?.v3) return null;
  const validations = result.v3.validations ?? [];
  const groups = result.v3.evidence?.candidate_groups ?? [];
  return (
    <div className="v3Summary">
      <strong>v3 evidence</strong>
      <p>{result.v3.confidence ? `confidence ${result.v3.confidence}` : "confidence pending"} · {result.v3.used_ai ? "AI finalized" : "local finalized"}</p>
      {result.v3.reasoning ? <p>{result.v3.reasoning}</p> : null}
      <div className="v3Metrics">
        <span>{groups.length} groups</span>
        <span>{validations.length} validations</span>
        <span>{result.v3.evidence?.lazy_load_observed ? "lazy load observed" : "no lazy signal"}</span>
      </div>
      {validations.slice(0, 3).map((validation) => (
        <div className="validationCard" key={validation.hypothesis_id}>
          <span>{validation.hypothesis_id}</span>
          <strong>{Math.round(validation.quality_score * 100)}%</strong>
          <small>{validation.listing.visible_candidate_count}/{validation.listing.candidate_count} visible · link {Math.round(validation.listing.link_coverage * 100)}%</small>
        </div>
      ))}
    </div>
  );
}

function DebugTimeline({ events }: { events: { phase: string; message: string }[] }) {
  return (
    <details className="debug" open>
      <summary>Debug timeline</summary>
      {events.slice(-8).map((event, index) => (
        <div className="event" key={`${event.phase}-${index}`}>
          <span>{event.phase}</span>
          <p>{event.message}</p>
        </div>
      ))}
    </details>
  );
}

function Tree({ nodes, selectedItemId, onSelect }: { nodes: ProjectionNode[]; selectedItemId: string | null; onSelect: (id: string) => void }) {
  if (!nodes.length) return <div className="empty">Parsed resources will appear here.</div>;
  return (
    <div className="tree">
      {nodes.map((node) => (
        <TreeNode key={node.id} node={node} selectedItemId={selectedItemId} onSelect={onSelect} depth={0} />
      ))}
    </div>
  );
}

function TreeNode({ node, depth, selectedItemId, onSelect }: { node: ProjectionNode; depth: number; selectedItemId: string | null; onSelect: (id: string) => void }) {
  const selected = Boolean(node.item_id && node.item_id === selectedItemId);
  return (
    <div>
      <button className={`treeNode ${selected ? "selected" : ""}`} style={{ paddingLeft: 10 + depth * 14 }} onClick={() => node.item_id && onSelect(node.item_id)}>
        <span>{node.kind === "directory" ? "▸" : "·"}</span>
        {node.name}
      </button>
      {node.children.map((child) => <TreeNode key={child.id} node={child} selectedItemId={selectedItemId} onSelect={onSelect} depth={depth + 1} />)}
    </div>
  );
}

function MediaPanel({ item, media, sessionId }: { item: ProjectionItem | null; media: ProjectionMedia | null; sessionId: string }) {
  if (!item) return <div className="empty">Select an item to inspect media.</div>;
  const proxyUrl = media ? `/api/proxy/${sessionId}/${media.id}` : null;
  return (
    <div className="mediaPanel">
      {item.thumbnail_url ? <img className="thumb" src={item.thumbnail_url} alt="" /> : <div className="thumb placeholder" />}
      <h2>{item.title}</h2>
      <a href={item.detail_url} target="_blank" rel="noreferrer">{item.detail_url} <ExternalLink size={13} /></a>
      {item.warning ? <p className="warning">{item.warning}</p> : null}
      {media ? <MediaPreview media={media} proxyUrl={proxyUrl} /> : <p className="muted">No direct media found yet.</p>}
    </div>
  );
}

function MediaPreview({ media, proxyUrl }: { media: ProjectionMedia; proxyUrl: string | null }) {
  const src = media.requires_proxy && proxyUrl ? proxyUrl : media.url;
  if (media.type === "image") return <img className="assetPreview" src={src} alt="" />;
  if (media.type === "audio") return <audio controls src={src} />;
  if (media.type === "video" || media.type === "all") return <video controls src={src} />;
  return <a href={src}>{src}</a>;
}
