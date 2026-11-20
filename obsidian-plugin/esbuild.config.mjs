// Bündelt src/main.ts zu main.js, wie Obsidian es lädt. `obsidian` stellt die App selbst bereit.
import esbuild from "esbuild";

const produktion = process.argv[2] === "production";

const ctx = await esbuild.context({
  entryPoints: ["src/main.ts"],
  bundle: true,
  external: ["obsidian", "electron", "@codemirror/*", "@lezer/*"],
  format: "cjs",
  target: "es2020",
  logLevel: "info",
  sourcemap: produktion ? false : "inline",
  minify: produktion,
  outfile: "main.js",
});

if (produktion) {
  await ctx.rebuild();
  await ctx.dispose();
} else {
  await ctx.watch();
}
