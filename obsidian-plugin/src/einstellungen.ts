/** Gespeicherte Einstellungen, ohne Obsidian (testbar). */

export interface Einstellungen {
  apiUrl: string;
  anzahl: number;
}

export const STANDARD: Einstellungen = {
  apiUrl: "http://localhost:8080",
  anzahl: 5,
};

/** Gespeicherte Werte prüfen, Unbrauchbares durch den Standard ersetzen. */
export function einstellungenLaden(roh: unknown): Einstellungen {
  const d = (typeof roh === "object" && roh !== null ? roh : {}) as Partial<Einstellungen>;
  const anzahl = Number(d.anzahl);
  return {
    apiUrl: typeof d.apiUrl === "string" && d.apiUrl.trim() ? d.apiUrl.trim() : STANDARD.apiUrl,
    anzahl: Number.isInteger(anzahl) && anzahl >= 1 && anzahl <= 20 ? anzahl : STANDARD.anzahl,
  };
}
