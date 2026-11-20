import { ItemView, Notice, Platform, type WorkspaceLeaf, setIcon } from "obsidian";
import type { Quelle } from "./api";
import type AssistentPlugin from "./main";
import { linkZiel, notizname, sekunden } from "./text";

export const VIEW_TYP = "vault-assistent-seitenleiste";

/**
 * Seitenleiste: Frage stellen oder nur suchen. Jede Quelle ist ein `[[Name]]`-Chip,
 * ein Klick öffnet die Notiz am passenden Abschnitt (Strg/Cmd-Klick in neuem Tab).
 */
export class AssistentView extends ItemView {
  private eingabe!: HTMLTextAreaElement;
  private nurSuchen!: HTMLInputElement;
  private knopf!: HTMLButtonElement;
  private ergebnis!: HTMLElement;
  private laeuft = false;

  constructor(
    leaf: WorkspaceLeaf,
    private readonly plugin: AssistentPlugin,
  ) {
    super(leaf);
  }

  override getViewType(): string {
    return VIEW_TYP;
  }

  override getDisplayText(): string {
    return "Vault-Assistent";
  }

  override getIcon(): string {
    return "message-circle-question";
  }

  override async onOpen(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("vault-assistent");

    const form = root.createEl("form", { cls: "vault-assistent-form" });
    this.eingabe = form.createEl("textarea", {
      cls: "vault-assistent-eingabe",
      attr: { placeholder: "Frage an den Vault …", rows: "3", "aria-label": "Frage" },
    });
    const zeile = form.createDiv({ cls: "vault-assistent-zeile" });
    const label = zeile.createEl("label", { cls: "vault-assistent-schalter" });
    this.nurSuchen = label.createEl("input", { type: "checkbox" });
    label.appendText("Nur suchen");
    this.knopf = zeile.createEl("button", { text: "Fragen", cls: "mod-cta", type: "submit" });
    this.nurSuchen.addEventListener("change", () => {
      this.knopf.setText(this.nurSuchen.checked ? "Suchen" : "Fragen");
    });

    this.eingabe.addEventListener("keydown", (e) => {
      // Nur am Desktop: Mobile Tastaturen haben kein Umschalt+Enter für neue Zeilen.
      if (Platform.isDesktop && e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        form.requestSubmit();
      }
    });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      void this.ausfuehren(this.eingabe.value, this.nurSuchen.checked);
    });

    this.ergebnis = root.createDiv({ cls: "vault-assistent-ergebnis" });
    if (Platform.isDesktop) {
      this.hinweis("Enter stellt die Frage, Umschalt+Enter macht eine neue Zeile.");
    }
  }

  override async onClose(): Promise<void> {
    this.contentEl.empty();
  }

  fokus(): void {
    this.eingabe.focus();
  }

  /** Von außen: „Ähnliche Notizen“ zur aktiven Notiz. */
  async aehnliche(titel: string, anfrage: string, pfad: string): Promise<void> {
    await this.ausfuehren(anfrage, true, { titel, ausser: pfad });
  }

  private async ausfuehren(
    text: string,
    nurSuchen: boolean,
    aehnlich?: { titel: string; ausser: string },
  ): Promise<void> {
    const frage = text.trim();
    if (!frage) return;
    if (this.laeuft) {
      new Notice("Der Assistent ist noch mit der letzten Anfrage beschäftigt.");
      return;
    }
    this.laeuft = true;
    this.knopf.disabled = true;
    this.ergebnis.empty();
    const warten = this.ergebnis.createDiv({
      cls: "vault-assistent-hinweis",
      text: nurSuchen ? "Suche …" : "Der Assistent denkt nach …",
    });
    try {
      if (nurSuchen) {
        const quellen = await this.plugin.suchen(frage, aehnlich?.ausser);
        warten.remove();
        if (aehnlich) {
          this.ergebnis.createEl("h4", { text: `Ähnlich zu „${aehnlich.titel}“` });
        }
        this.quellenListe(quellen, true);
      } else {
        const a = await this.plugin.api().fragen(frage, this.plugin.einstellungen.anzahl);
        warten.remove();
        const antwort = this.ergebnis.createDiv({ cls: "vault-assistent-antwort" });
        antwort.setText(a.antwort);
        this.ergebnis.createDiv({
          cls: "vault-assistent-hinweis",
          text: `Formuliert von ${a.modell} in ${sekunden(a.dauer_s)}`,
        });
        this.ergebnis.createEl("h4", { text: "Quellen" });
        this.quellenListe(a.quellen, false);
      }
    } catch (e) {
      warten.remove();
      this.fehler(e);
    } finally {
      this.laeuft = false;
      this.knopf.disabled = false;
    }
  }

  private quellenListe(quellen: Quelle[], mitAuszug: boolean): void {
    if (!quellen.length) {
      this.hinweis("Nichts gefunden.");
      return;
    }
    const liste = this.ergebnis.createEl("ol", { cls: "vault-assistent-quellen" });
    for (const q of quellen) {
      const li = liste.createEl("li");
      const chip = li.createEl("a", {
        cls: "internal-link vault-assistent-chip",
        text: `[[${notizname(q.pfad)}]]`,
        href: linkZiel(q.pfad, q.ueberschrift),
        attr: { "aria-label": q.pfad, "data-href": linkZiel(q.pfad, q.ueberschrift) },
      });
      chip.addEventListener("click", (e) => {
        e.preventDefault();
        void this.app.workspace.openLinkText(
          linkZiel(q.pfad, q.ueberschrift),
          "",
          e.ctrlKey || e.metaKey,
        );
      });
      const pfadTeile = q.pfad.split("/");
      pfadTeile.pop();
      const ort = [pfadTeile.join("/"), q.ueberschrift.split(" > ").pop()]
        .filter(Boolean)
        .join(" · ");
      if (ort) li.createDiv({ cls: "vault-assistent-ort", text: ort });
      if (mitAuszug && q.auszug) {
        li.createDiv({ cls: "vault-assistent-auszug", text: q.auszug });
      }
    }
  }

  private hinweis(text: string): void {
    this.ergebnis.createDiv({ cls: "vault-assistent-hinweis", text });
  }

  private fehler(e: unknown): void {
    const box = this.ergebnis.createDiv({ cls: "vault-assistent-fehler" });
    setIcon(box.createSpan(), "alert-triangle");
    box.createSpan({ text: e instanceof Error ? e.message : String(e) });
  }
}
