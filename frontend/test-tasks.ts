import type { Task } from "./client";
export const tasks: { id: string; task: Task; fail?: boolean }[] = [
  {
    id: "guide",
    task: {
      title: "Accogliere nuovi volontari",
      description:
        "Preparare una breve guida per i nuovi volontari della biblioteca.",
      context:
        "Usare le risorse già disponibili. La lunghezza della guida è da concordare.",
    },
  },
  {
    id: "meeting",
    task: {
      title: "Organizzare la riunione di progetto",
      description:
        "Proporre un ordine del giorno e una checklist per una riunione di allineamento.",
      context: "Durata e partecipanti sono da confermare.",
    },
  },
  {
    id: "review",
    fail: true,
    task: {
      title: "Rivedere il processo di onboarding",
      description:
        "Preparare una proposta per rendere più chiaro il primo giorno di lavoro.",
      context:
        "Scenario dimostrativo: errore simulato al primo turno, recuperabile con retry.",
    },
  },
];
