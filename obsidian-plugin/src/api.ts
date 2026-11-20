/**
 * Client für die REST-API des Obsidian-Assistenten.
 *
 * Die eigentliche HTTP-Anfrage wird hineingereicht: im Plugin Obsidians `requestUrl`
 * (umgeht CORS, geht auch mobil), in den Tests eine Attrappe. So bleibt diese Datei
 * ohne Obsidian testbar.
 */

export interface Quelle {
  nr: number;
  pfad: string;
  titel: string;
  ueberschrift: string;
  score: number;
  link: string;
  auszug: string;
}

export interface Antwort {
  antwort: string;
  quellen: Quelle[];
  modell: string;
  dauer_s: number;
}

export interface Status {
  version: string;
  chunks: number;
  vault: string;
  ollama_erreichbar: boolean;
  chat_modell: string;
  embed_modell: string;
}

export interface Anfrage {
  url: string;
  method: "GET" | "POST";
  body?: string;
}

export interface Rohantwort {
  status: number;
  text: string;
}

export type Senden = (a: Anfrage) => Promise<Rohantwort>;

/** Fehler der API. `status` 0: nicht erreichbar. */
export class ApiFehler extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiFehler";
  }
}

/** `detail` aus einer FastAPI-Fehlerantwort, bei 422 die Meldungen der Prüfung. */
export function fehlermeldung(status: number, text: string): string {
  try {
    const daten = JSON.parse(text) as { detail?: unknown };
    const detail = daten.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const teile = detail.map((d) =>
        typeof d === "object" && d !== null && "msg" in d ? String(d.msg) : String(d),
      );
      if (teile.length) return teile.join("; ");
    }
  } catch {
    // kein JSON, unten den Text nehmen
  }
  return text.trim() || `HTTP ${status}`;
}

export class AssistentApi {
  private readonly basis: string;

  constructor(
    basisUrl: string,
    private readonly senden: Senden,
  ) {
    this.basis = basisUrl.trim().replace(/\/+$/, "");
  }

  private async anfrage<T>(method: "GET" | "POST", pfad: string, body?: unknown): Promise<T> {
    if (!this.basis) {
      throw new ApiFehler(0, "Keine API-Adresse eingestellt (Einstellungen → Vault-Assistent).");
    }
    let r: Rohantwort;
    try {
      r = await this.senden({
        url: this.basis + pfad,
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      const grund = e instanceof Error ? e.message : String(e);
      throw new ApiFehler(0, `API unter ${this.basis} nicht erreichbar (${grund}).`);
    }
    if (r.status >= 400) throw new ApiFehler(r.status, fehlermeldung(r.status, r.text));
    try {
      return JSON.parse(r.text) as T;
    } catch {
      throw new ApiFehler(r.status, `${this.basis} antwortet nicht wie die API.`);
    }
  }

  fragen(frage: string, k = 5): Promise<Antwort> {
    return this.anfrage<Antwort>("POST", "/ask", { frage, k });
  }

  async suchen(frage: string, k = 8): Promise<Quelle[]> {
    const daten = await this.anfrage<{ quellen: Quelle[] }>("POST", "/search", { frage, k });
    return daten.quellen;
  }

  status(): Promise<Status> {
    return this.anfrage<Status>("GET", "/status");
  }
}
