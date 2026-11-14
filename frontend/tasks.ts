import type { Task } from "./client";
/** Business goals only. Workspace capabilities are selected separately in createRun. */
export const tasks: { id: string; task: Task }[] = [
  {
    id: "expansion",
    task: {
      title: "Aggiungere 20 colonnine entro il 1 marzo 2027",
      description:
        "Vogliamo aggiungere 20 colonnine entro il 1 marzo 2027. Quale piano proponete?",
    },
  },
  {
    id: "maintenance",
    task: {
      title: "Manutenzione delle colonnine a Bolzano",
      description:
        "Quando dovremmo effettuare la manutenzione delle colonnine nell’area di Bolzano?",
    },
  },
];
