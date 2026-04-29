// Schema types mirroring the Python backend API responses
// No DB on the frontend — all data fetched from agent REST API

export interface CallLog {
  id: number;
  call_id: string;
  direction: "inbound" | "outbound";
  caller_id: string;
  called_number: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  intent: string | null;
  intent_detail: string | null;
  disposition: string | null;
  transferred_to: string | null;
  transcript?: string | null;
  appointment_id?: string | null;
  notes?: string | null;
  summary?: string | null;
}

export type CampaignStatus = "draft" | "active" | "paused" | "completed" | "archived";

export interface Campaign {
  id: number;
  campaign_id: string;
  name: string;
  description: string;
  status: CampaignStatus;
  caller_id: string;
  script: string;
  target_list: string[];
  calls_attempted: number;
  calls_connected: number;
  calls_failed: number;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface OutboundTestCallResult {
  channel_id: string;
  call_log_id: number;
  call_id: string;
  destination: string;
  context: string;
}

export interface CallStats {
  total_calls: number;
  transferred: number;
  scheduled: number;
  hangup: number;
  after_hours: number;
  voicemail: number;
  avg_duration_seconds: number;
}

export interface RoutingRule {
  id: number;
  keyword: string;
  extension: string;
  description: string | null;
  active: boolean;
  priority: number;
  agent_lang: string;
}

export type AgentAvailabilityState = "offline" | "available" | "busy" | "break";
export type AgentLanguage = "en" | "es" | "fr" | "it" | "he" | "ro";

export interface HumanAgent {
  id: number;
  agent_id: string;
  display_name: string;
  extension: string;
  availability_state: AgentAvailabilityState;
  preferred_language: AgentLanguage;
  supported_languages: string[];
  assigned_queues: string[];
  current_call_id: string | null;
  last_offered_at: string | null;
  updated_at?: string | null;
}

export interface Appointment {
  id: number;
  google_event_id: string | null;
  caller_name: string;
  caller_phone: string;
  scheduled_at: string;
  duration_minutes: number;
  reason: string | null;
  confirmed: boolean;
}

export interface CalendarSlot {
  start: string;
  end: string;
  label: string;
}

export interface AgentConfig {
  agent_name: string;
  business_name: string;
  whisper_model: string;
  whisper_beam_size: number;
  ollama_model: string;
  kokoro_voice_en: string;
  kokoro_voice_es: string;
  kokoro_voice_fr: string;
  kokoro_voice_it: string;
  business_hours_start: number;
  business_hours_end: number;
  business_timezone: string;
  appointment_slot_minutes: number;
  availability_lookahead_days: number;
  google_calendar_id: string;
  // v1.2
  after_hours_mode: string;
  operator_extension: string;
  emergency_extension: string;
  max_retries: number;
  silence_timeout_sec: number;
  dtmf_enabled: boolean;
  dtmf_map: string;
  vip_callers: string;
  voicemail_enabled: boolean;
  voicemail_dir: string;
  voicemail_transcribe: boolean;
  call_summary_enabled: boolean;
  faq_enabled: boolean;
  faq_file: string;
  vtiger_enabled: boolean;
  vtiger_base_url: string;
  vtiger_username: string;
  vtiger_access_key: string;
  vtiger_default_module: "Contacts" | "Leads";
}

export interface Holiday {
  id: number;
  date: string;
  name: string;
  active: boolean;
}

export interface HealthStatus {
  status: string;
  version: string;
  checks?: {
    ari: { ok: boolean; detail: string };
    moh: { ok: boolean; detail: string };
    voicemail: { ok: boolean; detail: string };
  };
  features: {
    voicemail: boolean;
    call_summary: boolean;
    faq: boolean;
    dtmf: boolean;
  };
}

export interface HealthHistoryEntry {
  timestamp: string;
  status: "ok" | "degraded" | "error";
  checks: {
    ari: { ok: boolean; detail: string };
    moh: { ok: boolean; detail: string };
    voicemail: { ok: boolean; detail: string };
  };
}
