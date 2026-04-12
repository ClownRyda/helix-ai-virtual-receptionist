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
  { id: 1, keyword: "sales",     extension: "1002", description: "Sales team",           active: true,  priority: 10 },
  { id: 2, keyword: "pricing",   extension: "1002", description: "Pricing inquiries",     active: true,  priority: 9  },
  { id: 3, keyword: "billing",   extension: "1002", description: "Billing department",    active: true,  priority: 10 },
  { id: 4, keyword: "support",   extension: "1003", description: "Technical support",     active: true,  priority: 10 },
  { id: 5, keyword: "technical", extension: "1003", description: "Tech support fallback", active: true,  priority: 9  },
  { id: 6, keyword: "operator",  extension: "1001", description: "Operator / reception",  active: true,  priority: 5  },
  { id: 7, keyword: "emergency", extension: "1001", description: "Emergency line",        active: false, priority: 20 },
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
  ollama_model: "llama3.1:8b",
  piper_model: "en_US-lessac-medium",
  business_hours_start: 9,
  business_hours_end: 17,
  business_timezone: "America/Chicago",
  appointment_slot_minutes: 30,
  availability_lookahead_days: 7,
  google_calendar_id: "primary",
};

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

  app.get("/api/appointments", (_req, res) => res.json(mockAppointments));

  app.get("/api/config", (_req, res) => res.json(mockConfig));

  return httpServer;
}
