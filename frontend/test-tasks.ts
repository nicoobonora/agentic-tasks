import type { Task } from "./client";
export const tasks: { id: string; task: Task; fail?: boolean }[] = [
  {
    id: "guide",
    task: {
      title: "Welcome new volunteers",
      description: "Prepare a short guide for the library's new volunteers.",
      context:
        "Use the resources already available. The length of the guide is still to be agreed.",
    },
  },
  {
    id: "meeting",
    task: {
      title: "Organize the project meeting",
      description:
        "Propose an agenda and a checklist for an alignment meeting.",
      context: "Duration and participants are still to be confirmed.",
    },
  },
  {
    id: "review",
    fail: true,
    task: {
      title: "Review the onboarding process",
      description: "Prepare a proposal to make the first day of work clearer.",
      context:
        "Demo scenario: simulated error on the first turn, recoverable with retry.",
    },
  },
];
