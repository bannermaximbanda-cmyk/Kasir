/**
 * Client-side image compressor + uploader.
 *
 * Flow: File → canvas resize (client-side, no CPU cost on server) → WebP blob →
 *       POST /api/upload/image?scope=... → { url }. Storing only URLs (never
 *       Base64) keeps DB rows tiny and page loads fast.
 *
 * Scope-based max dimensions match the backend:
 *   product → 600px, logo → 400px, banner → 1200px.
 */
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const MAX_SIDE = { product: 600, logo: 400, banner: 1200 };
const QUALITY = 0.82; // WebP quality — visually near-lossless at ~5× JPEG compression.

/** Resize an image File on the client → WebP Blob (aspect preserved). */
async function compressToWebP(file, maxSide) {
  const bitmap = await createImageBitmapSafe(file);
  const { width, height } = bitmap;
  const scale = Math.max(width, height);
  const ratio = scale > maxSide ? maxSide / scale : 1;
  const w = Math.max(1, Math.round(width * ratio));
  const h = Math.max(1, Math.round(height * ratio));
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h); // flatten alpha for WebP
  ctx.drawImage(bitmap, 0, 0, w, h);
  return await new Promise((resolve) => canvas.toBlob(resolve, "image/webp", QUALITY));
}

/** Cross-browser bitmap loader (Safari fallback via <img> element). */
async function createImageBitmapSafe(file) {
  if (window.createImageBitmap) {
    try { return await window.createImageBitmap(file); } catch (_) { /* fall through */ }
  }
  return await new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = (e) => { URL.revokeObjectURL(url); reject(e); };
    img.src = url;
  });
}

/**
 * Upload a File → returns absolute image URL suitable for <img src=...>.
 * Falls back to Base64 data URL only if the network upload fails, so the
 * previous UX still works (with a warning in console).
 */
export async function uploadImage(file, scope = "product") {
  if (!file) return "";
  const maxSide = MAX_SIDE[scope] || MAX_SIDE.product;
  let blob;
  try { blob = await compressToWebP(file, maxSide); }
  catch (e) { console.warn("[uploadImage] compress failed, sending raw", e); blob = file; }
  const fd = new FormData();
  fd.append("file", blob, `${scope}.webp`);
  try {
    const { data } = await axios.post(`${API}/upload/image?scope=${encodeURIComponent(scope)}`, fd);
    // Backend returns "/api/uploads/xxx.webp"; make it an absolute URL so it
    // works even when the frontend fetches from a different origin.
    return data.url?.startsWith("http") ? data.url : `${process.env.REACT_APP_BACKEND_URL}${data.url}`;
  } catch (err) {
    console.warn("[uploadImage] upload failed, falling back to data URL", err?.response?.status || err);
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }
}
