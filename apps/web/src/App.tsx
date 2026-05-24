import { Clipboard, ExternalLink, FileCode2, FolderTree, Github, Info, Languages, Play, RefreshCw, Share2, Smartphone } from "lucide-react";
import Hls from "hls.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { cancelJob, createGenerationJob, createProjectionJob, createShare, getGenerationJob, getProjectionJob, getPublicConfig, getShare } from "./api";
import type { GenerationPartialResult, GenerationResult, JobResponse, MediaType, ProjectionItem, ProjectionMedia, ProjectionNode, ProjectionResult, PublicConfig, RuntimeNotice } from "./types";

type Locale = "en" | "zh";

const fallbackConfig: PublicConfig = {
  site: {
    default_locale: "en",
    supported_locales: ["en", "zh"],
    links: {
      github: "https://github.com/zwind-app/zwmp",
      zwind: "https://apps.apple.com/us/app/zwind-webdav-server-player/id6755239096"
    },
    seo: {
      en: {
        title: "ZWMP - Web Media Projection Rule Generator",
        description: "Generate, validate, preview, and share open Web Media Projection rules for video, audio, and image resources.",
        keywords: ["ZWMP", "Web Media Projection", "WebDAV media", "video rule generator"]
      },
      zh: {
        title: "ZWMP - Web Media Projection 规则生成器",
        description: "生成、校验、预览和分享开放的 Web Media Projection 规则。",
        keywords: ["ZWMP", "Web Media Projection", "WebDAV 媒体", "视频规则生成器"]
      }
    },
    guidance: {
      en: "Enter a listing URL to generate a .wm rule, or paste an existing rule and preview the projected resources directly.",
      zh: "输入列表页 URL 生成 .wm 规则，或直接粘贴已有规则并预览投影后的媒体资源。"
    }
  }
};

