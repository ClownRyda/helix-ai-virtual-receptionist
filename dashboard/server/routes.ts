import type { Express } from "express";
import { createServer, type Server } from "http";
import { storage } from "./storage";

// ── Mock data (used when the Python agent is not running) ────
const mockCalls = [
  { id: 1, call_id: "c001", caller_id: "+12145550101", started_at: new Date(Date.now() - 1000*60*12).toISOString(), ended_at: new Date(Date.now() - 1000*60*9).toISOString(), duration_seconds: 187, intent: "schedule", intent_detail: "Schedule a callback", disposition: "scheduled", transferred_to: null, transcript: "Caller asked to schedule a consultation for next Tuesday afternoon.", appointment_id: "apt_001", notes: null },
  { id: 2, call_id: "c002", caller_id: "+14695550198", started_at: new Date(Date.now() - 1000*60*34).toISOString(), ended_at: new Date(Date.now() - 1000*60*31).toISOString(), duration_seconds: 95, intent: "transfer", intent_detail: "Transfer to sales", disposition: "transferred", transferred_to: "1002", transcript: "Caller asked about pricing and was transferred to the sales team.", appointment_id: null, notes: null },
  { id: 3, call_id: "c003", caller_id: "+19725550144", started_at: new Date(Date.now() - 1000*60*61).toISOString(), ended_at: new Date(Date.now() - 1000*60*58).toISOString(), duration_seconds: 212, intent: "schedule", intent_detail: "Book appointment", disposition: "scheduled", transferred_to: null, transcript: "Caller wanted to book a service appointment for their vehicle.", appointment_id: "apt_002", notes: null },
  { id: 4, call_id: "c004", caller_id: "+12145550177", started_at: new Date(Date.now() - 1000*60*95).toISOString(), ended_at: new Date(Date.now() - 1000*60*94).toISOString(), duration_seconds: 38, intent: "info", intent_detail: "Business hours inquiry", disposition: "hangup", transferred_to: null, transcript: "Caller asked about business hours. AI answered and caller hung up.", appointment_id: null, notes: null },
  { id: 5, call_id: "c005", caller_id: "+18175550122", started_at: new Date(Date.now() - 1000*60*130).toISOString(), ended_at: new Date(Date.now() - 1000*60*127).toISOString(), duration_seconds: 154, intent: "transfer", intent_detail: "Transfer to support", disposition: "transferred", transferred_to: "1003", transcript: "Caller reported a technical issue and was routed to support.", appointment_id: null, notes: null },
  { id: 6, call_id: "c006", caller_id: "+14695550133", started_at: new Date(Date.now() - 1000*60*180).toISOString(), ended_at: new Date(Date.now() - 1000*60*177).toISOString(), duration_seconds: 201, intent: "schedule", intent_detail: "Schedule callback", disposition: "scheduled", transferred_to: null, transcript: "Caller requested a callback for a quote on commercial cleaning services.", appointment_id: "apt_003", notes: null },
  { id: 7, call_id: "c007", caller_id: "+12145550199", started_at: new Date(Date.now() - 1000*60*240).toISOString(), ended_at: new Date(Date.now() - 1000*60*239).toISOString(), duration_seconds: 22, intent: "unknown", intent_detail: null, disposition: "hangup", transferred_to: null, transcript: "Caller hung up before intent could be determined.", appointment_id: null, notes: null },
  { id: 8, call_id: "c008", caller_id: "+19725550166", started_at: new Date(Date.now() - 1000*60*300).toISOString(), ended_at: new Date(Date.now() - 1000*60*296).toISOString(), duration_seconds: 278, intent: "transfer", intent_detail: "Transfer to billing", disposition: "transferred", transferred_to: "1002", transcript: "Caller had a billing question and was connected to the billing department.", appointment_id: null, notes: null },
];

