// MathText.jsx
import React from "react";
import { InlineMath, BlockMath } from "react-katex";
import "katex/dist/katex.min.css";

// Splits a string into plain text and math (\\(...\\) or \\[...\\])
function parseMathSegments(text) {
  const pattern = /\\\((.+?)\\\)|\\\[(.+?)\\\]/g;
  let result = [];
  let lastIndex = 0;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    // Push plain text before this match
    if (match.index > lastIndex) {
      result.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }

    if (match[0].startsWith("\\[")) {
      result.push({ type: "block", content: match[2] });
    } else {
      result.push({ type: "inline", content: match[1] });
    }

    lastIndex = pattern.lastIndex;
  }

  // Push any remaining plain text
  if (lastIndex < text.length) {
    result.push({ type: "text", content: text.slice(lastIndex) });
  }

  return result;
}

export default function MathText({ children }) {
  const segments = parseMathSegments(children);

  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === "inline") return <InlineMath key={i}>{seg.content}</InlineMath>;
        if (seg.type === "block") return <BlockMath key={i}>{seg.content}</BlockMath>;
        return <span key={i}>{seg.content}</span>;
      })}
    </>
  );
}