const text = {
  en: {
    generateRule: "Generate Rule",
    sourceUrl: "Source URL",
    mediaType: "Media Type",
    networkSniff: "Network sniff",
    networkSniffTip: "Capture browser network requests to find preloaded media URLs.",
    fastMode: "Fast mode",
    fastModeTip: "Emit v3 fast_mode=true in generated rules.",
    maxItems: "Max items",
    maxItemsTip: "Limit how many listing items are parsed and previewed.",
    advanced: "v3 advanced",
    samples: "Samples",
    groups: "Groups",
    hypotheses: "Hypotheses",
    validationLimit: "Validation limit",
    detailProbes: "Detail probes",
    scrollSteps: "Scroll steps",
    desktopViewport: "Desktop viewport",
    generate: "Generate",
    copy: "Copy",
    preview: "Preview",
    share: "Share",
    rule: "Rule",
    resources: "Resources",
    ready: "ready",
    idle: "idle",
    cacheHit: "cache hit",
    debugTimeline: "Progress timeline",
    parsedResources: "Parsed resources will appear here.",
    selectItem: "Select an item to inspect media.",
    noMedia: "No direct media found yet.",
    directMedia: "Direct media",
    copied: "Rule copied.",
    shared: "Share link copied.",
    localFinalized: "local finalized",
    aiFinalized: "AI finalized",
    openSource: "Open-source AGPL implementation with a CC BY rule specification.",
    manual: "Paste or edit a rule here, then preview it without generating."
  },
  zh: {
    generateRule: "生成规则",
    sourceUrl: "Source URL",
    mediaType: "媒体类型",
    networkSniff: "网络嗅探",
    networkSniffTip: "捕获浏览器网络请求，用于发现预加载的媒体 URL。",
    fastMode: "Fast mode",
    fastModeTip: "生成的 v3 规则会写入 fast_mode=true。",
    maxItems: "最大条目数",
    maxItemsTip: "限制解析和预览的列表条目数量。",
    advanced: "v3 高级选项",
    samples: "样本数",
    groups: "候选组",
    hypotheses: "规则假设",
    validationLimit: "校验数量",
    detailProbes: "详情探测",
    scrollSteps: "滚动次数",
    desktopViewport: "桌面视口",
    generate: "生成",
    copy: "复制",
    preview: "预览",
    share: "分享",
    rule: "规则",
    resources: "资源",
    ready: "就绪",
    idle: "空闲",
    cacheHit: "命中缓存",
    debugTimeline: "进度时间线",
    parsedResources: "解析出的资源会显示在这里。",
    selectItem: "选择一个条目查看媒体。",
    noMedia: "暂未发现直连媒体。",
    directMedia: "直连媒体",
    copied: "规则已复制。",
    shared: "分享链接已复制。",
    localFinalized: "本地推断",
    aiFinalized: "AI 推断",
    openSource: "AGPL 开源实现，规则规范采用 CC BY 许可。",
    manual: "可在这里粘贴或修改规则，然后直接预览，无需重新生成。"
  }
};

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
  const [config, setConfig] = useState<PublicConfig>(fallbackConfig);
  const [locale, setLocale] = useState<Locale>(() => (localStorage.getItem("zwmp_locale") as Locale) || "en");
  const t = text[locale];
  const [url, setUrl] = useState("https://example.com/videos");
  const [mediaType, setMediaType] = useState<MediaType>("video");
  const [job, setJob] = useState<JobResponse | null>(null);
  const [ruleText, setRuleText] = useState(sampleRule);
  const [projection, setProjection] = useState<ProjectionResult>(emptyProjection);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [siteProfile, setSiteProfile] = useState<GenerationResult["site_profile"] | null>(null);
  const jobRef = useRef<JobResponse | null>(null);

  const generationResult = job?.result && "rule_text" in job.result ? (job.result as GenerationResult) : null;
  const selectedItem = projection.items.find((item) => item.id === selectedItemId) ?? projection.items[0] ?? null;
  const selectedMedia = selectedItem ? projection.media.filter((entry) => selectedItem.media_ids.includes(entry.id)) : [];
  const progressStyle = useMemo(() => ({ width: `${Math.round((job?.progress ?? 0) * 100)}%` }), [job?.progress]);

  useEffect(() => {
    getPublicConfig().then(setConfig).catch(() => setConfig(fallbackConfig));
  }, []);

  useEffect(() => {
    jobRef.current = job;
  }, [job]);

  useEffect(() => {
    const cancelActiveOnClose = () => {
      const active = jobRef.current;
      if (!active || !["queued", "running"].includes(active.status)) return;
      navigator.sendBeacon?.(`/api/jobs/${active.id}/cancel`, new Blob(["{}"], { type: "application/json" }));
    };
    window.addEventListener("pagehide", cancelActiveOnClose);
    return () => window.removeEventListener("pagehide", cancelActiveOnClose);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const shareId = params.get("share");
    if (!shareId) return;
    getShare(shareId)
      .then((share) => {
        setRuleText(share.rule_text);
        setProjection(share.projection);
        setSiteProfile(share.site_profile ?? null);
        setRuntimeNotices(share.runtime_notices ?? []);
        setSelectedItemId(share.projection.items[0]?.id ?? null);
        const source = sourceFromRule(share.rule_text);
        if (source) setUrl(source);
      })
      .catch((loadError) => setError(loadError instanceof Error ? loadError.message : String(loadError)));
  }, []);

  useEffect(() => {
    localStorage.setItem("zwmp_locale", locale);
    const seo = config.site.seo[locale] ?? config.site.seo[config.site.default_locale] ?? fallbackConfig.site.seo.en;
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = seo.title;
    setMeta("description", seo.description);
    setMeta("keywords", seo.keywords.join(", "));
  }, [config, locale]);

  useEffect(() => {
    const source = sourceFromRule(ruleText);
    if (source && source !== url) setUrl(source);
  }, [ruleText]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = job.type === "generation" ? await getGenerationJob(job.id) : await getProjectionJob(job.id);
        setJob(next);
        if (next.partial_result) {
          applyJobPartial(next.partial_result);
        }
        if (next.status === "succeeded" && next.result) {
          if ("rule_text" in next.result) {
            const result = next.result as GenerationResult;
            setRuleText(result.rule_text);
            setProjection(result.projection_preview);
            setSiteProfile(result.site_profile);
            setRuntimeNotices(result.runtime_notices ?? []);
            setSelectedItemId((current) => keepOrFirstItem(current, result.projection_preview));
          } else if ("projection" in next.result) {
            const projectionResult = next.result.projection;
            setProjection(projectionResult);
            setRuntimeNotices(next.result.runtime_notices ?? []);
            setSelectedItemId((current) => keepOrFirstItem(current, projectionResult));
          }
        }
        if (next.status === "failed") setError(next.error ?? "Job failed");
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : String(pollError));
      }
    }, 700);
    return () => window.clearInterval(timer);
  }, [job]);

  async function generate() {
    setError(null);
    setShareUrl(null);
    await cancelActiveJob();
    setJob(null);
    setProjection(emptyProjection);
    setRuntimeNotices([]);
    setSiteProfile(null);
    setSelectedItemId(null);
    const created = await createGenerationJob(url, mediaType, {
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

  function applyJobPartial(partial: GenerationPartialResult) {
    if (partial.rule_text) setRuleText(partial.rule_text);
    if (partial.site_profile) setSiteProfile(partial.site_profile);
    if (partial.runtime_notices) setRuntimeNotices(partial.runtime_notices);
    if (partial.projection_preview) {
      setProjection(partial.projection_preview);
      setSelectedItemId((current) => keepOrFirstItem(current, partial.projection_preview ?? emptyProjection));
    }
  }

  async function previewEditedRule() {
    setError(null);
    setShareUrl(null);
    await cancelActiveJob();
    setJob(null);
    setProjection(emptyProjection);
    setRuntimeNotices([]);
    setSiteProfile(null);
    setSelectedItemId(null);
    const created = await createProjectionJob(ruleText);
    setJob(created);
  }

  async function cancelActiveJob() {
    const active = jobRef.current;
    if (!active || !["queued", "running"].includes(active.status)) return;
    try {
      await cancelJob(active.id);
    } catch {
      // Best-effort cleanup; the new job should still proceed if cancellation races with completion.
    }
  }

  async function copyRule() {
    await navigator.clipboard.writeText(ruleText);
    setToast(t.copied);
  }

  async function shareCurrent() {
    const share = await createShare({
      rule_text: ruleText,
      projection,
      site_profile: siteProfile,
      runtime_notices: runtimeNotices,
      warnings: projection.warnings
    });
    const absolute = new URL(share.url_path, window.location.origin).toString();
    setShareUrl(absolute);
    await navigator.clipboard.writeText(absolute);
    setToast(t.shared);
  }

  return (
    <main className="shell">
      <nav className="topbar">
        <div className="brand">
          <img className="mark" src="/zwmp-icon.svg" alt="ZWMP icon" />
          <span>
            <strong>ZWMP</strong>
            <small>Web Media Projection</small>
          </span>
        </div>
        <div className="links">
          <button className="linkButton" onClick={() => setLocale(locale === "en" ? "zh" : "en")}><Languages size={16} /> {locale === "en" ? "中文" : "EN"}</button>
          <a href={config.site.links.github} target="_blank" rel="noreferrer"><Github size={16} /> GitHub</a>
          <a href={config.site.links.zwind} target="_blank" rel="noreferrer"><Smartphone size={16} /> Zwind</a>
        </div>
      </nav>

      <section className="intro">
        <h1>{config.site.seo[locale]?.title ?? "ZWMP"}</h1>
        <p>{config.site.guidance[locale] ?? fallbackConfig.site.guidance.en}</p>
        <small>{t.openSource}</small>
      </section>

      <section className="workspace">
        <aside className="controlPane">
          <div className="panelTitle"><Play size={18} /><span>{t.generateRule}</span></div>
          <label className="field">
            <span>{t.sourceUrl}</span>
            <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/videos" />
          </label>
          <div className="field">
            <span>{t.mediaType}</span>
            <div className="segments">
              {(["video", "audio", "image", "all"] as MediaType[]).map((type) => (
                <button className={mediaType === type ? "active" : ""} key={type} onClick={() => setMediaType(type)}>{type}</button>
              ))}
            </div>
          </div>
          <div className="options">
            <OptionToggle label={t.networkSniff} checked={forceNetworkSniff} onChange={setForceNetworkSniff} tooltip={t.networkSniffTip} />
            <OptionToggle label={t.fastMode} checked={fastMode} onChange={setFastMode} tooltip={t.fastModeTip} disabled />
            <label className="numberOption">
              <span>{t.maxItems} <Tooltip text={t.maxItemsTip} /></span>
              <input type="number" min={1} max={200} value={maxItems} onChange={(event) => setMaxItems(Number(event.target.value) || 30)} />
            </label>
            <details className="advancedOptions">
              <summary>{t.advanced}</summary>
              <NumberOption label={t.samples} value={sampleItems} min={1} max={20} onChange={setSampleItems} tooltip="Card samples collected per candidate group." />
              <NumberOption label={t.groups} value={candidateGroups} min={1} max={12} onChange={setCandidateGroups} tooltip="Top visual/repeated candidate groups to analyze." />
              <NumberOption label={t.hypotheses} value={validateHypotheses} min={1} max={8} onChange={setValidateHypotheses} tooltip="Rule hypotheses validated before finalization." />
              <NumberOption label={t.validationLimit} value={validationLimit} min={1} max={100} onChange={setValidationLimit} tooltip="Candidate nodes inspected per selector during dry-run validation." />
              <NumberOption label={t.detailProbes} value={detailProbes} min={0} max={12} onChange={setDetailProbes} tooltip="Detail pages opened during rule generation validation. Resource preview still evaluates all rule items." />
              <NumberOption label={t.scrollSteps} value={scrollSteps} min={0} max={10} onChange={setScrollSteps} tooltip="Auto-scroll passes for lazy-loaded listing pages." />
              <OptionToggle label={t.desktopViewport} checked={desktopMode} onChange={setDesktopMode} tooltip="Use desktop viewport instead of the default mobile viewport." />
            </details>
          </div>
          <button className="primary" onClick={generate} disabled={job?.status === "running"}><RefreshCw size={16} />{t.generate}</button>
          <div className="progress"><div style={progressStyle} /></div>
          <Status job={job} error={error} cacheHit={generationResult?.cache_hit} locale={locale} />
          <RuntimeNotices notices={generationResult?.runtime_notices ?? runtimeNotices} />
          <V3Summary result={generationResult} locale={locale} />
          <DebugTimeline events={[...(job?.debug_events ?? []), ...projection.debug_events]} locale={locale} title={t.debugTimeline} />
        </aside>

        <section className="rulePane">
          <div className="paneHeader">
            <span><FileCode2 size={18} /> {t.rule}</span>
            <div>
              <button className="ghost" onClick={copyRule}><Clipboard size={15} /> {t.copy}</button>
              <button className="ghost" onClick={previewEditedRule}><Play size={15} /> {t.preview}</button>
              <button className="ghost" onClick={shareCurrent} disabled={!projection.items.length}><Share2 size={15} /> {t.share}</button>
            </div>
          </div>
          <p className="ruleHint">{t.manual}</p>
          <textarea spellCheck={false} value={ruleText} onChange={(event) => setRuleText(event.target.value)} />
          <div className="warnings">
            {toast ? <p>{toast}</p> : null}
            {shareUrl ? <p>{shareUrl}</p> : null}
            {projection.warnings.map((warning) => <p key={warning}>{translateDebug(warning, locale)}</p>)}
          </div>
        </section>

        <section className="previewPane">
          <div className="paneHeader">
            <span><FolderTree size={18} /> {t.resources}</span>
            <span className="meta">{projection.items.length} items / {projection.media.length} resources</span>
          </div>
          <div className="previewGrid">
            <Tree nodes={projection.tree} onSelect={setSelectedItemId} selectedItemId={selectedItem?.id ?? null} emptyText={t.parsedResources} />
            <MediaPanel item={selectedItem} media={selectedMedia} t={t} />
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

function Tooltip({ text: value }: { text: string }) {
  return <span className="tooltip" title={value} aria-label={value}><Info size={13} /></span>;
}

function Status({ job, error, cacheHit, locale }: { job: JobResponse | null; error: string | null; cacheHit?: boolean; locale: Locale }) {
  const t = text[locale];
  return (
    <div className="status">
      <strong>{job ? `${job.status} · ${job.phase}` : t.idle}</strong>
      <span>{cacheHit ? t.cacheHit : job ? `${Math.round(job.progress * 100)}%` : t.ready}</span>
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

function V3Summary({ result, locale }: { result: GenerationResult | null; locale: Locale }) {
  if (!result?.v3) return null;
  const validations = result.v3.validations ?? [];
  const groups = result.v3.evidence?.candidate_groups ?? [];
  const t = text[locale];
  return (
    <div className="v3Summary">
      <strong>v3 evidence</strong>
      <p>{result.v3.confidence ? `confidence ${result.v3.confidence}` : "confidence pending"} · {result.v3.used_ai ? t.aiFinalized : t.localFinalized}</p>
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

function DebugTimeline({ events, locale, title }: { events: { phase: string; message: string }[]; locale: Locale; title: string }) {
  return (
    <details className="debug" open>
      <summary>{title}</summary>
      {events.map((event, index) => (
        <div className="event" key={`${event.phase}-${index}`}>
          <span>{event.phase}</span>
          <p>{translateDebug(event.message, locale)}</p>
        </div>
      ))}
    </details>
  );
}

function Tree({ nodes, selectedItemId, onSelect, emptyText }: { nodes: ProjectionNode[]; selectedItemId: string | null; onSelect: (id: string) => void; emptyText: string }) {
  if (!nodes.length) return <div className="empty">{emptyText}</div>;
  return (
    <div className="tree">
      {nodes.map((node) => <TreeNode key={node.id} node={node} selectedItemId={selectedItemId} onSelect={onSelect} depth={0} />)}
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

function MediaPanel({ item, media, t }: { item: ProjectionItem | null; media: ProjectionMedia[]; t: typeof text.en }) {
  if (!item) return <div className="empty">{t.selectItem}</div>;
  return (
    <div className="mediaPanel">
      {item.thumbnail_url ? <img className="thumb" src={item.thumbnail_url} alt="" /> : <div className="thumb placeholder" />}
      <h2>{item.title}</h2>
      <a href={item.detail_url} target="_blank" rel="noreferrer">{item.detail_url} <ExternalLink size={13} /></a>
      {item.warning ? <p className="warning">{item.warning}</p> : null}
      {media.length ? (
        <div className="mediaList">
          {media.map((entry, index) => <MediaPreview key={entry.id} media={entry} label={`${t.directMedia} ${index + 1}`} />)}
        </div>
      ) : <p className="muted">{t.noMedia}</p>}
    </div>
  );
}

function MediaPreview({ media, label }: { media: ProjectionMedia; label: string }) {
  const src = media.url;
  return (
    <div className="mediaEntry">
      <div className="mediaEntryHeader">
        <span>{label}</span>
        <a href={src} target="_blank" rel="noreferrer"><ExternalLink size={13} /> URL</a>
      </div>
      {media.type === "image" ? <img className="assetPreview" src={src} alt="" /> : null}
      {media.type === "audio" ? <audio controls src={src} /> : null}
      {media.type === "video" || media.type === "all" ? <VideoPreview src={src} /> : null}
    </div>
  );
}

function VideoPreview({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playbackError, setPlaybackError] = useState<string | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    let hls: Hls | null = null;
    setPlaybackError(null);
    video.removeAttribute("src");
    video.load();

    if (isHlsUrl(src)) {
      if (Hls.isSupported()) {
        hls = new Hls();
        hls.on(Hls.Events.ERROR, (_event, data) => {
          console.error("hls.js error", data);
          if (data.fatal) {
            setPlaybackError(`HLS playback failed: ${data.type} / ${data.details}`);
          }
        });
        hls.loadSource(src);
        hls.attachMedia(video);
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = src;
      } else {
        setPlaybackError("不支持当前视频格式");
      }
    } else {
      video.src = src;
    }

    return () => {
      if (hls) hls.destroy();
      video.removeAttribute("src");
      video.load();
    };
  }, [src]);

  return (
    <>
      <video ref={videoRef} controls />
      {playbackError ? <p className="mediaError">{playbackError}</p> : null}
    </>
  );
}

function isHlsUrl(src: string): boolean {
  const clean = src.split("#", 1)[0].split("?", 1)[0].toLowerCase();
  return clean.endsWith(".m3u8");
}

function sourceFromRule(rule: string): string | null {
  const line = rule.split(/\r?\n/).find((value) => value.trim().startsWith("source="));
  return line ? line.slice("source=".length).trim() || null : null;
}

function keepOrFirstItem(current: string | null, projection: ProjectionResult): string | null {
  if (current && projection.items.some((item) => item.id === current)) return current;
  return projection.items[0]?.id ?? null;
}

function setMeta(name: string, content: string) {
  let element = document.querySelector(`meta[name="${name}"]`) as HTMLMetaElement | null;
  if (!element) {
    element = document.createElement("meta");
    element.name = name;
    document.head.appendChild(element);
  }
  element.content = content;
}

function translateDebug(message: string, locale: Locale): string {
  if (locale === "zh") return message;
  if (message.includes("无 detail 跳转")) return "No detail hops enabled.";
  if (message.includes("当前 rule 的候选项和跳转链解析正常")) return "The rule resolved candidates and detail hops successfully. If playback fails, inspect network sniffing or detail-page media detection.";
  const candidateMatch = message.match(/候选项匹配 (\d+) 个，可见 (\d+) 个/);
  if (candidateMatch) return `Matched ${candidateMatch[1]} candidates, ${candidateMatch[2]} visible.`;
  return message;
}
