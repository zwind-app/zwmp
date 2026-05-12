import { Clipboard, ExternalLink, FileCode2, FolderTree, Github, Play, RefreshCw, Smartphone } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createGenerationJob, createProjectionJob, getGenerationJob, getProjectionJob } from "./api";
import type { GenerationResult, JobResponse, MediaType, ProjectionItem, ProjectionMedia, ProjectionNode, ProjectionResult } from "./types";

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
            setSelectedItemId(result.projection_preview.items[0]?.id ?? null);
          } else if ("projection" in next.result) {
            setProjection(next.result.projection);
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
    const created = await createGenerationJob(url, mediaType);
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
          <button className="primary" onClick={generate} disabled={job?.status === "running"}>
            <RefreshCw size={16} />
            Generate
          </button>
          <div className="progress">
            <div style={progressStyle} />
          </div>
          <Status job={job} error={error} cacheHit={generationResult?.cache_hit} />
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
            <span><FolderTree size={18} /> Projection</span>
            <span className="meta">{projection.items.length} items / {projection.media.length} media</span>
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

function Status({ job, error, cacheHit }: { job: JobResponse | null; error: string | null; cacheHit?: boolean }) {
  return (
    <div className="status">
      <strong>{job ? `${job.status} · ${job.phase}` : "idle"}</strong>
      <span>{cacheHit ? "cache hit" : job ? `${Math.round(job.progress * 100)}%` : "ready"}</span>
      {error ? <p>{error}</p> : null}
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
  if (!nodes.length) return <div className="empty">Generated projection will appear here.</div>;
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