const mockRouting = [
  { id: 1, keyword: "sales",     extension: "1002", description: "Sales team",           active: true,  priority: 10, agent_lang: "en" },
  { id: 2, keyword: "pricing",   extension: "1002", description: "Pricing inquiries",     active: true,  priority: 9,  agent_lang: "en" },
  { id: 3, keyword: "billing",   extension: "1002", description: "Billing department",    active: true,  priority: 10, agent_lang: "en" },
  { id: 4, keyword: "support",   extension: "1003", description: "Technical support",     active: true,  priority: 10, agent_lang: "en" },
  { id: 5, keyword: "technical", extension: "1003", description: "Tech support fallback", active: true,  priority: 9,  agent_lang: "en" },
  { id: 6, keyword: "operator",  extension: "1001", description: "Operator / reception",  active: true,  priority: 5,  agent_lang: "en" },
  { id: 7, keyword: "emergency", extension: "1001", description: "Emergency line",        active: false, priority: 20, agent_lang: "en" },
];

const mockAppointments = [
  { id: 1, google_event_id: "gcal_001", caller_name: "James Harmon",   caller_phone: "+12145550101", scheduled_at: new Date(Date.now() + 1000*60*60*26).toISOString(), duration_minutes: 30, reason: "Consultation",         confirmed: true  },
  { id: 2, google_event_id: "gcal_002", caller_name: "Maria Castillo", caller_phone: "+19725550144", scheduled_at: new Date(Date.now() + 1000*60*60*50).toISOString(), duration_minutes: 30, reason: "Service appointment",  confirmed: true  },
  { id: 3, google_event_id: null,       caller_name: "Derek Simms",    caller_phone: "+14695550133", scheduled_at: new Date(Date.now() + 1000*60*60*74).toISOString(), duration_minutes: 30, reason: "Commercial quote",     confirmed: false },
];

const mockConfig = {
  agent_name: "Alex",
  business_name: "Helix AI",
  whisper_model: "base.en",
  whisper_beam_size: 1,
  ollama_model: "llama3.1:8b",
  kokoro_voice_en: "af_heart",
  kokoro_voice_es: "ef_dora",
  kokoro_voice_fr: "ff_siwis",
  kokoro_voice_it: "if_sara",
  business_hours_start: 9,
  business_hours_end: 17,
  business_timezone: "America/Chicago",
  appointment_slot_minutes: 30,
  availability_lookahead_days: 7,
  google_calendar_id: "primary",
  // v1.2 fields
  after_hours_mode: "callback",
  operator_extension: "1001",
  emergency_extension: "1001",
  max_retries: 3,
  silence_timeout_sec: 8,
  dtmf_enabled: false,
  dtmf_map: '{"1":"1002","2":"1003","0":"1001"}',
  vip_callers: "",
  voicemail_enabled: false,
  voicemail_dir: "/var/spool/helix/voicemail",
  voicemail_transcribe: true,
  call_summary_enabled: false,
  faq_enabled: false,
  faq_file: "faq.txt",
  vtiger_enabled: false,
  vtiger_base_url: "http://127.0.0.1:8188",
  vtiger_username: "admin",
  vtiger_access_key: "",
  vtiger_default_module: "Contacts",
};

const mockHolidays = [
  { id: 1, date: "2026-07-04", name: "Independence Day",    active: true,  created_at: new Date().toISOString() },
  { id: 2, date: "2026-11-26", name: "Thanksgiving Day",    active: true,  created_at: new Date().toISOString() },
  { id: 3, date: "2026-12-25", name: "Christmas Day",       active: true,  created_at: new Date().toISOString() },
  { id: 4, date: "2027-01-01", name: "New Year's Day",      active: true,  created_at: new Date().toISOString() },
];

