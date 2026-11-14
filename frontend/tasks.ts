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
];
