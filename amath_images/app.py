# app.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, JSONResponse
from typing import Optional
import base64
import json
import subprocess
from io import BytesIO

import cairosvg
from PIL import Image

from storage import GCSStore, CACHE_HEADERS, PNG_PATH, META_PATH
from keying import compute_key

app = FastAPI(title="Math Images", version="0.1.0")

# Lazy-initialized globals (set on startup)
store: Optional[GCSStore] = None
store_init_error: Optional[str] = None
runtime_settings = None  # created at startup


@app.on_event("startup")
def _init_store():
    """Delay env parsing and GCS client init so module import never crashes."""
    global store, store_init_error, runtime_settings
    try:
        # Import Settings at runtime (pydantic-settings v2)
        from settings import Settings  # type: ignore
        runtime_settings = Settings()
    except Exception as e:
        store = None
        store_init_error = f"settings_init_error: {e}"
        return

    try:
        store = GCSStore(
            bucket_name=runtime_settings.MATH_IMG_BUCKET,
            sa_json=runtime_settings.GCP_SERVICE_ACCOUNT_JSON,
        )
        store_init_error = None
    except Exception as e:
        store = None
        store_init_error = f"gcs_init_error: {e}"


@app.get("/health")
def health():
    if store_init_error:
        return {"ok": False, "error": store_init_error}
    if store is None:
        return {"ok": False, "error": "store_not_initialized"}
    try:
        probe = store.bucket.blob("health/_probe")
        _ = probe.exists()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/health/write")
def health_write():
    """Verify we can write to the bucket (permissions)."""
    if store_init_error:
        return {"ok": False, "error": store_init_error}
    if store is None:
        return {"ok": False, "error": "store_not_initialized"}
    try:
        gen = store.write_probe()
        return {"ok": True, "wrote": True, "generation": gen}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------- Node SVG render ----------
def _render_svg_node(latex: str, width_px: int, font_px: int) -> str:
    """Call the Node renderer and return SVG markup."""
    payload = json.dumps({"latex": latex, "widthPx": width_px, "fontPx": font_px})
    proc = subprocess.run(
        ["node", "renderer/render.js"],
        input=payload.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node_render_failed: {proc.stderr.decode('utf-8', 'ignore')}")
    return proc.stdout.decode("utf-8", "ignore")

@app.get("/health/render")
def health_render():
    """Confirm Node+MathJax can render SVG."""
    if store_init_error:
        return {"ok": False, "error": store_init_error}
    try:
        svg = _render_svg_node("E=mc^2", width_px=320, font_px=18)
        return {"ok": True, "svg_len": len(svg)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------- helpers ----------
def _b64url_decode(s: str) -> bytes:
    # Accept URL-safe base64 without padding
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))

def _validate_inputs(latex_utf8: bytes, wpt: float, fpx: int, scale: int):
    if runtime_settings is None:
        raise HTTPException(status_code=503, detail="settings_not_loaded")
    if len(latex_utf8) == 0 or len(latex_utf8) > runtime_settings.MAX_LATEX_BYTES:
        raise HTTPException(status_code=413, detail="latex_too_large")
    if not (0 < wpt <= runtime_settings.MAX_WIDTH_PT):
        raise HTTPException(status_code=400, detail="wpt_out_of_range")
    if scale not in runtime_settings.ALLOWED_SCALES:
        raise HTTPException(status_code=400, detail="bad_scale")
    if not (8 <= fpx <= 48):
        raise HTTPException(status_code=400, detail="fpx_out_of_range")

def _svg_to_png(svg_markup: str, output_width_px: int) -> bytes:
    """Rasterize SVG to PNG bytes at exact pixel width (transparent background)."""
    return cairosvg.svg2png(
        bytestring=svg_markup.encode("utf-8"),
        output_width=output_width_px,
        background_color=None,  # keep transparent
    )

def _png_height_px(png_bytes: bytes) -> int:
    """Return PNG pixel height using Pillow."""
    with Image.open(BytesIO(png_bytes)) as im:
        return im.height

# ---------- API ----------
@app.get("/math/v1/png/{key}.png")
def get_png(
    key: str,
    latex_b64: str = Query(..., description="base64url raw LaTeX"),
    wpt: float = Query(..., description="content width in points"),
    fpx: int = Query(..., description="font size in CSS px"),
    scale: int = Query(..., description="2 or 3"),
    token: str = Query(..., description="unit token string"),
):
    if store is None or runtime_settings is None:
        raise HTTPException(status_code=503, detail="store_init_failed")

    try:
        latex_bytes = _b64url_decode(latex_b64)
        latex_str = latex_bytes.decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="bad_base64")

    _validate_inputs(latex_bytes, wpt, fpx, scale)

    recomputed, pixel_width = compute_key(
        render_salt=runtime_settings.RENDER_SALT,
        token=token,
        scale=scale,
        wpt=wpt,
        fpx=fpx,
        latex_utf8=latex_bytes,
    )
    if recomputed != key:
        raise HTTPException(status_code=400, detail="key_mismatch")

    # 1) Try cache (GCS)
    png = store.get_png(key)
    if png is not None:
        headers = {
            **CACHE_HEADERS,
            "Content-Type": "image/png",
            "X-Math-Cache": "hit",
            "X-Math-Pixel-Width": str(pixel_width),
            "ETag": key,
        }
        return Response(content=png, media_type="image/png", headers=headers)

    # 2) Render on miss
    try:
        svg = _render_svg_node(latex_str, width_px=pixel_width, font_px=fpx)
        png = _svg_to_png(svg, output_width_px=pixel_width)
        height_px = _png_height_px(png)
        height_pt = height_px / float(scale)
    except Exception as e:
        # If render fails, behave like before (report miss) so iOS can fallback.
        return JSONResponse(
            status_code=502,
            content={"detail": "render_failed", "error": str(e)[:400]},
            headers={"X-Math-Cache": "error", "X-Math-Pixel-Width": str(pixel_width)},
        )

    # 3) Store PNG + meta, then return PNG
    try:
        # PNG
        png_blob = store.bucket.blob(PNG_PATH.format(key=key))
        png_blob.cache_control = CACHE_HEADERS["Cache-Control"]
        png_blob.upload_from_string(png, content_type="image/png")

        # Meta JSON
        meta_blob = store.bucket.blob(META_PATH.format(key=key))
        meta_blob.cache_control = CACHE_HEADERS["Cache-Control"]
        meta_json = json.dumps({"wPt": float(wpt), "hPt": float(height_pt)}, separators=(",", ":"))
        meta_blob.upload_from_string(meta_json, content_type="application/json")
    except Exception:
        # Return the rendered image even if storage write fails.
        headers = {
            "Content-Type": "image/png",
            "X-Math-Cache": "render_no_store",
            "X-Math-Pixel-Width": str(pixel_width),
        }
        return Response(content=png, media_type="image/png", headers=headers)

    headers = {
        **CACHE_HEADERS,
        "Content-Type": "image/png",
        "X-Math-Cache": "render",
        "X-Math-Pixel-Width": str(pixel_width),
        "ETag": key,
    }
    return Response(content=png, media_type="image/png", headers=headers)

@app.get("/math/v1/meta/{key}.json")
def get_meta(key: str):
    if store is None:
        raise HTTPException(status_code=503, detail="store_init_failed")
    meta = store.get_meta_text(key)
    if meta is None:
        raise HTTPException(status_code=404, detail="not_found")
    return Response(content=meta, media_type="application/json", headers=CACHE_HEADERS)