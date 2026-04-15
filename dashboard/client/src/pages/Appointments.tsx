import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Clock } from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import type { Appointment, CalendarSlot } from "@shared/schema";
import { Skeleton } from "@/components/ui/skeleton";

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString([], {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function Appointments() {
  const { data: appointments, isLoading: apptLoading } = useQuery<Appointment[]>({
    queryKey: ["/api/appointments"],
    queryFn: () => fetchJSON("/api/appointments"),
    refetchInterval: 30_000,
  });

  const { data: slots, isLoading: slotsLoading } = useQuery<CalendarSlot[]>({
    queryKey: ["/api/calendar/slots"],
    queryFn: () => fetchJSON("/api/calendar/slots?num_slots=10"),
    refetchInterval: 60_000,
  });

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Appointments</h1>
        <p className="text-sm text-muted-foreground mt-0.5">Callbacks scheduled by the AI receptionist</p>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Scheduled appointments */}
        <div className="lg:col-span-2 bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-3.5 border-b border-border">
            <h2 className="text-sm font-semibold text-foreground">Scheduled Callbacks</h2>
          </div>

          {apptLoading ? (
            <div className="p-4 space-y-3">
              {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}
            </div>
          ) : !appointments?.length ? (
            <div className="py-14 text-center text-muted-foreground text-sm">
              <CalendarClock size={36} className="mx-auto mb-3 opacity-25" />
              No appointments scheduled yet
            </div>
          ) : (
            <div className="divide-y divide-border">
              {appointments.map((appt) => (
                <div key={appt.id} className="px-5 py-4 hover:bg-secondary transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-foreground">{appt.caller_name}</div>
                      <div className="text-xs text-muted-foreground mono mt-0.5">{appt.caller_phone}</div>
                      {appt.reason && (
                        <div className="text-xs text-muted-foreground mt-1 max-w-sm">{appt.reason}</div>
                      )}
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-xs font-medium text-primary">{formatDateTime(appt.scheduled_at)}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{appt.duration_minutes} min</div>
                      {appt.confirmed && (
                        <span className="inline-block mt-1 text-xs badge-answered px-2 py-0.5 rounded">Confirmed</span>
                      )}
                    </div>
                  </div>
                  {appt.google_event_id && (
                    <div className="text-xs text-muted-foreground/50 mono mt-2 truncate">
                      GCal: {appt.google_event_id}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Upcoming availability */}
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-3.5 border-b border-border">
            <h2 className="text-sm font-semibold text-foreground">Open Slots</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Next available from Google Calendar</p>
          </div>

          {slotsLoading ? (
            <div className="p-4 space-y-2">
              {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          ) : !slots?.length ? (
            <div className="py-10 text-center text-muted-foreground text-sm">
              <Clock size={28} className="mx-auto mb-2 opacity-25" />
              No open slots
            </div>
          ) : (
            <div className="divide-y divide-border">
              {slots.map((slot, i) => (
                <div key={i} className="px-5 py-3 hover:bg-secondary transition-colors">
                  <div className="text-xs font-medium text-foreground">{slot.label}</div>
                  <div className="text-xs text-muted-foreground mono mt-0.5">
                    {new Date(slot.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    {" – "}
                    {new Date(slot.end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
