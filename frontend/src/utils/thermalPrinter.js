// ESC/POS thermal printer over Web Bluetooth (58mm & 80mm)
// Direct silent printing without browser dialog.
// Chrome/Edge required (Web Bluetooth not available in Firefox/Safari).

const ESC = 0x1b;
const GS = 0x1d;
const LF = 0x0a;
const NUL = 0x00;

// Standard ESC/POS Bluetooth service UUIDs (common thermal printers).
const SERVICE_CANDIDATES = [
  0x18f0,
  "000018f0-0000-1000-8000-00805f9b34fb",
  "49535343-fe7d-4ae5-8fa9-9fafd205e455",
  "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
];

let cachedDevice = null;
let cachedCharacteristic = null;

const enc = new TextEncoder();

/** Build a byte payload from a mix of strings and byte arrays. */
function build(...parts) {
  const arrays = parts.map((p) => (typeof p === "string" ? enc.encode(p) : new Uint8Array(p)));
  const total = arrays.reduce((n, a) => n + a.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const a of arrays) { out.set(a, off); off += a.length; }
  return out;
}

async function connectPrinter() {
  if (!navigator.bluetooth) throw new Error("Perangkat ini tidak mendukung Web Bluetooth. Gunakan Chrome/Edge di HP atau desktop.");
  if (cachedCharacteristic && cachedDevice?.gatt?.connected) return cachedCharacteristic;
  const device = await navigator.bluetooth.requestDevice({
    acceptAllDevices: true,
    optionalServices: SERVICE_CANDIDATES,
  });
  const server = await device.gatt.connect();
  let writeChar = null;
  for (const svcId of SERVICE_CANDIDATES) {
    try {
      const svc = await server.getPrimaryService(svcId);
      const chars = await svc.getCharacteristics();
      writeChar = chars.find((c) => c.properties.write || c.properties.writeWithoutResponse) || null;
      if (writeChar) break;
    } catch (_) { /* try next */ }
  }
  if (!writeChar) throw new Error("Printer tidak menyediakan karakteristik write ESC/POS.");
  cachedDevice = device;
  cachedCharacteristic = writeChar;
  device.addEventListener("gattserverdisconnected", () => { cachedCharacteristic = null; });
  return writeChar;
}

async function writeChunks(characteristic, bytes) {
  const CHUNK = 180;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const chunk = bytes.slice(i, i + CHUNK);
    if (characteristic.writeValueWithoutResponse) {
      await characteristic.writeValueWithoutResponse(chunk);
    } else {
      await characteristic.writeValue(chunk);
    }
  }
}

// ESC/POS helpers
const align = { left: 0, center: 1, right: 2 };
export const escpos = {
  init: () => [ESC, 0x40],
  setAlign: (n) => [ESC, 0x61, n],
  bold: (on) => [ESC, 0x45, on ? 1 : 0],
  double: (on) => [GS, 0x21, on ? 0x11 : 0x00],
  feed: (n = 1) => new Array(n).fill(LF),
  cut: () => [GS, 0x56, 0x42, 0x00],
  line: (width = 32) => enc.encode("-".repeat(width) + "\n"),
  text: (str) => enc.encode(str),
};

export function formatCurrency(n) {
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n || 0);
}

// Pad two columns to `width` (default 32 chars for 58mm)
export function twoCol(left, right, width = 32) {
  const l = String(left);
  const r = String(right);
  const pad = Math.max(1, width - l.length - r.length);
  return l + " ".repeat(pad) + r + "\n";
}

