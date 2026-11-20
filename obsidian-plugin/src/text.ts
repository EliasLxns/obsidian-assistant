/** Reine Hilfsfunktionen ohne Obsidian: Linkziele, Anfragen aus Notizen, Texte. */

const MAX_ZEICHEN = 1500;

/** Ziel für `openLinkText`: Pfad ohne `.md`, bei Abschnitten mit `#Überschrift`. */
export function linkZiel(pfad: string, ueberschrift: string): string {
  const ohne = pfad.replace(/\.md$/i, "");
  // Zeichen, die Obsidian im Linkziel anders liest, ersetzt es selbst durch Leerzeichen.
  const letzte = ueberschrift
    .split(" > ")
    .pop()
    ?.replace(/[#|^]|\[\[|\]\]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return letzte ? `${ohne}#${letzte}` : ohne;
}

/** `03 Wissen/Docker/Compose.md` → `Compose` */
export function notizname(pfad: string): string {
  const datei = pfad.split("/").pop() ?? pfad;
  return datei.replace(/\.md$/i, "");
}

/**
 * Suchtext für „Ähnliche Notizen“: Titel plus Anfang des Inhalts, ohne Frontmatter,
 * Codeblöcke und Markdown-Zeichen, die nur Rauschen wären.
 */
export function anfrageAusNotiz(titel: string, inhalt: string): string {
  const ohneFrontmatter = inhalt.replace(/^---\r?\n(?:[\s\S]*?\r?\n)?---[ \t]*(?:\r?\n|$)/, "");
  const ohneCode = ohneFrontmatter.replace(/(```|~~~)[\s\S]*?\1/g, " ");
  const text = ohneCode
    .replace(/!?\[\[([^\]|]*)(\|[^\]]*)?\]\]/g, "$1")
    .replace(/^[ \t]*(#{1,6}|>|[-*+]|\d+\.)[ \t]+/gm, "") // Überschriften, Zitate, Listen
    .replace(/[*_`~=]+/g, "") // Hervorhebungen; Bindestriche in Wörtern bleiben
    .replace(/\s+/g, " ")
    .trim();
  return `${titel}. ${text}`.slice(0, MAX_ZEICHEN).trim();
}

/** Quellen derselben Notiz zusammenfassen (die API liefert je Abschnitt einen Treffer). */
export function ohneDoppelte<T extends { pfad: string }>(quellen: T[], ausser?: string): T[] {
  const gesehen = new Set<string>(ausser ? [ausser] : []);
  return quellen.filter((q) => {
    if (gesehen.has(q.pfad)) return false;
    gesehen.add(q.pfad);
    return true;
  });
}

export function sekunden(s: number): string {
  return `${s.toFixed(1).replace(".", ",")} s`;
}
