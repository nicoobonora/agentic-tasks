import type { Task } from "./client";
/** Business goals only. Workspace capabilities are selected separately in createRun. */
export const tasks: { id: string; task: Task }[] = [
  {
    id: "expansion",
    task: {
      title: "Add 20 charging stations by 1 March 2027",
      description:
        "We want to add 20 charging stations by 1 March 2027. What plan do you propose?",
    },
  },
  {
    id: "maintenance",
    task: {
      title: "Charging station maintenance in Bolzano",
      description:
        "When should we carry out maintenance on the charging stations in the Bolzano area?",
    },
  },
  {
    id: "maintenance-window",
    task: {
      title: "Pick a 2-hour maintenance window at BZ_PIAVE_01",
      description:
        "Recommend the recurring 2-hour weekly slot with the lowest observed occupancy at BZ_PIAVE_01 for routine maintenance, using its historical plug status.",
      context:
        "Scope is fixed. Site: BZ_PIAVE_01, tool site_id Neogy-AMPECO:78218 (the only feed with recent data; do not use other IDs). Call charging.compare_maintenance_windows with start 2026-08-01T00:00:00Z, end 2026-11-14T00:00:00Z, duration_hours 2, permitted_hours 6 to 22, minimum_coverage 0.9. Unit is plugs; no budget involved (finance: not applicable). Maintenance is routine, not a fault repair, and no date is scheduled. Claim rules: a supported claim must not contain any digit (no dates, times, hours or percentages) unless it carries a metric_reference copied verbatim from metric_reference_examples; write the recommended weekday and start hour in the draft actions, not in supported claims. The ranking returned by the tool is the decision rule; the top-ranked slot is an acceptable final answer and the operator does not need to confirm it. No action is executed.",
    },
  },
];
