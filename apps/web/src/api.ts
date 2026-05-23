import type { JobResponse, MediaType, PublicConfig, ShareCreateRequest, ShareResponse } from "./types";

export interface GenerationOptions {
  force_network_sniff: boolean;
  fast_mode: boolean;
  max_items: number | null;
  sample_items: number;
  max_candidate_groups: number;
  validate_hypotheses: number;
  validation_limit: number;
  detail_probes: number;
  scroll_steps: number;
  desktop: boolean;
}

export async function createGenerationJob(url: string, mediaType: MediaType, options: GenerationOptions): Promise<JobResponse> {
  const response = await fetch("/api/generation-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, media_type: mediaType, options })
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function getGenerationJob(id: string): Promise<JobResponse> {
  const response = await fetch(`/api/generation-jobs/${id}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function createProjectionJob(ruleText: string): Promise<JobResponse> {
  const response = await fetch("/api/projection-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rule_text: ruleText })
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function getProjectionJob(id: string): Promise<JobResponse> {
  const response = await fetch(`/api/projection-jobs/${id}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function cancelJob(id: string): Promise<JobResponse> {
  const response = await fetch(`/api/jobs/${id}/cancel`, { method: "POST" });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function getPublicConfig(): Promise<PublicConfig> {
  const response = await fetch("/api/config");
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function createShare(request: ShareCreateRequest): Promise<ShareResponse> {
  const response = await fetch("/api/shares", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function getShare(id: string): Promise<ShareResponse> {
  const response = await fetch(`/api/shares/${id}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
