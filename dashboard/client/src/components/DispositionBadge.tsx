export default function DispositionBadge({ disposition }: { disposition: string | null }) {
  const d = disposition || "unknown";
  const classes: Record<string, string> = {
    scheduled: "badge-scheduled",
    transferred: "badge-transferred",
    hangup: "badge-hangup",
    answered: "badge-answered",
    unknown: "badge-hangup",
  };
  const labels: Record<string, string> = {
    scheduled: "Scheduled",
    transferred: "Transferred",
    hangup: "Hung Up",
    answered: "Answered",
    unknown: "Unknown",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${classes[d] || "badge-hangup"}`}>
      {labels[d] || d}
    </span>
  );
}
