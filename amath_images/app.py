# app.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, JSONResponse
from typing import Optional
import base64

from storage import GCSStore, CACHE_HEADERS
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
        # Real GCS probe (auth + bucket). HEAD request under the hood.
        probe = store.bucket.blob("health/_probe")
        _ = probe.exists()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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

    png = store.get_png(key)
    if png is None:
        # Stub behavior for v1: no render yet — just advertise the miss.
        return JSONResponse(
            status_code=404,
            content={"detail": "render_miss"},
            headers={"X-Math-Cache": "miss", "X-Math-Pixel-Width": str(pixel_width)},
        )

    headers = {
        **CACHE_HEADERS,
        "Content-Type": "image/png",
        "X-Math-Cache": "hit",
        "X-Math-Pixel-Width": str(pixel_width),
        "ETag": key,  # stable across time for this content
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