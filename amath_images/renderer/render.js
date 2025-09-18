// renderer/render.js
import { mathjax } from "mathjax-full/js/mathjax.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";

// Read JSON from stdin: { latex, widthPx, fontPx, display }
const stdin = await new Promise((resolve, reject) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => (data += c));
  process.stdin.on("end", () => resolve(data));
  process.stdin.on("error", reject);
});

let payload;
try {
  payload = JSON.parse(stdin || "{}");
} catch {
  console.error("bad_json");
  process.exit(2);
}

const { latex, widthPx = 320, fontPx = 18, display = true } = payload || {};

try {
  const adaptor = liteAdaptor();
  RegisterHTMLHandler(adaptor);

  // Match the iOS WebView TeX settings (delimiters + escapes)
  const tex = new TeX({
    packages: AllPackages,
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
    processEscapes: true,
  });

  // Self-contained SVGs, inherit mtext font, and explicit linebreaks
  const svg = new SVG({
    fontCache: "none",
    mtextInheritFont: true,
    linebreaks: { automatic: true, width: "container" },
  });

  const html = mathjax.document("", { InputJax: tex, OutputJax: svg });

  // containerWidth is in em; set 1em = fontPx (CSS px)
  const em = fontPx;
  const containerWidthEm = widthPx / em;

  const node = html.convert(latex || "", {
    display: !!display,
    em,            // px per em
    ex: em / 2,    // rough ex
    containerWidth: containerWidthEm,
  });

  process.stdout.write(adaptor.innerHTML(node));
} catch (e) {
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
}