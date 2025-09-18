// renderer/render.js
import fs from "node:fs";

import { mathjax } from "mathjax-full/js/mathjax.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";

// Read JSON from stdin: { latex, widthPx, fontPx }
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
} catch (e) {
  console.error("bad_json");
  process.exit(2);
}

const { latex, widthPx = 320, fontPx = 18, display = true } = payload || {};

try {
  const adaptor = liteAdaptor();
  RegisterHTMLHandler(adaptor);

  const tex = new TeX({
    packages: AllPackages,
  });

  // Important bits:
  //  - fontCache 'none' => self-contained SVGs (no external fonts)
  //  - mtextInheritFont => use system font metrics for text in <mtext>
  //  - linebreaks via containerWidth + em scaling (see below)
  const svg = new SVG({
    fontCache: "none",
    mtextInheritFont: true,
  });

  const html = mathjax.document("", {
    InputJax: tex,
    OutputJax: svg,
  });

  // containerWidth is in "em". We set em so 1em = fontPx CSS pixels,
  // then express the container width in em to match widthPx.
  const em = fontPx; // 1em = fontPx px
  const containerWidthEm = widthPx / em;

  const node = html.convert(latex || "", {
    display: !!display,
    em,                // px per em
    ex: em / 2,        // rough ex
    containerWidth: containerWidthEm,
  });

  const svgStr = adaptor.innerHTML(node);
  process.stdout.write(svgStr);
} catch (e) {
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
}