/** Build ESC/POS byte payload for a POS sale receipt. */
export function buildSaleReceipt({ outlet, sale, cashier, width = 32 }) {
  const parts = [];
  const cfg = outlet.printer_config || {};
  parts.push(new Uint8Array(escpos.init()));
  parts.push(new Uint8Array(escpos.setAlign(align.center)));
  parts.push(new Uint8Array(escpos.double(true)));
  parts.push(escpos.text(`${outlet.name}\n`));
  parts.push(new Uint8Array(escpos.double(false)));
  if (outlet.address) parts.push(escpos.text(`${outlet.address}\n`));
  if (outlet.phone) parts.push(escpos.text(`Telp: ${outlet.phone}\n`));
  // Custom header lines from Printer Settings
  if (cfg.header && String(cfg.header).trim()) {
    for (const ln of String(cfg.header).split("\n")) if (ln.trim()) parts.push(escpos.text(`${ln}\n`));
  }
  parts.push(new Uint8Array(escpos.setAlign(align.left)));
  parts.push(escpos.line(width));
  const dt = sale.created_at ? new Date(sale.created_at) : new Date();
  parts.push(escpos.text(`${dt.toLocaleString("id-ID")}\n`));
  parts.push(escpos.text(`No  : #${String(sale.id).slice(-8).toUpperCase()}\n`));
  parts.push(escpos.text(`Kasir: ${cashier}\n`));
  parts.push(escpos.text(`Meja : ${sale.table || sale.table_no || "-"}\n`));
  parts.push(escpos.line(width));
  for (const ln of (sale.lines || [])) {
    parts.push(escpos.text(`${ln.name}\n`));
    parts.push(escpos.text(twoCol(`  ${ln.quantity} x ${formatCurrency(ln.price)}`, formatCurrency(ln.price * ln.quantity), width)));
  }
  parts.push(escpos.line(width));
  parts.push(escpos.text(twoCol("Subtotal", formatCurrency(sale.subtotal), width)));
  if (sale.tax) parts.push(escpos.text(twoCol("Pajak", formatCurrency(sale.tax), width)));
  parts.push(new Uint8Array(escpos.bold(true)));
  parts.push(escpos.text(twoCol("TOTAL", formatCurrency(sale.total), width)));
  parts.push(new Uint8Array(escpos.bold(false)));
  parts.push(escpos.line(width));
  parts.push(escpos.text(twoCol("Bayar", sale.payment_method, width)));
  if (sale.cash_received) parts.push(escpos.text(twoCol("Tunai", formatCurrency(sale.cash_received), width)));
  if (sale.change_amount) parts.push(escpos.text(twoCol("Kembali", formatCurrency(sale.change_amount), width)));
  if (sale.payment_reference) parts.push(escpos.text(twoCol("Ref", String(sale.payment_reference).slice(0, 16), width)));
  parts.push(new Uint8Array(escpos.feed(1)));
  parts.push(new Uint8Array(escpos.setAlign(align.center)));
  // Custom footer lines (fallback to default if empty)
  if (cfg.footer && String(cfg.footer).trim()) {
    for (const ln of String(cfg.footer).split("\n")) if (ln.trim()) parts.push(escpos.text(`${ln}\n`));
  } else {
    parts.push(escpos.text("Terima kasih atas kunjungan Anda!\n"));
    parts.push(escpos.text(`~ ${outlet.brand_name || "MJD Kupi"} ~\n`));
  }
  parts.push(new Uint8Array(escpos.feed(3)));
  parts.push(new Uint8Array(escpos.cut()));
  return build(...parts);
}

