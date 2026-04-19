import { Switch, Route, Router } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/queryClient";
import { Toaster } from "@/components/ui/toaster";
import Sidebar from "@/components/Sidebar";
import Dashboard from "@/pages/Dashboard";
import CallLogs from "@/pages/CallLogs";
import CallDetail from "@/pages/CallDetail";
import Routing from "@/pages/Routing";
import Appointments from "@/pages/Appointments";
import Settings from "@/pages/Settings";
import Voicemails from "@/pages/Voicemails";
import Agents from "@/pages/Agents";
import Campaigns from "@/pages/Campaigns";
import OutboundCalls from "@/pages/OutboundCalls";

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* Router must wrap Sidebar so nav links get hash-location context */}
      <Router hook={useHashLocation}>
        <div className="flex min-h-screen bg-background">
          <Sidebar />
          <main className="flex-1 min-w-0 overflow-auto">
            <Switch>
              <Route path="/" component={Dashboard} />
              <Route path="/calls" component={CallLogs} />
              <Route path="/calls/:callId" component={CallDetail} />
              <Route path="/routing" component={Routing} />
              <Route path="/agents" component={Agents} />
              <Route path="/campaigns" component={Campaigns} />
              <Route path="/outbound-calls" component={OutboundCalls} />
              <Route path="/appointments" component={Appointments} />
              <Route path="/voicemails" component={Voicemails} />
              <Route path="/settings" component={Settings} />
            </Switch>
          </main>
        </div>
      </Router>
      <Toaster />
    </QueryClientProvider>
  );
}
