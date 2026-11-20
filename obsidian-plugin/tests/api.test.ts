import { describe, expect, it } from "vitest";
import { type Anfrage, ApiFehler, AssistentApi, fehlermeldung, type Rohantwort } from "../src/api";

function attrappe(antwort: Rohantwort | Error) {
  const anfragen: Anfrage[] = [];
  const api = new AssistentApi("http://api:8080/", async (a) => {
    anfragen.push(a);
    if (antwort instanceof Error) throw antwort;
    return antwort;
  });
  return { api, anfragen };
}

const quelle = {
  nr: 1,
  pfad: "03 Wissen/Docker/Ollama.md",
  titel: "Ollama",
  ueberschrift: "Ollama > Port",
  score: 0.9,
  link: "obsidian://open?vault=demo_vault&file=03%20Wissen%2FDocker%2FOllama",
  auszug: "Ollama lauscht auf 11434.",
};

describe("AssistentApi", () => {
  it("stellt Fragen per POST /ask", async () => {
    const { api, anfragen } = attrappe({
      status: 200,
      text: JSON.stringify({ antwort: "Port 11434 [1].", quellen: [quelle], modell: "m", dauer_s: 2 }),
    });
    const a = await api.fragen("Welcher Port?", 3);
    expect(a.quellen[0]?.titel).toBe("Ollama");
    expect(anfragen).toEqual([
      { url: "http://api:8080/ask", method: "POST", body: '{"frage":"Welcher Port?","k":3}' },
    ]);
  });

  it("liefert bei der Suche nur die Quellen", async () => {
    const { api, anfragen } = attrappe({ status: 200, text: JSON.stringify({ quellen: [quelle] }) });
    expect(await api.suchen("Port")).toEqual([quelle]);
    expect(anfragen[0]?.url).toBe("http://api:8080/search");
  });

  it("meldet Fehler der API mit detail", async () => {
    const { api } = attrappe({ status: 503, text: '{"detail": "Ist der Gaming-PC wach?"}' });
    await expect(api.fragen("x")).rejects.toMatchObject({
      status: 503,
      message: "Ist der Gaming-PC wach?",
    });
  });

  it("meldet eine nicht erreichbare API mit Status 0", async () => {
    const { api } = attrappe(new Error("ECONNREFUSED"));
    const fehler = await api.status().catch((e: unknown) => e);
    expect(fehler).toBeInstanceOf(ApiFehler);
    expect(fehler).toMatchObject({ status: 0 });
    expect((fehler as Error).message).toContain("nicht erreichbar");
  });

  it("erkennt einen falschen Dienst", async () => {
    const { api } = attrappe({ status: 200, text: "<html>Router</html>" });
    await expect(api.status()).rejects.toThrow("antwortet nicht wie die API");
  });

  it("verlangt eine Adresse", async () => {
    const api = new AssistentApi("  ", () => Promise.reject(new Error("nie")));
    await expect(api.status()).rejects.toThrow("Keine API-Adresse");
  });
});

describe("fehlermeldung", () => {
  it("fasst Prüffehler zusammen", () => {
    const text = JSON.stringify({ detail: [{ msg: "zu lang" }, { msg: "zu kurz" }] });
    expect(fehlermeldung(422, text)).toBe("zu lang; zu kurz");
  });

  it("nimmt sonst den Text oder den Status", () => {
    expect(fehlermeldung(500, "Internal Server Error")).toBe("Internal Server Error");
    expect(fehlermeldung(502, "")).toBe("HTTP 502");
  });
});