/** Build ESC/POS byte payload for the shift close report. */
export function buildShiftReport({ outlet, report, width = 32 }) {
  const s = report.shift || {};
  const parts = [];
  parts.push(new Uint8Array(escpos.init()));
  parts.push(new Uint8Array(escpos.setAlign(align.center)));
  parts.push(new Uint8Array(escpos.double(true)));
  parts.push(escpos.text(`${outlet.name}\n`));
  parts.push(new Uint8Array(escpos.double(false)));
  parts.push(escpos.text("LAPORAN SHIFT KASIR\n"));
  parts.push(new Uint8Array(escpos.setAlign(align.left)));
  parts.push(escpos.line(width));
  const dt = (iso) => iso ? new Date(iso).toLocaleString("id-ID") : "-";
  parts.push(escpos.text(`Kasir  : ${report.cashier_name || "-"}\n`));
  parts.push(escpos.text(`Mulai  : ${dt(s.opened_at)}\n`));
  parts.push(escpos.text(`Selesai: ${dt(s.closed_at)}\n`));
  parts.push(escpos.text(`Status : ${(s.status || "").toUpperCase()}\n`));
  parts.push(escpos.line(width));
  parts.push(escpos.text(twoCol("Modal Awal", formatCurrency(s.opening_cash), width)));
  parts.push(escpos.text(twoCol("Total Cash", formatCurrency(report.total_cash), width)));
  parts.push(escpos.text(twoCol("Total Transfer", formatCurrency(report.total_transfer), width)));
  parts.push(new Uint8Array(escpos.bold(true)));
  parts.push(escpos.text(twoCol("TOTAL OMSET", formatCurrency(report.total_omset), width)));
  parts.push(new Uint8Array(escpos.bold(false)));
  parts.push(escpos.text(twoCol("Meja Lunas", String(report.tables_paid || 0), width)));
  parts.push(escpos.text(twoCol("Meja Pending", String(report.tables_pending || 0), width)));
  parts.push(escpos.text(twoCol("Pengeluaran", formatCurrency(report.expenses_total), width)));
  parts.push(escpos.line(width));
  parts.push(escpos.text("BREAKDOWN PER MERCHANT:\n"));
  for (const [k, v] of Object.entries(report.per_merchant || {})) {
    parts.push(escpos.text(twoCol(`- ${k}`.slice(0, 20), formatCurrency(v), width)));
  }
  parts.push(escpos.line(width));
  parts.push(new Uint8Array(escpos.setAlign(align.center)));
  parts.push(escpos.text("Selisih Kas: " + formatCurrency(s.variance || 0) + "\n"));
  parts.push(new Uint8Array(escpos.feed(3)));
  parts.push(new Uint8Array(escpos.cut()));
  return build(...parts);
}

/** Kitchen ticket - one per merchant, marked as DAPUR */
export function buildKitchenTicket({ outlet, ticket, width = 32 }) {
  const parts = [];
  parts.push(new Uint8Array(escpos.init()));
  parts.push(new Uint8Array(escpos.setAlign(align.center)));
  parts.push(new Uint8Array(escpos.double(true)));
  parts.push(escpos.text(`** DAPUR **\n`));
  parts.push(new Uint8Array(escpos.double(false)));
  parts.push(escpos.text(`${ticket.merchant_name || outlet.name}\n`));
  parts.push(new Uint8Array(escpos.setAlign(align.left)));
  parts.push(escpos.line(width));
  parts.push(escpos.text(`Meja : ${ticket.table_no || ticket.table || "-"}\n`));
  parts.push(escpos.text(`Order: #${String(ticket.source_id || ticket.id).slice(-6).toUpperCase()}\n`));
  parts.push(escpos.text(new Date().toLocaleString("id-ID") + "\n"));
  parts.push(escpos.line(width));
  for (const ln of (ticket.lines || [])) {
    parts.push(new Uint8Array(escpos.bold(true)));
    parts.push(escpos.text(`${ln.quantity}x ${ln.name}\n`));
    parts.push(new Uint8Array(escpos.bold(false)));
  }
  parts.push(new Uint8Array(escpos.feed(3)));
  parts.push(new Uint8Array(escpos.cut()));
  return build(...parts);
}

/** Direct print any prebuilt ESC/POS byte array. Silent, no browser dialog. */
export async function directPrint(bytes) {
  if (!bytes || bytes.length === 0) return { ok: false, reason: "empty" };
  const ch = await connectPrinter();
  await writeChunks(ch, bytes);
  return { ok: true };
}

export async function pairPrinter() {
  await connectPrinter();
  return { ok: true, name: cachedDevice?.name || "Unknown" };
}

export function isPrinterConnected() {
  return !!(cachedCharacteristic && cachedDevice?.gatt?.connected);
}

export function pairedPrinterName() {
  return cachedDevice?.name || "";
}

export function isPrinterSupported() {
  return typeof navigator !== "undefined" && !!navigator.bluetooth;
}
