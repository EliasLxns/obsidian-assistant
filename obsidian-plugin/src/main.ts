import { MarkdownView, Notice, Plugin, type RequestUrlParam, requestUrl } from "obsidian";
import { AssistentApi, type Quelle, type Rohantwort } from "./api";
import { type Einstellungen, einstellungenLaden } from "./einstellungen";
import { EinstellungenTab } from "./settings";
import { anfrageAusNotiz, ohneDoppelte } from "./text";
import { AssistentView, VIEW_TYP } from "./view";

async function senden(a: { url: string; method: string; body?: string }): Promise<Rohantwort> {
  const param: RequestUrlParam = {
    url: a.url,
    method: a.method,
    body: a.body,
    contentType: a.body === undefined ? undefined : "application/json",
    throw: false, // Fehlerstatus selbst auswerten, damit `detail` der API ankommt
  };
  const r = await requestUrl(param);
  return { status: r.status, text: r.text };
}

export default class AssistentPlugin extends Plugin {
  einstellungen!: Einstellungen;

  override async onload(): Promise<void> {
    this.einstellungen = einstellungenLaden(await this.loadData());
    this.registerView(VIEW_TYP, (leaf) => new AssistentView(leaf, this));
    this.addSettingTab(new EinstellungenTab(this.app, this));

    this.addRibbonIcon("message-circle-question", "Vault-Assistent öffnen", () => {
      void this.seitenleiste();
    });
    this.addCommand({
      id: "fragen",
      name: "Assistent fragen",
      callback: () => void this.seitenleiste(),
    });
    this.addCommand({
      id: "aehnliche-notizen",
      name: "Ähnliche Notizen zur aktuellen Notiz",
      checkCallback: (pruefen) => {
        const ansicht = this.app.workspace.getActiveViewOfType(MarkdownView);
        if (!ansicht?.file) return false;
        if (!pruefen) {
          const datei = ansicht.file;
          const anfrage = anfrageAusNotiz(datei.basename, ansicht.editor.getValue());
          void this.seitenleiste(false).then((v) => v?.aehnliche(datei.basename, anfrage, datei.path));
        }
        return true;
      },
    });
  }

  api(): AssistentApi {
    return new AssistentApi(this.einstellungen.apiUrl, senden);
  }

  async speichern(): Promise<void> {
    await this.saveData(this.einstellungen);
  }

  /** Suche; bei „Ähnliche Notizen“ ohne die Notiz selbst. */
  async suchen(frage: string, ausser?: string): Promise<Quelle[]> {
    const k = this.einstellungen.anzahl;
    // `/search` liefert schon je Notiz den besten Abschnitt; einer mehr ersetzt die Notiz selbst.
    const quellen = await this.api().suchen(frage, Math.min(ausser ? k + 1 : k, 20));
    return ohneDoppelte(quellen, ausser).slice(0, k);
  }

  async verbindungPruefen(): Promise<void> {
    try {
      const s = await this.api().status();
      const ollama = s.ollama_erreichbar ? "Gaming-PC wach" : "Gaming-PC schläft";
      new Notice(`Verbunden mit API ${s.version}: ${s.chunks} Abschnitte im Index, ${ollama}.`);
    } catch (e) {
      new Notice(e instanceof Error ? e.message : String(e), 8000);
    }
  }

  private async seitenleiste(fokus = true): Promise<AssistentView | undefined> {
    const { workspace } = this.app;
    let leaf = workspace.getLeavesOfType(VIEW_TYP)[0];
    if (!leaf) {
      leaf = workspace.getRightLeaf(false) ?? undefined;
      await leaf?.setViewState({ type: VIEW_TYP, active: true });
    }
    if (!leaf) return undefined;
    await workspace.revealLeaf(leaf);
    const view = leaf.view instanceof AssistentView ? leaf.view : undefined;
    if (fokus) view?.fokus();
    return view;
  }
}
