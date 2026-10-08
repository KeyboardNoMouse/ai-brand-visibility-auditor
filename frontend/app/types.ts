export interface BotRule {
  category: "training" | "search" | "user" | "unknown";
  allowed: boolean;
  disallowed_on_root: boolean;
  disallowed_on_path: boolean;
  has_explicit_rule: boolean;
}

export interface AccessResult {
  robots_txt_found: boolean;
  robots_txt_raw: string | null;
  llms_txt_found: boolean;
  llms_txt_raw: string | null;
  bot_rules: Record<string, BotRule>;
}

export interface TechnicalResult {
  meta_description: string | null;
  has_schema_data: boolean;
  schema_types: string[];
  h1_count: number;
  heading_structure: Record<string, number>;
  word_count: number;
  has_statistics: boolean;
  has_quotations: boolean;
  has_outbound_citations: boolean;
  technical_score: number;
}

export interface PromptRunDetail {
  run_number: number;
  brand_mentioned: boolean;
  raw_response: string;
}

export interface PromptAggregate {
  prompt_text: string;
  prompt_type: "branded" | "unbranded" | "knowledge";
  runs: number;
  mentions: number;
  mention_rate: number;
  runs_detail: PromptRunDetail[];
}

export interface MentionResult {
  per_prompt: PromptAggregate[];
  overall_mention_rate: number;
  branded_mention_rate: number;
  unbranded_mention_rate: number;
  category?: string | null;
  brand_known?: "known" | "hallucinated" | "unknown";
  knowledge_consistency?: number;
  explicit_unknown_rate?: number;
}

export interface RetrievalCompetitor {
  domain: string;
  rank: number;
  title?: string;
}

export interface RetrievalPerQuery {
  query: string;
  rank: number | null;
  retrieved: boolean;
  competitors: RetrievalCompetitor[];
  result_count: number;
}

export interface RetrievalResult {
  available: boolean;
  reason: string | null;
  query_text: string | null;
  brand_url_retrieved: boolean | null;
  retrieved_rank: number | null;
  best_rank?: number | null;
  retrieval_rate?: number | null;
  queries_run?: number;
  competitors?: RetrievalCompetitor[];
  per_query?: RetrievalPerQuery[];
  raw_response?: Record<string, unknown>;
}

export interface Recommendation {
  id: string;
  category: "access" | "technical" | "mention" | "retrieval";
  severity: "high" | "medium" | "low";
  description: string;
}

export interface SubScores {
  access: number;
  technical: number;
  mention: number;
  retrieval: number | null;
}

export interface AuditMeta {
  id: string;
  brand_name: string;
  url: string;
  status: string;
  composite_score: number | null;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface AuditResult {
  audit: AuditMeta;
  sub_scores: SubScores;
  access: AccessResult | null;
  technical: TechnicalResult | null;
  mention: MentionResult | null;
  retrieval: RetrievalResult | null;
  recommendations: Recommendation[];
}
