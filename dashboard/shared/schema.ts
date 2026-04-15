// Schema types mirroring the Python backend API responses
// No DB on the frontend — all data fetched from agent REST API

export interface CallLog {
  id: number;
  call_id: string;
  caller_id: string;
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
  ollama_model: string;
  piper_model: string;
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
  voicemail_transcribe: boolean;
  call_summary_enabled: boolean;
  faq_enabled: boolean;
  faq_file: string;
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
  features: {
    voicemail: boolean;
    call_summary: boolean;
    faq: boolean;
    dtmf: boolean;
  };
}
