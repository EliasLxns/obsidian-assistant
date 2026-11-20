import { type App, PluginSettingTab, Setting } from "obsidian";
import { STANDARD } from "./einstellungen";
import type AssistentPlugin from "./main";

export class EinstellungenTab extends PluginSettingTab {
  constructor(
    app: App,
    private readonly plugin: AssistentPlugin,
  ) {
    super(app, plugin);
  }

  override display(): void {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("API-Adresse")
      .setDesc("Wo die API des Assistenten läuft, im Heimnetz oder über Tailscale.")
      .addText((t) =>
        t
          .setPlaceholder(STANDARD.apiUrl)
          .setValue(this.plugin.einstellungen.apiUrl)
          .onChange(async (wert) => {
            this.plugin.einstellungen.apiUrl = wert.trim() || STANDARD.apiUrl;
            await this.plugin.speichern();
          }),
      )
      .addButton((b) =>
        b.setButtonText("Verbindung prüfen").onClick(async () => {
          await this.plugin.verbindungPruefen();
        }),
      );

    new Setting(containerEl)
      .setName("Anzahl Quellen")
      .setDesc("Wie viele Abschnitte die Suche liefert (1 bis 20).")
      .addSlider((s) =>
        s
          .setLimits(1, 20, 1)
          .setValue(this.plugin.einstellungen.anzahl)
          .setDynamicTooltip()
          .onChange(async (wert) => {
            this.plugin.einstellungen.anzahl = wert;
            await this.plugin.speichern();
          }),
      );
  }
}
