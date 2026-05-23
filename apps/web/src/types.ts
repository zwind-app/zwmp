export type MediaType = "video" | "audio" | "image" | "all";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface DebugEvent {
  level: "debug" | "info" | "warning" | "error";
  phase: string;
  message: string;
  data: Record<string, unknown>;
}

export interface ProjectionNode {
  id: string;
  name: string;
  kind: "directory" | "file";
  item_id?: string | null;
  media_id?: string | null;
  children: ProjectionNode[];
}

export interface ProjectionItem {
  id: string;
  title: string;
  detail_url: string;
  thumbnail_url?: string | null;
  duration?: string | null;
  status: "pending" | "resolved" | "needs-interaction" | "failed";
  media_ids: string[];
  warning?: string | null;
}

export interface ProjectionMedia {
  id: string;
  item_id: string;
  url: string;
  type: MediaType;
  extension?: string | null;
  delivery: "direct" | "proxy" | "auto";
  requires_proxy: boolean;
  headers_hint: Record<string, string>;
}

export interface ProjectionResult {
  tree: ProjectionNode[];
  items: ProjectionItem[];
  media: ProjectionMedia[];
  debug_events: DebugEvent[];
  warnings: string[];
}

export interface RuntimeNotice {
  kind: "ai_fallback" | "ai_quota" | "sniffing_limited";
  message: string;
  action: string;
}

export interface GenerationResult {
  rule_id: string;
  rule_text: string;
  site_profile: {
    category: string;
    language: string;
    layout_type: string;
    content_type: string;
    confidence: number;
    notes?: string | null;
  };
  projection_preview: ProjectionResult;
  cache_hit: boolean;
  warnings: string[];
  runtime_notices: RuntimeNotice[];
  v3: {
    used_ai?: boolean;
    confidence?: string;
    reasoning?: string;
    detail_url_examples?: string[];
    evidence?: {
      title?: string | null;
      lazy_load_observed?: boolean;
      candidate_groups?: Array<{ group_id: string; selector: string; visible_count: number; score: number }>;
    };
    validations?: Array<{
      hypothesis_id: string;
      quality_score: number;
      warnings: string[];
      suggested_repairs: Record<string, unknown>;
      listing: { candidate_count: number; visible_candidate_count: number; link_coverage: number; title_coverage: number; thumbnail_coverage: number };
    }>;
  };
}

export interface GenerationPartialResult {
  rule_text?: string;
  site_profile?: GenerationResult["site_profile"] | null;
  projection_preview?: ProjectionResult;
  cache_hit?: boolean;
  warnings?: string[];
  runtime_notices?: RuntimeNotice[];
  v3?: GenerationResult["v3"];
}

export interface JobResponse {
  id: string;
  type: "generation" | "projection";
  status: JobStatus;
  phase: string;
  progress: number;
  error?: string | null;
  debug_events: DebugEvent[];
  partial_result?: GenerationPartialResult | null;
  result?: GenerationResult | { projection: ProjectionResult; runtime_notices: RuntimeNotice[]; debug?: Record<string, unknown> } | null;
}

export interface PublicConfig {
  site: {
    default_locale: string;
    supported_locales: string[];
    links: { github: string; zwind: string };
    seo: Record<string, { title: string; description: string; keywords: string[] }>;
    guidance: Record<string, string>;
  };
}

export interface ShareCreateRequest {
  rule_text: string;
  projection: ProjectionResult;
  site_profile?: GenerationResult["site_profile"] | null;
  runtime_notices: RuntimeNotice[];
  warnings: string[];
}

export interface ShareResponse extends ShareCreateRequest {
  id: string;
  url_path: string;
  created_at: string;
}
