import { describe, expect, it } from "vitest";
import { einstellungenLaden, STANDARD } from "../src/einstellungen";
import { anfrageAusNotiz, linkZiel, notizname, ohneDoppelte, sekunden } from "../src/text";

describe("linkZiel", () => {
  it("springt zum letzten Teil der Überschrift", () => {
    expect(linkZiel("03 Wissen/Docker/Compose.md", "Compose > Starten")).toBe(
      "03 Wissen/Docker/Compose#Starten",
    );
  });

  it("ersetzt Zeichen, die Obsidian im Linkziel anders liest", () => {
    expect(linkZiel("Code.md", "Code > C# Tipps | kurz")).toBe("Code#C Tipps kurz");
  });

  it("öffnet ohne Überschrift die Notiz", () => {
    expect(linkZiel("Notiz.md", "")).toBe("Notiz");
  });
});

it("notizname", () => {
  expect(notizname("03 Wissen/Docker/Compose.md")).toBe("Compose");
  expect(notizname("Version 1.2.md")).toBe("Version 1.2");
});

describe("anfrageAusNotiz", () => {
  it("lässt Frontmatter, Code und Markdown weg", () => {
    const inhalt = "---\ntags: [x]\n---\n# Kopf\n\nText mit [[Ziel|Alias]] und **fett**.\n- Wake-on-LAN\n```\ncode\n```\n";
    expect(anfrageAusNotiz("Titel", inhalt)).toBe("Titel. Kopf Text mit Ziel und fett. Wake-on-LAN");
  });

  it("versteht leeres Frontmatter, CRLF und ~~~-Blöcke", () => {
    expect(anfrageAusNotiz("T", "---\r\n---\r\nText\r\n~~~\ncode\n~~~\nEnde")).toBe("T. Text Ende");
  });

  it("kürzt lange Notizen", () => {
    expect(anfrageAusNotiz("T", "wort ".repeat(1000)).length).toBeLessThanOrEqual(1500);
  });
});

it("ohneDoppelte behält den ersten Treffer je Notiz und lässt eine aus", () => {
  const q = [{ pfad: "a" }, { pfad: "b" }, { pfad: "a" }, { pfad: "c" }];
  expect(ohneDoppelte(q, "b")).toEqual([{ pfad: "a" }, { pfad: "c" }]);
});

it("sekunden mit Komma", () => {
  expect(sekunden(2.345)).toBe("2,3 s");
});

describe("einstellungenLaden", () => {
  it("nimmt den Standard für fehlende oder kaputte Werte", () => {
    expect(einstellungenLaden(null)).toEqual(STANDARD);
    expect(einstellungenLaden({ apiUrl: " ", anzahl: 99 })).toEqual(STANDARD);
  });

  it("übernimmt gültige Werte", () => {
    expect(einstellungenLaden({ apiUrl: " http://assistent:8080 ", anzahl: 8 })).toEqual({
      apiUrl: "http://assistent:8080",
      anzahl: 8,
    });
  });
});