const mockVoicemails: any[] = [];
const mockAgents = [
  {
    id: 1,
    agent_id: "1001",
    display_name: "Operator One",
    extension: "1001",
    availability_state: "available",
    preferred_language: "en",
    supported_languages: ["en", "es"],
    assigned_queues: ["operator", "general"],
    current_call_id: null,
    last_offered_at: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 2,
    agent_id: "1002",
    display_name: "Sales Sofia",
    extension: "1002",
    availability_state: "break",
    preferred_language: "es",
    supported_languages: ["es", "en"],
    assigned_queues: ["sales", "billing"],
    current_call_id: null,
    last_offered_at: new Date(Date.now() - 1000 * 60 * 63).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {

  app.get("/api/health", (_req, res) => res.json({ status: "ok", mode: "demo" }));

  app.get("/api/stats", (_req, res) => {
    const transferred = mockCalls.filter(c => c.disposition === "transferred").length;
    const scheduled   = mockCalls.filter(c => c.disposition === "scheduled").length;
    const hangup      = mockCalls.filter(c => c.disposition === "hangup").length;
    const avg = Math.round(mockCalls.reduce((s, c) => s + (c.duration_seconds ?? 0), 0) / mockCalls.length);
    res.json({ total_calls: mockCalls.length, transferred, scheduled, hangup, avg_duration_seconds: avg });
  });

  app.get("/api/calls", (req, res) => {
    const limit = parseInt((req.query.limit as string) ?? "50");
    res.json(mockCalls.slice(0, limit));
  });

  app.get("/api/calls/:id", (req, res) => {
    const call = mockCalls.find(c => c.id === parseInt(req.params.id));
    if (!call) return res.status(404).json({ error: "Not found" });
    res.json(call);
  });

  app.get("/api/routing", (_req, res) => res.json(mockRouting));

  app.post("/api/routing", (req, res) => {
    const rule = { id: mockRouting.length + 1, ...req.body };
    mockRouting.push(rule);
    res.status(201).json(rule);
  });

  app.put("/api/routing/:id", (req, res) => {
    const idx = mockRouting.findIndex(r => r.id === parseInt(req.params.id));
    if (idx === -1) return res.status(404).json({ error: "Not found" });
    mockRouting[idx] = { ...mockRouting[idx], ...req.body };
    res.json(mockRouting[idx]);
  });

  app.delete("/api/routing/:id", (req, res) => {
    const idx = mockRouting.findIndex(r => r.id === parseInt(req.params.id));
    if (idx !== -1) mockRouting.splice(idx, 1);
    res.json({ ok: true });
  });

  app.get("/api/agents", (_req, res) => res.json(mockAgents));
  app.post("/api/agents/register", (req, res) => {
    const agent = {
      id: mockAgents.length + 1,
      current_call_id: null,
      last_offered_at: null,
      updated_at: new Date().toISOString(),
      ...req.body,
    };
    mockAgents.push(agent);
    res.status(201).json(agent);
  });
  app.patch("/api/agents/:agentId", (req, res) => {
    const agent = mockAgents.find((row) => row.agent_id === req.params.agentId);
    if (!agent) return res.status(404).json({ error: "Not found" });
    Object.assign(agent, req.body, { updated_at: new Date().toISOString() });
    res.json(agent);
  });

  app.get("/api/appointments", (_req, res) => res.json(mockAppointments));

  app.get("/api/config", (_req, res) => res.json(mockConfig));
  app.patch("/api/config", (req, res) => {
    Object.assign(mockConfig, req.body);
    res.json({ updated: Object.keys(req.body), note: "Demo mode — restart agent to apply on server." });
  });

  app.get("/api/holidays", (_req, res) => res.json(mockHolidays));
  app.post("/api/holidays", (req, res) => {
    const holiday = { id: mockHolidays.length + 1, created_at: new Date().toISOString(), active: true, ...req.body };
    mockHolidays.push(holiday);
    res.status(201).json(holiday);
  });
  app.delete("/api/holidays/:id", (req, res) => {
    const idx = mockHolidays.findIndex(h => h.id === parseInt(req.params.id));
    if (idx !== -1) mockHolidays.splice(idx, 1);
    res.json({ ok: true });
  });

  app.get("/api/voicemails", (_req, res) => res.json(mockVoicemails));
  app.get("/api/voicemails/:id", (req, res) => {
    const vm = mockVoicemails.find(v => v.id === parseInt(req.params.id));
    if (!vm) return res.status(404).json({ error: "Not found" });
    res.json(vm);
  });
  app.patch("/api/voicemails/:id", (req, res) => {
    const vm = mockVoicemails.find(v => v.id === parseInt(req.params.id));
    if (!vm) return res.status(404).json({ error: "Not found" });
    Object.assign(vm, req.body);
    res.json(vm);
  });

  return httpServer;
}
