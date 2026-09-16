import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { QRCodeSVG, QRCodeCanvas } from "qrcode.react";
import {
  BarChart3, Bell, ChefHat, ChevronDown, ClipboardList, Coffee, CreditCard,
  Database, DollarSign, FileText, Grid2X2, LogOut, Menu, Package, Plus,
  Printer, QrCode, Receipt, Search, Settings2, ShoppingCart, Store, Timer,
  Trash2, Users, Wallet, X, Building2, Volume2, MessageCircle, PlayCircle,
  StopCircle, UserCheck, Upload, Image as ImageIcon, Check, Copy, Shield,
  Eye, EyeOff, RefreshCw, Bluetooth, MapPin, Star, ChevronRight, Link as LinkIcon, Info,
  Download, FileSpreadsheet, TrendingDown, TrendingUp, ArrowRightLeft, Pencil, Filter, Eye as EyeOn,
} from "lucide-react";
import { pairPrinter, directPrint, isPrinterConnected, pairedPrinterName, isPrinterSupported, buildSaleReceipt, buildShiftReport, buildKitchenTicket } from "@/utils/thermalPrinter";
import { queueSale, drainQueue, queuedCount } from "@/utils/offlineQueue";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from "recharts";
import * as XLSX from "xlsx";
import "@/App.css";

const money = (n) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const ORIGIN = typeof window !== "undefined" ? window.location.origin : "";
// Leading Zero Fix (#8.1) — attach to onFocus on all number inputs
const numOnFocus = (e) => { if (e.target.value === "0" || e.target.value === 0) e.target.select(); };
axios.defaults.withCredentials = true;
// SEC-001 defense-in-depth: custom header on every request. Cross-site attackers cannot set
// custom headers on simple requests (triggers CORS preflight which is blocked).
axios.defaults.headers.common["X-Requested-With"] = "mjd-kupi";

const NAV_BY_ROLE = {
  "Super Admin": ["overview", "pos", "kds", "inventory", "expenses", "products", "merchants", "cashiers", "reports", "tables", "self-service", "vendor-center", "users", "printer", "settings"],
  "Admin": ["overview", "kds", "inventory", "expenses", "products", "merchants", "cashiers", "reports", "tables", "vendor-center", "printer"],
  Vendor: ["kds", "vendor-center", "self-service"],
  Kasir: ["pos", "expenses", "kds", "printer"],
};
const NAV_ITEMS = [
  { id: "overview", label: "Ringkasan", icon: BarChart3 },
  { id: "pos", label: "Terminal POS", icon: CreditCard, live: true },
  { id: "kds", label: "Kitchen Display", icon: ChefHat },
  { id: "inventory", label: "Inventori & Stok", icon: Package },
  { id: "expenses", label: "Pengeluaran", icon: Wallet },
  { id: "products", label: "Produk & HPP", icon: ClipboardList },
  { id: "merchants", label: "Merchant / Tenant", icon: Store },
  { id: "cashiers", label: "Monitoring Kasir", icon: UserCheck },
  { id: "reports", label: "Laporan Keuangan", icon: FileText },
  { id: "tables", label: "QR Meja", icon: Grid2X2 },
  { id: "self-service", label: "Self-Service", icon: QrCode },
  { id: "vendor-center", label: "Pusat Vendor", icon: Users },
  { id: "users", label: "User & Security", icon: Shield },
  { id: "printer", label: "Pengaturan Printer", icon: Printer },
  { id: "settings", label: "Pengaturan Sistem", icon: Settings2 },
];

export default function App() {
  // Public route: /self-order?table=NN (customer QR scan)
  if (typeof window !== "undefined" && window.location.pathname === "/self-order") {
    return <CustomerSelfOrder />;
  }
  return <AdminApp />;
}

function AdminApp() {
  const [session, setSession] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [page, setPage] = useState("overview");
  const [products, setProducts] = useState([]);
  const [merchants, setMerchants] = useState([]);
  const [outlets, setOutlets] = useState([]);
  const [activeOutlet, setActiveOutlet] = useState("outlet-sudirman");
  const [cart, setCart] = useState([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Semua");
  const [toast, setToast] = useState("");
  const [sidebar, setSidebar] = useState(false);
  const [collapsed, setCollapsed] = useState(() => (typeof window !== "undefined" && localStorage.getItem("mjd_sidebar_collapsed") === "1"));
  const [branding, setBranding] = useState({ name: "MJD Kupi", theme_color: "#f97316", logo_url: "", banner_url: "" });
  const [brandingText, setBrandingText] = useState({ name: "MJD Kupi", subtitle: "Retail Command Center" });
  const [featureMatrix, setFeatureMatrix] = useState({}); // { "role:Kasir": {pos:true, kds:false}, "outlet:x": {...} }
  const [taxConfig, setTaxConfig] = useState({ enabled: false, percent: 0 });
  const [notifications, setNotifications] = useState({ items: [], unread_count: 0 });
  const [showNotif, setShowNotif] = useState(false);
  const [expenses, setExpenses] = useState([]);
  const [shift, setShift] = useState(null);
  const [showShiftOpen, setShowShiftOpen] = useState(false);
  const [showShiftClose, setShowShiftClose] = useState(false);
  const [showPayment, setShowPayment] = useState(false);
  const [lastSale, setLastSale] = useState(null);
  const [showReceipt, setShowReceipt] = useState(false);
  const [onlineOrders, setOnlineOrders] = useState([]);
  const [showOnlineOrders, setShowOnlineOrders] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [shiftReport, setShiftReport] = useState(null);
  const [brandLogo, setBrandLogo] = useState("");
  const [offlineQueued, setOfflineQueued] = useState(0);
  const [online, setOnline] = useState(typeof navigator !== "undefined" ? navigator.onLine : true);
  const prevOnlineIdsRef = useRef(new Set());
  const chimeRef = useRef(null);
  const printerRef = useRef(null);

  const notify = (text) => { setToast(text); window.setTimeout(() => setToast(""), 2500); };
  const role = session?.role;
  const toggleCollapsed = () => setCollapsed((c) => { const nx = !c; try { localStorage.setItem("mjd_sidebar_collapsed", nx ? "1" : "0"); } catch {} return nx; });
  // Feature toggles: an item is DISABLED if any applicable rule sets it to false
  const isFeatureAllowed = (id) => {
    if (!featureMatrix || Object.keys(featureMatrix).length === 0) return true;
    const roleKey = `role:${role}`;
    const outletKey = `outlet:${session?.outlet_id}`;
    const roleRule = featureMatrix[roleKey];
    const outletRule = featureMatrix[outletKey];
    if (roleRule && roleRule[id] === false) return false;
    if (outletRule && outletRule[id] === false) return false;
    return true;
  };
  const allowed = NAV_ITEMS.filter((n) => (NAV_BY_ROLE[role] || []).includes(n.id)).filter((n) => isFeatureAllowed(n.id));

  const reloadProducts = () => {
    const includeInactive = (session?.role === "Super Admin" || session?.role === "Admin") ? "?include_inactive=1" : "";
    return axios.get(`${API}/products${includeInactive}`).then(({ data }) => setProducts(data.map((p) => ({ ...p, id: p.id, price: Number(p.price), cost: Number(p.cost), stock: Number(p.stock), is_active: p.is_active !== false })))).catch(() => {});
  };
  const reloadMerchants = () => axios.get(`${API}/merchants`).then(({ data }) => setMerchants(data)).catch(() => {});
  const reloadExpenses = () => axios.get(`${API}/expenses`).then(({ data }) => setExpenses(data)).catch(() => {});
  const reloadShift = () => axios.get(`${API}/shifts/current`).then(({ data }) => setShift(data)).catch(() => setShift(null));
  const reloadOnlineOrders = async () => {
    try {
      const { data } = await axios.get(`${API}/pos/online-orders`);
      const ids = new Set(data.map((o) => o.id));
      const prev = prevOnlineIdsRef.current;
      const hasNew = prev.size > 0 && [...ids].some((id) => !prev.has(id));
      if (hasNew && chimeRef.current) chimeRef.current();
      prevOnlineIdsRef.current = ids;
      setOnlineOrders(data);
    } catch {}
  };

  useEffect(() => {
    axios.get(`${API}/auth/me`).then(({ data }) => setSession(data)).catch(() => {}).finally(() => setAuthLoading(false));
  }, []);
  useEffect(() => {
    if (!session) return;
    setPage(session.role === "Kasir" ? "pos" : session.role === "Vendor" ? "kds" : "overview");
    // Default consolidated view for admin/super-admin
    if (session.role === "Super Admin" || session.role === "Admin") setActiveOutlet("all");
    else setActiveOutlet(session.outlet_id || "outlet-sudirman");
    reloadProducts(); reloadMerchants(); reloadExpenses();
    // Super Admin includes inactive outlets so they can reactivate; others only get active
    const outletUrl = session?.role === "Super Admin" ? `${API}/outlets?include_inactive=1` : `${API}/outlets`;
    axios.get(outletUrl).then(({ data }) => setOutlets(data)).catch(() => {});
    axios.get(`${API}/settings/logo`).then(({ data }) => setBrandLogo(data?.logo_data || "")).catch(() => {});
    axios.get(`${API}/branding/current`).then(({ data }) => {
      setBranding(data);
      try {
        document.documentElement.style.setProperty("--brand-accent", data.theme_color || "#f97316");
      } catch {}
    }).catch(() => {});
    axios.get(`${API}/feature-toggles`).then(({ data }) => setFeatureMatrix(data?.matrix || {})).catch(() => {});
    axios.get(`${API}/settings/branding_text`).then(({ data }) => {
      if (data && typeof data === "object" && (data.name || data.subtitle)) setBrandingText({ name: data.name || "MJD Kupi", subtitle: data.subtitle || "Retail Command Center" });
    }).catch(() => {});
    axios.get(`${API}/settings/tax_config`).then(({ data }) => {
      if (data && typeof data === "object") setTaxConfig({ enabled: !!data.enabled, percent: Number(data.percent || 0) });
    }).catch(() => {});
    // Notifications polling every 15s
    const loadNotif = () => axios.get(`${API}/notifications`, { params: { outlet_id: activeOutlet !== "all" ? activeOutlet : undefined } }).then(({ data }) => setNotifications(data)).catch(() => {});
    loadNotif();
    const notifTimer = setInterval(loadNotif, 15000);
    if (session.role === "Kasir") reloadShift();
    // Setup WebAudio chime
    chimeRef.current = () => {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const o = ctx.createOscillator(); const g = ctx.createGain();
        o.type = "sine"; o.frequency.value = 1200; g.gain.value = 0.18;
        o.connect(g).connect(ctx.destination); o.start();
        setTimeout(() => { o.frequency.value = 880; }, 130);
        setTimeout(() => { o.stop(); ctx.close(); }, 380);
      } catch {}
    };
    // Poll online orders every 4s for cashier/admin/super
    let onlineTimer = null;
    if (["Kasir", "Admin", "Super Admin"].includes(session.role)) {
      reloadOnlineOrders();
      onlineTimer = setInterval(reloadOnlineOrders, 4000);
    }
    return () => {
      clearInterval(notifTimer);
      if (onlineTimer) clearInterval(onlineTimer);
    };
  }, [session]);

  useEffect(() => {
    // Offline resilience: track connectivity + auto-drain queue on reconnect
    const goOnline = async () => {
      setOnline(true);
      try {
        const { synced, remaining } = await drainQueue(async (p) => { await axios.post(`${API}/sales`, p); });
        setOfflineQueued(remaining);
        if (synced > 0) { notify(`${synced} transaksi offline berhasil disinkronkan`); reloadProducts(); }
      } catch {}
    };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    queuedCount().then(setOfflineQueued).catch(() => {});
    return () => { window.removeEventListener("online", goOnline); window.removeEventListener("offline", goOffline); };
  }, []);

  const filtered = useMemo(
    () => products.filter((p) => p.is_active !== false && (category === "Semua" || p.category === category) && p.name.toLowerCase().includes(query.toLowerCase())),
    [products, category, query]
  );
  const subtotal = cart.reduce((sum, i) => sum + i.price * i.qty, 0);
  const tax = taxConfig.enabled && taxConfig.percent > 0 ? Math.round(subtotal * (taxConfig.percent / 100)) : 0;
  const total = subtotal + tax;

  const addToCart = (product, variant = null, notes = "") => setCart((cur) => {
    const key = variant ? `${product.id}__${variant.id}` : product.id;
    const found = cur.find((i) => i.key === key && i.notes === notes);
    if (found) return cur.map((i) => i === found ? { ...i, qty: i.qty + 1 } : i);
    const price = variant ? Number(variant.price) : Number(product.price);
    return [...cur, {
      key, id: product.id, name: product.name, vendor: product.vendor, merchant_id: product.merchant_id,
      color: product.color, image_url: product.image_url,
      variant_id: variant?.id || null, variant_name: variant?.name || "", notes: notes || "",
      price, qty: 1,
    }];
  });
  const adjustCart = (key, amount) => setCart((cur) => cur.map((i) => i.key === key ? { ...i, qty: i.qty + amount } : i).filter((i) => i.qty > 0));

  const openPayment = () => {
    if (!cart.length) return;
    if (session.role === "Kasir" && !shift) { setShowShiftOpen(true); notify("Buka shift terlebih dahulu sebelum bertransaksi"); return; }
    setShowPayment(true);
  };

  const confirmSale = async ({ method, reference, cashReceived }) => {
    const payload = {
      table: "Meja 07",
      lines: cart.map((i) => ({ product_id: String(i.id), name: i.name, quantity: i.qty, price: i.price, vendor: i.vendor, merchant_id: i.merchant_id, variant_id: i.variant_id || null, variant_name: i.variant_name || "", notes: i.notes || "" })),
      subtotal, tax, total,
      payment_method: method,
      payment_reference: reference || "",
      cash_received: Number(cashReceived) || 0,
      change_amount: Math.max(0, (Number(cashReceived) || 0) - total),
    };
    try {
      const { data } = await axios.post(`${API}/sales`, payload, { timeout: 8000 });
      setLastSale({ ...payload, id: data.id, created_at: data.created_at });
      setShowPayment(false);
      setShowReceipt(true);
      await reloadProducts();
      notify("Transaksi berhasil, tiket dapur terkirim");
    } catch (e) {
      // If network failure, queue offline
      if (!navigator.onLine || e.code === "ECONNABORTED" || !e.response) {
        await queueSale(payload);
        const c = await queuedCount();
        setOfflineQueued(c);
        setShowPayment(false);
        setCart([]);
        notify(`Offline: transaksi disimpan di antrean (${c} pending sync)`);
      } else {
        notify(e.response?.data?.detail || "Gagal menyimpan transaksi");
      }
    }
  };

  if (authLoading) return <div className="auth-loading" data-testid="auth-loading">Memuat ruang kerja MJD Kupi…</div>;
  if (!session) return <Login onLogin={setSession} />;

  const pageTitle = NAV_ITEMS.find((n) => n.id === page)?.label || "Ringkasan";

  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`} data-testid="mjd-kupi-app">
      <aside className={`sidebar ${sidebar ? "is-open" : ""} ${collapsed ? "collapsed" : ""}`} data-testid="main-sidebar">
        <div className="brand">
          <div className="brand-mark" data-testid="brand-logo">{(branding.logo_url || brandLogo) ? <img src={branding.logo_url || brandLogo} alt="logo" /> : <Coffee size={19} />}</div>
          <div className="brand-text"><strong data-testid="brand-name">{brandingText.name || "MJD Kupi"}</strong><span data-testid="brand-subtitle">{brandingText.subtitle || "Retail Command Center"}</span></div>
          <button className="collapse-toggle" data-testid="collapse-sidebar-button" onClick={toggleCollapsed} title={collapsed ? "Perluas sidebar" : "Ciutkan sidebar"}>
            <Menu size={16} />
          </button>
          <button className="mobile-close" data-testid="close-sidebar-button" onClick={() => setSidebar(false)}><X size={18} /></button>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="sidebar-nav">
          {allowed.map(({ id, label, icon: Icon, live }) => (
            <button key={id} className={page === id ? "nav-item active" : "nav-item"} data-testid={`nav-${id}`} title={collapsed ? label : ""} onClick={() => { setPage(id); setSidebar(false); }}>
              <Icon size={18} /><span>{label}</span>{live && <em>Live</em>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sync-card">
            <div className="sync-icon"><Database size={16} /></div>
            <div><b>Supabase Cloud</b><span>Sync tersambung</span></div><i />
          </div>
          {session.role === "Kasir" && (
            <div className="shift-mini" data-testid="shift-mini">
              {shift ? (
                <>
                  <b>Shift Aktif</b>
                  <span>Kas awal: {money(shift.opening_cash)}</span>
                  <button className="outline-btn full" onClick={() => setShowShiftClose(true)} data-testid="close-shift-button"><StopCircle size={13}/> Tutup Shift</button>
                </>
              ) : (
                <>
                  <b>Belum ada shift</b>
                  <span>Buka shift untuk mulai kasir</span>
                  <button className="primary-btn full" onClick={() => setShowShiftOpen(true)} data-testid="open-shift-button"><PlayCircle size={13}/> Buka Shift</button>
                </>
              )}
            </div>
          )}
          <div className="user-card">
            <div className="avatar">{session.name.slice(0, 2).toUpperCase()}</div>
            <div><b>{session.name}</b><span>{session.role}</span></div>
            <button data-testid="logout-button" onClick={async () => { await axios.post(`${API}/auth/logout`, {}); setSession(null); }}><LogOut size={16} /></button>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="mobile-menu" data-testid="open-sidebar-button" onClick={() => setSidebar(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span data-testid="breadcrumb-brand">{brandingText.name || "MJD Kupi"}</span><b>/</b><strong>{pageTitle}</strong></div>
          <div className="top-actions">
            <div className="merchant-switch" data-testid="outlet-switcher-wrapper">
              <Building2 size={16} />
              <select value={activeOutlet} onChange={(e) => {
                if (e.target.value === "__add__") { setPage("settings"); notify("Tambah outlet dari menu Pengaturan Sistem"); return; }
                setActiveOutlet(e.target.value);
              }} data-testid="outlet-switcher">
                {(role === "Super Admin" || role === "Admin") && <option value="all">🏢 Semua Outlet (Konsolidasi)</option>}
                {outlets.length ? outlets.map((o) => <option value={o.id} key={o.id}>{o.name}</option>) : <option value="outlet-sudirman">Outlet Sudirman</option>}
                {(role === "Super Admin") && <option value="__add__">+ Tambah Outlet Baru…</option>}
              </select>
              <ChevronDown size={14} />
              <span className={`outlet-badge ${activeOutlet === "all" ? "all" : ""}`}>{activeOutlet === "all" ? "Semua" : "Aktif"}</span>
            </div>
            <div className="ops-status" data-testid="ops-status">
              <i className="pulse" /> POS: Online
              {session.role === "Kasir" && shift && <> · <b>Shift: Active ({session.name.split(" ")[0]})</b></>}
              {session.role === "Kasir" && !shift && <> · <em>Shift belum dibuka</em></>}
            </div>
            <div className="role-chip" data-testid="current-user-role">{session.name} · {session.role}</div>
            {(!online || offlineQueued > 0) && <div className="offline-chip" data-testid="offline-chip">{!online ? "🔌 OFFLINE" : `⏳ ${offlineQueued} pending`}</div>}
            <button className="icon-button notif-btn" data-testid="notifications-button" onClick={() => setShowNotif(true)}>
              <Bell size={18} />
              {notifications.unread_count > 0 && <span className="notif-badge" data-testid="notif-badge">{notifications.unread_count}</span>}
            </button>
            <div className="top-avatar">{session.name.slice(0, 2).toUpperCase()}</div>
          </div>
        </header>

        <div className="page-wrap">
          {page === "overview" && <Overview products={products} expenses={expenses} setPage={setPage} activeOutlet={activeOutlet} />}
          {page === "pos" && (
            <POS products={filtered} query={query} setQuery={setQuery} category={category} setCategory={setCategory}
                 cart={cart} addToCart={addToCart} adjustCart={adjustCart} subtotal={subtotal} tax={tax} total={total} taxConfig={taxConfig}
                 onPay={openPayment} shift={shift} role={session.role}
                 onlineOrders={onlineOrders} openOnline={() => setShowOnlineOrders(true)}
                 openHistory={() => setShowHistory(true)} />
          )}
          {page === "kds" && <KDS notify={notify} merchants={merchants} />}
          {page === "inventory" && <Inventory products={products} reload={reloadProducts} notify={notify} />}
          {page === "expenses" && <Expenses expenses={expenses} reload={reloadExpenses} notify={notify} session={session} shift={shift} />}
          {page === "products" && <Products products={products} merchants={merchants} outlets={outlets} session={session} reload={reloadProducts} notify={notify} />}
          {page === "merchants" && <Merchants merchants={merchants} reload={reloadMerchants} notify={notify} />}
          {page === "cashiers" && <CashierMonitor notify={notify} onView={setShiftReport} pinDisabled={!isFeatureAllowed("cashier_pin")} />}
          {page === "users" && session.role === "Super Admin" && <UserManagement notify={notify} />}
          {page === "reports" && <Reports products={products} expenses={expenses} />}
          {page === "tables" && <Tables notify={notify} activeOutlet={activeOutlet} branding={branding} />}
          {page === "self-service" && <SelfService products={products} notify={notify} activeOutlet={activeOutlet} outlets={outlets} />}
          {page === "vendor-center" && <VendorCenter notify={notify} />}
          {page === "settings" && <SettingsPage notify={notify} printerRef={printerRef} role={session.role} brandingText={brandingText} onBrandingTextSaved={(v) => setBrandingText(v)} pinDisabled={!isFeatureAllowed("cashier_pin")} onFeatureToggleSaved={() => axios.get(`${API}/feature-toggles`).then(({ data }) => setFeatureMatrix(data?.matrix || {})).catch(() => {})} />}
          {page === "printer" && <PrinterSettings notify={notify} />}
        </div>
        {showNotif && <NotificationDrawer notif={notifications} onClose={() => setShowNotif(false)}
          setPage={(p) => { setShowNotif(false); setPage(p); }}
          onOrderClick={(n) => {
            // Extract order UUID from notif id e.g. "order:a0927bdb-...."
            const orderId = String(n.id || "").replace(/^order:/, "");
            setShowNotif(false); setPage("pos"); setShowOnlineOrders(true);
            // Highlight the clicked order after modal opens
            setTimeout(() => {
              const el = document.querySelector(`[data-testid='online-item-${orderId}']`);
              if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("highlight-flash"); setTimeout(() => el.classList.remove("highlight-flash"), 2500); }
            }, 500);
          }}
          onMarkAll={() => setNotifications({ ...notifications, unread_count: 0 })} />}
      </main>

      {toast && <div className="toast" data-testid="toast-message"><span>✓</span>{toast}</div>}
      {showShiftOpen && <ShiftOpenModal session={session} activeOutlet={activeOutlet} outlets={outlets} notify={notify}
        onClose={() => setShowShiftOpen(false)}
        onOpened={(s) => { setShift(s); setShowShiftOpen(false); notify("Shift berhasil dibuka"); }} />}
      {showShiftClose && shift && <ShiftCloseModal shift={shift} onClose={() => setShowShiftClose(false)} onClosed={(rep) => { setShift(null); setShowShiftClose(false); setShiftReport(rep); notify(`Shift ditutup. Selisih ${money(rep.shift.variance)}`); }} />}
      {showPayment && <PaymentModal total={total} onClose={() => setShowPayment(false)} onConfirm={confirmSale} />}
      {showReceipt && lastSale && <ReceiptModal sale={lastSale} merchants={merchants} outlets={outlets} cashier={session?.name || ""} onClose={() => { setShowReceipt(false); setLastSale(null); setCart([]); }} notify={notify} />}
      {showOnlineOrders && <OnlineOrdersModal orders={onlineOrders} onClose={() => setShowOnlineOrders(false)} reload={reloadOnlineOrders} notify={notify} onAcceptDone={() => reloadProducts()} />}
      {showHistory && <HistoryModal onClose={() => setShowHistory(false)} notify={notify} />}
      {shiftReport && <ShiftReportModal report={shiftReport} outlets={outlets} onClose={() => setShiftReport(null)} notify={notify} />}
    </div>
  );
}

// -------- Section header --------
function SectionHeader({ eyebrow, title, description, action }) {
  return <div className="section-header"><div><div className="eyebrow">{eyebrow}</div><h1 data-testid="page-heading">{title}</h1><p>{description}</p></div>{action}</div>;
}
function Metric({ label, value, change, tone, icon: Icon }) {
  return <div className="metric" data-testid={`metric-${label.toLowerCase().replaceAll(" ", "-")}`}><div className={`metric-icon ${tone}`}><Icon size={19} /></div><span>{label}</span><strong>{value}</strong><small className={tone === "red" ? "negative" : "positive"}>{change}</small></div>;
}
function QuickAction({ icon: Icon, title, detail, onClick }) {
  return <button className="quick-action" data-testid={`quick-${title.toLowerCase().replaceAll(" ", "-")}`} onClick={onClick}><div><Icon size={18} /></div><span><b>{title}</b><small>{detail}</small></span><strong>→</strong></button>;
}

// -------- Overview (Enterprise Dashboard v2) --------

function Overview({ products, expenses, setPage, activeOutlet }) {
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("daily");
  const load = () => axios.get(`${API}/dashboard/analytics`, { params: { mode, outlet_id: activeOutlet } }).then(({ data }) => setData(data)).catch(() => {});
  useEffect(() => { load(); }, [mode, activeOutlet]);
  if (!data) return <div className="dash-loading">Memuat analytics…</div>;
  const kpi = data.kpi || {};
  const growth = kpi.sales_growth_percent || 0;
  const pieColors = ["#f97316", "#10b981", "#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444"];
  const marginPct = kpi.sales_today ? Math.round(((kpi.sales_today - kpi.expenses_total) / kpi.sales_today) * 100) : 0;
  return <>
    <SectionHeader eyebrow={`RINGKASAN OPERASIONAL · ${data.outlet_scope === "all" ? "Semua Outlet" : "Outlet aktif"}`} title="Dashboard operasional"
      description="Pantau kesehatan bisnis, tren penjualan, dan alert stok dalam satu pandangan."
      action={<button className="primary-btn" data-testid="overview-pos-button" onClick={() => setPage("pos")}><CreditCard size={16} /> Buka Terminal POS</button>} />
    {/* Row 1 · KPI Cards */}
    <div className="kpi-grid" data-testid="kpi-grid">
      <div className="kpi-card orange" data-testid="kpi-sales">
        <div className="kpi-head"><span>Total Penjualan</span><div className="kpi-icon"><Receipt size={16}/></div></div>
        <strong className="tabular">{money(kpi.sales_today)}</strong>
        <div className={`kpi-badge ${growth >= 0 ? "up" : "down"}`}>{growth >= 0 ? "▲" : "▼"} {Math.abs(growth)}% vs kemarin</div>
      </div>
      <div className="kpi-card green" data-testid="kpi-transactions">
        <div className="kpi-head"><span>Total Transaksi</span><div className="kpi-icon"><ShoppingCart size={16}/></div></div>
        <strong className="tabular">{kpi.transactions_today} Transaksi</strong>
        <div className="kpi-badge neutral">Basket size {money(kpi.avg_basket)}</div>
      </div>
      <div className="kpi-card blue" data-testid="kpi-profit">
        <div className="kpi-head"><span>Laba Bersih</span><div className="kpi-icon"><BarChart3 size={16}/></div></div>
        <strong className={`tabular ${kpi.net_profit < 0 ? "negative" : ""}`}>{money(kpi.net_profit)}</strong>
        <div className={`kpi-badge ${marginPct >= 0 ? "up" : "down"}`}>Margin {marginPct}%</div>
      </div>
      <div className="kpi-card red" data-testid="kpi-expenses">
        <div className="kpi-head"><span>Total Pengeluaran</span><div className="kpi-icon"><Wallet size={16}/></div></div>
        <strong className="tabular">{money(kpi.expenses_total)}</strong>
        <div className="kpi-badge neutral">{expenses.length} entri tercatat</div>
      </div>
    </div>
    {/* Row 2 · Charts */}
    <div className="analytics-grid">
      <section className="panel analytics-panel" data-testid="sales-trend-panel">
        <div className="panel-head">
          <div><h2>Performa Penjualan & Tren</h2><span>{mode === "hourly" ? "Per jam · hari ini" : "7 hari terakhir"}</span></div>
          <div className="mode-toggle">
            <button className={mode === "hourly" ? "active" : ""} onClick={() => setMode("hourly")} data-testid="trend-hourly">Jam</button>
            <button className={mode === "daily" ? "active" : ""} onClick={() => setMode("daily")} data-testid="trend-daily">Harian</button>
          </div>
        </div>
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <AreaChart data={data.trend} margin={{ top: 5, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="salesGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#f97316" stopOpacity={0.4}/>
                  <stop offset="100%" stopColor="#f97316" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <XAxis dataKey="label" stroke="#9aa4b2" fontSize={10} />
              <YAxis stroke="#9aa4b2" fontSize={10} tickFormatter={(v) => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : `${(v/1000).toFixed(0)}rb`} />
              <RTooltip contentStyle={{ background: "#1f2933", border: 0, borderRadius: 8, fontSize: 11, color: "#fff" }} formatter={(v, n) => n === "gross" ? [money(v), "Omset"] : [v, "Transaksi"]} />
              <Area type="monotone" dataKey="gross" stroke="#f97316" strokeWidth={2} fill="url(#salesGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>
      <section className="panel analytics-panel" data-testid="payment-donut-panel">
        <div className="panel-head"><div><h2>Metode Pembayaran</h2><span>30 hari terakhir</span></div></div>
        <div style={{ width: "100%", height: 260 }}>
          {data.payment_breakdown?.length ? <ResponsiveContainer>
            <PieChart>
              <Pie data={data.payment_breakdown} dataKey="total" nameKey="method" innerRadius={60} outerRadius={95} paddingAngle={3}>
                {data.payment_breakdown.map((_, i) => <Cell key={i} fill={pieColors[i % pieColors.length]} />)}
              </Pie>
              <Legend verticalAlign="bottom" iconType="circle" formatter={(v) => <span style={{ fontSize: 11, color: "#596574" }}>{v}</span>} />
              <RTooltip formatter={(v) => money(v)} contentStyle={{ background: "#1f2933", border: 0, borderRadius: 8, fontSize: 11, color: "#fff" }} />
            </PieChart>
          </ResponsiveContainer> : <div className="empty-cart"><CreditCard size={26} /><b>Belum ada transaksi</b></div>}
        </div>
      </section>
    </div>
    {/* Row 3 · Inventory + Top + Quick Actions */}
    <div className="ops-grid">
      <section className="panel ops-panel red" data-testid="lowstock-panel">
        <div className="panel-head"><div><h2>Stok Menipis</h2><span>Butuh restock segera</span></div><button className="text-btn" onClick={() => setPage("inventory")}>Semua →</button></div>
        <div className="lowstock-list">
          {data.low_stock?.length ? data.low_stock.slice(0, 5).map((p) => <div className="lowstock-row" key={p.id}>
            <div className="ls-info"><b>{p.name}</b><span>{p.vendor} · {p.outlet_id.replace("outlet-", "")}</span></div>
            <div className="ls-stock">
              <strong className={p.stock === 0 ? "danger" : "warn"}>{p.stock}</strong>
              <small>/ min {p.min}</small>
            </div>
            <button className="restock-btn" onClick={() => setPage("inventory")} data-testid={`restock-${p.id}`}>Restock</button>
          </div>) : <div className="empty-hint">Semua stok aman ✓</div>}
        </div>
      </section>
      <section className="panel ops-panel" data-testid="top-products-panel">
        <div className="panel-head"><div><h2>Top 5 Produk Terlaris</h2><span>Volume 30 hari</span></div></div>
        <div className="top-list">
          {data.top_products?.length ? data.top_products.map((p, i) => {
            const maxQty = data.top_products[0]?.quantity || 1;
            const pct = Math.round((p.quantity / maxQty) * 100);
            return <div className="top-row" key={p.product_id}>
              <div className="top-info"><span className="top-rank">#{i+1}</span><b>{p.name}</b></div>
              <div className="top-bar"><div style={{ width: `${pct}%` }} /></div>
              <div className="top-meta"><strong>{p.quantity}</strong><small>{money(p.revenue)}</small></div>
            </div>;
          }) : <div className="empty-hint">Belum ada data penjualan</div>}
        </div>
      </section>
      <section className="panel ops-panel" data-testid="quick-actions-panel">
        <div className="panel-head"><div><h2>Aksi Cepat</h2><span>Shortcut ke alur utama</span></div></div>
        <div className="quick-list">
          <QuickAction icon={Plus} title="Tambah produk" detail="Buat menu baru & atur HPP" onClick={() => setPage("products")} />
          <QuickAction icon={Package} title="Restock inventori" detail={`${products.reduce((a,p)=>a+(p.stock||0),0)} unit tercatat`} onClick={() => setPage("inventory")} />
          <QuickAction icon={Wallet} title="Catat pengeluaran" detail="Tambah biaya operasional" onClick={() => setPage("expenses")} />
          <QuickAction icon={PlayCircle} title="Buka Shift Kasir" detail="Mulai sesi terminal POS" onClick={() => setPage("pos")} />
        </div>
      </section>
    </div>
    {/* Row 4 · Outlet Comparison (only when 'Semua Outlet') */}
    {data.outlet_compare?.length > 0 && <section className="panel outlet-compare" data-testid="outlet-compare-panel">
      <div className="panel-head"><div><h2>Perbandingan Antar Outlet</h2><span>Omset 30 hari · sinkron Supabase</span></div></div>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>
          <BarChart data={data.outlet_compare} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <XAxis dataKey="name" stroke="#9aa4b2" fontSize={11} />
            <YAxis stroke="#9aa4b2" fontSize={10} tickFormatter={(v) => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : `${(v/1000).toFixed(0)}rb`} />
            <RTooltip formatter={(v, n) => n === "gross" ? [money(v), "Omset"] : [v, "Transaksi"]} contentStyle={{ background: "#1f2933", border: 0, borderRadius: 8, fontSize: 11, color: "#fff" }} />
            <Bar dataKey="gross" fill="#f97316" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>}
  </>;
}

// -------- Pagination Helper --------
const PAGE_SIZE = 12;

function usePagination(items, deps = [], pageSize = PAGE_SIZE) {
  const [page, setPage] = useState(1);
  // Reset to page 1 whenever filter deps change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setPage(1); }, deps);
  const totalPages = Math.max(1, Math.ceil((items?.length || 0) / pageSize));
  const clampedPage = Math.min(page, totalPages);
  const start = (clampedPage - 1) * pageSize;
  const end = start + pageSize;
  const pageItems = (items || []).slice(start, end);
  return {
    page: clampedPage, setPage, totalPages, pageItems,
    start: items?.length ? start + 1 : 0,
    end: Math.min(end, items?.length || 0),
    total: items?.length || 0,
  };
}

function PaginationBar({ page, setPage, totalPages, start, end, total, label = "produk", testid = "pagination" }) {
  if (total === 0) return null;
  // Build compact page window: [1] … [p-1] [p] [p+1] … [last]
  const pages = [];
  const push = (n) => { if (!pages.includes(n) && n >= 1 && n <= totalPages) pages.push(n); };
  push(1);
  for (let n = page - 1; n <= page + 1; n++) push(n);
  push(totalPages);
  pages.sort((a, b) => a - b);
  const withEllipsis = [];
  pages.forEach((n, i) => {
    if (i > 0 && n - pages[i - 1] > 1) withEllipsis.push("…");
    withEllipsis.push(n);
  });
  return <div className="pagination-bar" data-testid={testid}>
    <span className="pg-info">Menampilkan <b>{start}-{end}</b> dari <b>{total}</b> {label}</span>
    <div className="pg-controls">
      <button className="pg-btn" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid={`${testid}-prev`}>‹ Sebelumnya</button>
      {withEllipsis.map((n, i) => n === "…"
        ? <span key={`e-${i}`} className="pg-ellipsis">…</span>
        : <button key={n} className={`pg-num ${n === page ? "active" : ""}`} onClick={() => setPage(n)} data-testid={`${testid}-page-${n}`}>{n}</button>
      )}
      <button className="pg-btn" disabled={page >= totalPages} onClick={() => setPage(page + 1)} data-testid={`${testid}-next`}>Selanjutnya ›</button>
    </div>
  </div>;
}

// -------- POS --------
function POS({ products, query, setQuery, category, setCategory, cart, addToCart, adjustCart, subtotal, tax, total, taxConfig, onPay, shift, role, onlineOrders, openOnline, openHistory }) {
  const locked = role === "Kasir" && !shift;
  const [variantPick, setVariantPick] = useState(null); // { product }
  const pg = usePagination(products, [query, category, products.length]);
  const handleProductClick = (p) => {
    const active = (p.variants || []).filter((v) => v.active !== false);
    if (active.length > 0) setVariantPick(p);
    else addToCart(p);
  };
  return <>
    <SectionHeader eyebrow={shift ? `SHIFT AKTIF · Kas awal ${money(shift.opening_cash)}` : "TERMINAL KASIR"} title="Pesanan baru"
      description="Pilih menu, atur jumlah, lalu selesaikan pembayaran."
      action={<div className="pos-actions">
        <button className="online-btn" onClick={openHistory} data-testid="history-button" disabled={locked}><FileText size={15} /> History Kasir</button>
        <button className={`online-btn ${(onlineOrders?.length || 0) > 0 ? "has-new" : ""}`} onClick={openOnline} disabled={locked} data-testid="online-orders-button">
          <QrCode size={15} /> Pesanan Online
          {(onlineOrders?.length || 0) > 0 && <span className="badge">{onlineOrders.length}</span>}
        </button>
        <div className="live-pill"><i /> Terminal online</div>
      </div>} />
    {locked && <div className="warn-banner" data-testid="pos-shift-warning">🔒 Terminal terkunci. Buka Shift di sidebar untuk mulai bertransaksi.</div>}
    <div className={`pos-layout ${locked ? "locked" : ""}`} data-testid="pos-layout">
      <section className="menu-area">
        <div className="menu-tools">
          <div className="search-box"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari menu atau scan barcode..." disabled={locked} data-testid="pos-product-search" /></div>
          <div className="category-tabs">{["Semua", "Kopi", "Makanan", "Snack", "Non-Kopi"].map((c) => <button className={category === c ? "selected" : ""} key={c} onClick={() => setCategory(c)} disabled={locked} data-testid={`category-${c.toLowerCase()}`}>{c}</button>)}</div>
        </div>
        <div className="menu-scroll" data-testid="pos-menu-scroll">
          <div className="product-grid" data-testid="pos-product-grid">
            {pg.total === 0 && <div className="empty-vendor" style={{ gridColumn: "1/-1" }} data-testid="pos-empty-menu"><Search size={26}/><b>Tidak ada menu</b><span>Ubah pencarian atau kategori</span></div>}
            {pg.pageItems.map((p) => <button className="product-card" key={p.id} onClick={() => handleProductClick(p)} disabled={locked} data-testid={`product-card-${p.id}`}>
              <div className="product-art" style={{ background: p.color }}>{p.image_url ? <img src={p.image_url} alt={p.name} className="product-img" /> : <Coffee size={30} />}<span>{p.stock} stok</span></div>
              <div className="product-info"><b>{p.name}</b><span>{p.vendor}{(p.variants||[]).filter(v=>v.active!==false).length>0 && ` · ${(p.variants||[]).filter(v=>v.active!==false).length} varian`}</span><strong>{money(p.price)}</strong></div>
              <div className="add-product"><Plus size={17} /></div>
            </button>)}
          </div>
          <PaginationBar {...pg} label="menu" testid="pos-pagination" />
        </div>
      </section>
      <aside className="cart-panel">
        <div className="cart-head">
          <div><h2>Keranjang</h2><span data-testid="cart-item-count">{cart.reduce((a, i) => a + i.qty, 0)} item · Meja 07</span></div>
          <button className="clear-btn" onClick={() => cart.forEach((i) => adjustCart(i.key, -i.qty))} data-testid="clear-cart-button">Bersihkan</button>
        </div>
        <div className="cart-items">
          {cart.length ? cart.map((item) => <div className="cart-item pro" key={item.key} data-testid={`cart-line-${item.key}`}>
            <div className="mini-art" style={{ background: item.color }}>{item.image_url ? <img src={item.image_url} alt="" /> : <Coffee size={16} />}</div>
            <div className="cart-body">
              <div className="cart-title"><b>{item.name}</b>{item.variant_name && <em className="var-chip">{item.variant_name}</em>}</div>
              {item.notes && <div className="cart-notes">📝 {item.notes}</div>}
              <div className="cart-price-row"><span>{money(item.price)} × {item.qty}</span><strong>{money(item.price * item.qty)}</strong></div>
              <div className="qty">
                <button onClick={() => adjustCart(item.key, -1)} data-testid={`decrease-${item.key}`}>−</button>
                <strong>{item.qty}</strong>
                <button onClick={() => adjustCart(item.key, 1)} data-testid={`increase-${item.key}`}>+</button>
              </div>
            </div>
          </div>) : <div className="empty-cart"><ShoppingCart size={26} /><b>Keranjang masih kosong</b><span>Pilih menu untuk memulai pesanan</span></div>}
        </div>
        <div className="cart-summary">
          <div><span>Subtotal ({cart.reduce((a, i) => a + i.qty, 0)} item)</span><b>{money(subtotal)}</b></div>
          {taxConfig?.enabled && taxConfig.percent > 0 && <div data-testid="cart-tax-row"><span>PPN ({taxConfig.percent}%)</span><b>{money(tax)}</b></div>}
          <div className="total-line"><span>Total pembayaran</span><strong>{money(total)}</strong></div>
          <button className="pay-btn" disabled={!cart.length} onClick={onPay} data-testid="pay-order-button"><CreditCard size={17} /> Bayar sekarang <span>→</span></button>
          <button className="manual-btn" data-testid="manual-order-button"><Plus size={15} /> Tambah item manual</button>
        </div>
      </aside>
    </div>
    {variantPick && <VariantPickerModal product={variantPick} onClose={() => setVariantPick(null)} onAdd={(variant, notes) => { addToCart(variantPick, variant, notes); setVariantPick(null); }} />}
  </>;
}

function VariantPickerModal({ product, onClose, onAdd }) {
  const [pick, setPick] = useState((product.variants || []).find((v) => v.active !== false));
  const [notes, setNotes] = useState("");
  return <div className="modal-backdrop">
    <div className="pay-modal" data-testid="variant-picker-modal">
      <button className="modal-close" onClick={onClose}><X size={18}/></button>
      <div className="pay-head"><h2>{product.name}</h2><span>Pilih varian & catatan khusus</span></div>
      <div className="variant-picks">
        {(product.variants || []).filter(v => v.active !== false).map((v) => (
          <button key={v.id} className={`var-pick ${pick?.id === v.id ? "active" : ""}`} onClick={() => setPick(v)} data-testid={`pick-variant-${v.id}`}>
            <b>{v.name}</b><strong>{money(v.price)}</strong>
          </button>
        ))}
      </div>
      <div className="pay-body">
        <label>Catatan Khusus (opsional)</label>
        <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Less sugar / Tanpa es / Extra hot" data-testid="variant-notes-input" />
      </div>
      <button className="primary-btn full" disabled={!pick} onClick={() => onAdd(pick, notes)} data-testid="add-variant-to-cart"><Plus size={15}/> Tambahkan ke Keranjang · {money(pick?.price || 0)}</button>
    </div>
  </div>;
}

// -------- Payment Modal (multi-channel) --------
function PaymentModal({ total, onClose, onConfirm }) {
  const [method, setMethod] = useState("Cash");
  const [cash, setCash] = useState(total);
  const [ref, setRef] = useState("");
  const [proofData, setProofData] = useState("");
  const [qrisCode, setQrisCode] = useState("");
  useEffect(() => { axios.get(`${API}/settings/qris:outlet-sudirman`).then(({ data }) => setQrisCode(data?.qris_code || "")).catch(() => {}); }, []);
  const change = Math.max(0, Number(cash) - total);
  const canPay = method === "Cash" ? Number(cash) >= total : method === "Transfer" ? ref.length > 3 : (ref.length > 3 || proofData);
  const qrPayload = qrisCode || `MJDKUPI|AMOUNT:${total}|TS:${Date.now()}`;
  const handleFile = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => setProofData(r.result); r.readAsDataURL(f); };
  return <div className="modal-backdrop">
    <div className="pay-modal" data-testid="payment-modal">
      <button className="modal-close" onClick={onClose} data-testid="close-payment-button"><X size={18} /></button>
      <div className="pay-head"><h2>Pilih metode pembayaran</h2><span>Total tagihan</span><strong>{money(total)}</strong></div>
      <div className="pay-tabs">
        {[["Cash", DollarSign], ["Transfer", CreditCard], ["QRIS", QrCode]].map(([m, Icon]) => (
          <button key={m} className={method === m ? "active" : ""} onClick={() => setMethod(m)} data-testid={`method-${m.toLowerCase()}`}>
            <Icon size={17} />{m}
          </button>
        ))}
      </div>
      {method === "Cash" && <div className="pay-body">
        <label>Nominal diterima</label>
        <input type="number" value={cash} onChange={(e) => setCash(e.target.value)} onFocus={numOnFocus} data-testid="cash-received-input" />
        <div className="quick-cash">{[50000, 100000, 200000, total].map((v) => <button key={v} onClick={() => setCash(v)} data-testid={`quick-cash-${v}`}>{money(v)}</button>)}</div>
        <div className="change-line"><span>Kembalian</span><strong>{money(change)}</strong></div>
      </div>}
      {method === "Transfer" && <div className="pay-body">
        <label>Nomor referensi / rekening pengirim</label>
        <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Contoh: BCA-4823" data-testid="transfer-ref-input" />
        <div className="hint">Rekening MJD Kupi · BCA 4823-0011 a.n. MJD Kupi. Konfirmasi transfer sebelum menyelesaikan.</div>
      </div>}
      {method === "QRIS" && <div className="pay-body qris-body">
        <div className="qris-real" data-testid="qris-real"><QRCodeSVG value={qrPayload} size={180} bgColor="#ffffff" fgColor="#111827" level="M" includeMargin={true} /></div>
        <div className="hint">Scan QRIS di atas dengan m-banking / e-wallet untuk membayar {money(total)}.</div>
        <label>Nomor referensi (opsional)</label>
        <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="ID transaksi QRIS" data-testid="qris-ref-input" />
        <label>Upload bukti pembayaran</label>
        <input type="file" accept="image/*" onChange={handleFile} data-testid="qris-proof-input" />
        {proofData && <div className="proof-thumb"><img src={proofData} alt="Bukti" /><Check size={16} color="#059669" /></div>}
      </div>}
      <button className="primary-btn full" disabled={!canPay} onClick={() => onConfirm({ method, reference: ref || proofData.slice(0, 60), cashReceived: cash })} data-testid="confirm-payment-button">Konfirmasi pembayaran <span>→</span></button>
    </div>
  </div>;
}

// -------- Receipt Modal (with WA share + printer) --------
function ReceiptModal({ sale, merchants, outlets, cashier, onClose, notify }) {
  const [printing, setPrinting] = useState(false);
  const outlet = outlets?.find((o) => o.id === (sale.outlet_id || "outlet-sudirman")) || { name: "MJD Kupi", address: "", phone: "" };
  const grouped = useMemo(() => {
    const g = {};
    (sale.lines || []).forEach((ln) => {
      const key = ln.merchant_id || ln.vendor || "MJD Kupi";
      if (!g[key]) g[key] = { name: ln.vendor || "MJD Kupi", phone: merchants.find((m) => m.id === ln.merchant_id)?.phone, lines: [] };
      g[key].lines.push(ln);
    });
    return g;
  }, [sale, merchants]);

  const shareWA = (name, phone, lines) => {
    const body = `🔔 [PESANAN BARU - MJD KUPI]\n${sale.table || sale.table_no} | Order: #${String(sale.id).slice(-6)}\n` +
      lines.map((l) => `${l.quantity}× ${l.name}`).join("\n") +
      `\nTotal: ${money(lines.reduce((s, l) => s + l.price * l.quantity, 0))} | Status: DIBAYAR`;
    const url = phone ? `https://wa.me/${phone}?text=${encodeURIComponent(body)}` : `https://wa.me/?text=${encodeURIComponent(body)}`;
    window.open(url, "_blank");
    notify(`WhatsApp ke ${name} disiapkan`);
  };

  const printThermal = async () => {
    setPrinting(true);
    try {
      const width = 32; // 58mm default
      const salePayload = buildSaleReceipt({ outlet, sale, cashier: cashier || "-", width });
      await directPrint(salePayload);
      // Also print one kitchen ticket per merchant
      for (const [_, g] of Object.entries(grouped)) {
        const kb = buildKitchenTicket({ outlet, ticket: { source_id: sale.id, table_no: sale.table || sale.table_no, merchant_name: g.name, lines: g.lines }, width });
        await directPrint(kb);
      }
      notify("Struk tercetak langsung ke printer thermal");
    } catch (e) {
      notify(e.message || "Gagal cetak. Sambungkan printer di menu Pengaturan.");
    } finally {
      setPrinting(false);
    }
  };

  return <div className="modal-backdrop">
    <div className="receipt-modal wide" data-testid="receipt-modal">
      <button className="modal-close" onClick={onClose} data-testid="close-receipt-button"><X size={18} /></button>
      <div className="receipt-logo"><Coffee size={17} /></div>
      <h2>{outlet.name}</h2>
      <span>Struk #{String(sale.id).slice(-6)} · {sale.payment_method}</span>
      <div className="receipt-items">{(sale.lines || []).map((i, idx) => <div key={idx}><span>{i.quantity}× {i.name}</span><b>{money(i.price * i.quantity)}</b></div>)}</div>
      <div className="receipt-total"><span>Total dibayar</span><strong>{money(sale.total)}</strong></div>
      {sale.payment_method === "Cash" && sale.cash_received > 0 && <div className="receipt-total"><span>Kembalian</span><strong>{money(sale.change_amount)}</strong></div>}
      <div className="receipt-status">✓ Pembayaran berhasil · Tiket dapur terkirim</div>
      <div className="split-tickets">
        <b>Kirim tiket dapur per merchant</b>
        {Object.entries(grouped).map(([k, g]) => (
          <div className="ticket-row" key={k}>
            <span><ChefHat size={13} /> {g.name} · {g.lines.length} item</span>
            <button className="small-action" data-testid={`wa-share-${k}`} onClick={() => shareWA(g.name, g.phone, g.lines)}><MessageCircle size={12} /> WhatsApp</button>
          </div>
        ))}
      </div>
      <div className="split-actions">
        <button className="outline-btn" disabled={printing} onClick={printThermal} data-testid="print-thermal-button"><Printer size={14} /> {printing ? "Mencetak..." : "Cetak Thermal"}</button>
        <button className="primary-btn" onClick={onClose} data-testid="finish-receipt-button">Selesai</button>
      </div>
    </div>
  </div>;
}

// -------- KDS (Kitchen Display) --------
function KDS({ notify, merchants }) {
  const [orders, setOrders] = useState([]);
  const [tick, setTick] = useState(0);
  const [soundOn, setSoundOn] = useState(true);
  const [filter, setFilter] = useState("all");
  const prevIdsRef = useRef(new Set());
  const audioRef = useRef(null);

  useEffect(() => {
    // simple beep synthesized via WebAudio
    audioRef.current = () => {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = "sine"; o.frequency.value = 880;
        g.gain.value = 0.15;
        o.connect(g).connect(ctx.destination);
        o.start();
        setTimeout(() => { o.frequency.value = 660; }, 120);
        setTimeout(() => { o.stop(); ctx.close(); }, 300);
      } catch {}
    };
  }, []);

  const load = async () => {
    try {
      const { data } = await axios.get(`${API}/kds/orders`);
      const newIds = new Set(data.map((o) => o.id));
      const prev = prevIdsRef.current;
      const isFresh = prev.size > 0 && [...newIds].some((id) => !prev.has(id));
      if (isFresh && soundOn && audioRef.current) audioRef.current();
      prevIdsRef.current = newIds;
      setOrders(data);
    } catch {}
  };
  useEffect(() => { load(); const t = setInterval(load, 3000); const c = setInterval(() => setTick((v) => v + 1), 1000); return () => { clearInterval(t); clearInterval(c); }; }, [soundOn]);

  const setStatus = async (id, status) => {
    await axios.patch(`${API}/kds/orders/${id}`, { status });
    notify(`Status: ${status}`);
    load();
  };

  const now = Date.now();
  const slaClass = (start) => {
    const mins = (now - new Date(start).getTime()) / 60000;
    if (mins > 15) return "red";
    if (mins > 10) return "yellow";
    return "green";
  };
  const slaLabel = (start) => {
    const mins = (now - new Date(start).getTime()) / 60000;
    const m = Math.floor(mins);
    const s = Math.floor((mins - m) * 60);
    return `${m}m ${s}s`;
  };

  const filtered = filter === "all" ? orders : orders.filter((o) => o.merchant_id === filter);

  return <>
    <SectionHeader eyebrow="LIVE KITCHEN DISPLAY" title="Antrean dapur real-time" description="SLA hijau <10m · kuning 10–15m · merah >15m. Chime otomatis saat pesanan baru."
      action={<div className="kds-controls">
        <select value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="kds-filter">
          <option value="all">Semua merchant</option>
          {merchants.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <button className={`outline-btn ${soundOn ? "on" : ""}`} onClick={() => setSoundOn((v) => !v)} data-testid="kds-sound-toggle"><Volume2 size={14} /> {soundOn ? "Suara ON" : "Suara OFF"}</button>
      </div>} />
    <div className="kds-grid">
      {filtered.length === 0 && <div className="empty-vendor kds-empty"><ChefHat size={30} /><b>Antrean masih kosong</b><span>Tunggu order baru</span></div>}
      {filtered.map((o) => (
        <div key={o.id} className={`kds-card ${slaClass(o.sla_start)}`} data-testid={`kds-ticket-${o.id}`}>
          <div className="kds-head">
            <div><b>#{String(o.id).slice(-5)} · {o.table_no}</b><span>{o.merchant_name}</span></div>
            <div className="sla" title="SLA"><Timer size={13} /> {slaLabel(o.sla_start)}</div>
          </div>
          <ul className="kds-lines">{(o.lines || []).map((ln, i) => <li key={i}><b>{ln.quantity}×</b> {ln.name}</li>)}</ul>
          <div className="kds-actions">
            {o.status === "Diproses" && <button className="primary-btn full" onClick={() => setStatus(o.id, "Siap diambil")} data-testid={`kds-ready-${o.id}`}>Tandai siap</button>}
            {o.status === "Siap diambil" && <button className="primary-btn full green" onClick={() => setStatus(o.id, "Selesai")} data-testid={`kds-done-${o.id}`}>Selesai</button>}
            <span className={`status-badge ${o.status.toLowerCase().replaceAll(" ", "-")}`}>{o.status}</span>
          </div>
        </div>
      ))}
    </div>
  </>;
}

// -------- Inventory --------
function Inventory({ products, reload, notify }) {
  const [showIn, setShowIn] = useState(false);
  const [showOpname, setShowOpname] = useState(false);
  const [showOut, setShowOut] = useState(false);
  const [tab, setTab] = useState("stock"); // stock | movements | excel
  const [movements, setMovements] = useState([]);
  const [mvFilter, setMvFilter] = useState({ product_id: "", kind: "" });
  const [loadingMv, setLoadingMv] = useState(false);
  const doAdjust = async (id, quantity, kind, reason) => { await axios.patch(`${API}/products/${id}/stock`, { quantity, kind, reason, note: "" }); reload(); };

  const loadMovements = async () => {
    setLoadingMv(true);
    try {
      const params = new URLSearchParams();
      if (mvFilter.product_id) params.set("product_id", mvFilter.product_id);
      if (mvFilter.kind) params.set("kind", mvFilter.kind);
      const { data } = await axios.get(`${API}/inventory/stock-movements?${params.toString()}`);
      setMovements(data || []);
    } catch (e) { notify("Gagal memuat mutasi stok"); }
    setLoadingMv(false);
  };
  useEffect(() => { if (tab === "movements") loadMovements(); /* eslint-disable-next-line */ }, [tab, mvFilter.product_id, mvFilter.kind]);

  // Excel Export
  const exportExcel = () => {
    const rows = products.map((p) => ({
      id: p.id, name: p.name, category: p.category, vendor: p.vendor,
      merchant_id: p.merchant_id || "", outlet_id: p.outlet_id || "outlet-sudirman",
      price: p.price, cost: p.cost, stock: p.stock, color: p.color || "#ffedd5",
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Produk");
    XLSX.writeFile(wb, `mjd-produk-${new Date().toISOString().slice(0,10)}.xlsx`);
    notify(`${rows.length} produk diekspor ke Excel`);
  };
  const downloadTemplate = () => {
    const ws = XLSX.utils.json_to_sheet([{ id: "", name: "Contoh Kopi Susu", category: "Kopi", vendor: "Barista Kopi", merchant_id: "m-barista", outlet_id: "outlet-sudirman", price: 25000, cost: 12000, stock: 50, color: "#ffedd5" }]);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Template");
    XLSX.writeFile(wb, "mjd-template-import-produk.xlsx");
    notify("Template diunduh");
  };
  const handleImport = async (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    try {
      const buf = await f.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array" });
      const rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]]);
      if (!rows.length) return notify("File Excel kosong");
      const payload = rows.map((r) => ({
        id: r.id || null,
        name: String(r.name || r.Nama || "").trim(),
        category: String(r.category || r.Kategori || "Lain-lain"),
        vendor: String(r.vendor || r.Vendor || "MJD Kupi"),
        merchant_id: r.merchant_id || null,
        outlet_id: r.outlet_id || "outlet-sudirman",
        price: Number(r.price || r.Harga || 0),
        cost: Number(r.cost || r.HPP || 0),
        stock: Number(r.stock || r.Stok || 0),
        color: r.color || "#ffedd5",
      }));
      const { data } = await axios.post(`${API}/products/bulk-import`, { rows: payload, mode: "upsert" });
      notify(`Import: ${data.created} baru, ${data.updated} diperbarui, ${data.errors?.length || 0} error`);
      reload();
    } catch (err) {
      notify(err.response?.data?.detail || "Gagal mengimpor file Excel");
    }
    e.target.value = "";
  };

  const kindLabel = { in: "Masuk", out: "Keluar", opname: "Opname", sale: "Penjualan", adjust: "Adjust", initial: "Awal" };
  const kindTone = { in: "green", out: "red", sale: "red", opname: "blue", adjust: "orange", initial: "orange" };
  const productMap = useMemo(() => Object.fromEntries(products.map((p) => [p.id, p])), [products]);

  return <>
    <SectionHeader eyebrow="STOCK ENGINE" title="Inventori & stok" description="Kelola barang masuk, keluar, mutasi audit, dan import massal via Excel."
      action={<div className="row-gap">
        <button className="outline-btn" onClick={() => setShowOut(true)} data-testid="stock-out-button"><Trash2 size={14} /> Barang keluar</button>
        <button className="outline-btn" onClick={() => setShowOpname(true)} data-testid="stock-opname-button">Stock opname</button>
        <button className="primary-btn" data-testid="stock-in-button" onClick={() => setShowIn(true)}><Plus size={16} /> Barang masuk</button>
      </div>} />
    <div className="ft-tabs" style={{ marginBottom: 12 }}>
      <button className={tab === "stock" ? "active" : ""} onClick={() => setTab("stock")} data-testid="inventory-tab-stock"><Package size={14} /> Ringkasan Stok</button>
      <button className={tab === "movements" ? "active" : ""} onClick={() => setTab("movements")} data-testid="inventory-tab-movements"><ArrowRightLeft size={14} /> Mutasi Stok</button>
      <button className={tab === "excel" ? "active" : ""} onClick={() => setTab("excel")} data-testid="inventory-tab-excel"><FileSpreadsheet size={14} /> Import / Export Excel</button>
    </div>
    {tab === "stock" && <>
      <div className="metric-grid three">
        <Metric label="Total unit" value={products.reduce((a, p) => a + p.stock, 0)} change={`${products.length} produk aktif`} tone="orange" icon={Package} />
        <Metric label="Stok menipis" value={products.filter((p) => p.stock < 15).length} change="Perlu restock" tone="red" icon={Bell} />
        <Metric label="Nilai persediaan" value={money(products.reduce((a, p) => a + p.stock * p.cost, 0))} change="HPP × stok" tone="green" icon={BarChart3} />
      </div>
      <section className="panel table-panel">
        <div className="panel-head"><div><h2>Ringkasan stok produk</h2><span>Sync Supabase</span></div></div>
        <div className="data-table">
          <div className="table-row table-label"><span>Produk</span><span>Vendor</span><span>HPP</span><span>Stok</span><span>Status</span><span /></div>
          {products.map((p) => <div className="table-row" key={p.id}>
            <span className="table-product"><div className="product-dot" style={{ background: p.color }}><Coffee size={14} /></div><b>{p.name}</b></span>
            <span>{p.vendor}</span><span>{money(p.cost)}</span><span><b>{p.stock}</b> unit</span>
            <span><i className={`status-dot ${p.stock < 15 ? "low" : "good"}`} />{p.stock < 15 ? "Menipis" : "Aman"}</span>
            <button className="small-action" onClick={() => { doAdjust(p.id, 10, "in", "Restock"); notify("+10 unit"); }} data-testid={`restock-${p.id}`}><Plus size={14} /> +10</button>
          </div>)}
        </div>
      </section>
    </>}
    {tab === "movements" && <>
      <section className="panel">
        <div className="panel-head">
          <div><h2>Mutasi stok (Audit Trail)</h2><span>Setiap perubahan stok terekam otomatis — {movements.length} entri</span></div>
          <div className="row-gap">
            <select value={mvFilter.kind} onChange={(e) => setMvFilter({ ...mvFilter, kind: e.target.value })} data-testid="mv-kind-filter">
              <option value="">Semua Jenis</option>
              <option value="in">Barang Masuk</option>
              <option value="out">Barang Keluar</option>
              <option value="sale">Penjualan</option>
              <option value="opname">Opname</option>
              <option value="adjust">Adjust</option>
            </select>
            <select value={mvFilter.product_id} onChange={(e) => setMvFilter({ ...mvFilter, product_id: e.target.value })} data-testid="mv-product-filter">
              <option value="">Semua Produk</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button className="outline-btn" onClick={loadMovements} data-testid="mv-reload"><RefreshCw size={14} /> Muat</button>
          </div>
        </div>
        <div className="data-table" data-testid="stock-movements-table">
          <div className="table-row table-label"><span>Waktu</span><span>Produk</span><span>Jenis</span><span>Perubahan</span><span>Sebelum → Sesudah</span><span>Operator / Alasan</span></div>
          {loadingMv && <div className="empty-vendor"><b>Memuat…</b></div>}
          {!loadingMv && !movements.length && <div className="empty-vendor" data-testid="mv-empty"><Package size={30} /><b>Belum ada mutasi</b><span>Lakukan transaksi POS atau adjust stok untuk mulai mencatat</span></div>}
          {movements.map((m) => {
            const p = productMap[m.product_id];
            const t = kindTone[m.kind] || "orange";
            const Icon = m.delta >= 0 ? TrendingUp : TrendingDown;
            return <div className="table-row" key={m.id} data-testid={`mv-row-${m.id}`}>
              <span><small>{new Date(m.created_at).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</small></span>
              <span><b>{p?.name || m.product_id.slice(0, 8)}</b></span>
              <span><span className="method-badge" style={{ background: t === "green" ? "#dcfce7" : t === "red" ? "#fee2e2" : t === "blue" ? "#dbeafe" : "#ffedd5" }}>{kindLabel[m.kind] || m.kind}</span></span>
              <span style={{ color: m.delta >= 0 ? "#059669" : "#dc2626", fontWeight: 700 }}><Icon size={13} /> {m.delta > 0 ? `+${m.delta}` : m.delta}</span>
              <span><b>{m.stock_before}</b> → <b>{m.stock_after}</b></span>
              <span><small>{m.operator_name || "-"} · {m.reason}</small></span>
            </div>;
          })}
        </div>
      </section>
    </>}
    {tab === "excel" && <>
      <section className="panel product-form-v2">
        <div className="form-heading"><div className="form-icon"><FileSpreadsheet size={18} /></div>
          <div><h2>Import & Export Produk (Excel)</h2><span>Kelola katalog dalam jumlah besar. Format .xlsx / .xls / .csv</span></div>
        </div>
        <div className="excel-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div className="excel-card" style={{ padding: 20, border: "1px dashed #e5e7eb", borderRadius: 12 }}>
            <h3 style={{ margin: 0, fontSize: 15 }}><Upload size={16} style={{ verticalAlign: "middle" }} /> Import dari Excel</h3>
            <p style={{ fontSize: 13, color: "#6b7280", margin: "8px 0 16px" }}>Kolom yang didukung: <b>id</b>, <b>name</b>, <b>category</b>, <b>vendor</b>, <b>merchant_id</b>, <b>outlet_id</b>, <b>price</b>, <b>cost</b>, <b>stock</b>, <b>color</b>. Mode <b>upsert</b> — produk dengan nama sama pada outlet yang sama akan di-update.</p>
            <div className="row-gap">
              <button className="outline-btn" onClick={downloadTemplate} data-testid="download-template-btn"><Download size={14} /> Unduh Template</button>
              <label className="primary-btn" data-testid="upload-excel-label">
                <Upload size={14} /> Pilih File Excel
                <input type="file" accept=".xlsx,.xls,.csv" onChange={handleImport} style={{ display: "none" }} data-testid="upload-excel-input" />
              </label>
            </div>
          </div>
          <div className="excel-card" style={{ padding: 20, border: "1px dashed #e5e7eb", borderRadius: 12 }}>
            <h3 style={{ margin: 0, fontSize: 15 }}><Download size={16} style={{ verticalAlign: "middle" }} /> Export ke Excel</h3>
            <p style={{ fontSize: 13, color: "#6b7280", margin: "8px 0 16px" }}>Unduh seluruh katalog produk aktif ({products.length} produk) sebagai file .xlsx — termasuk stok terkini & HPP.</p>
            <button className="primary-btn" onClick={exportExcel} data-testid="export-excel-btn"><FileSpreadsheet size={14} /> Export {products.length} Produk</button>
          </div>
        </div>
      </section>
    </>}
    {showIn && <StockModal title="Barang masuk (Restock)" products={products} kind="in" onClose={() => setShowIn(false)} onSubmit={(pid, qty, note) => { doAdjust(pid, qty, "in", note || "Restock"); setShowIn(false); notify("Stok masuk tercatat"); }} />}
    {showOut && <StockModal title="Barang keluar / rusak" products={products} kind="out" onClose={() => setShowOut(false)} onSubmit={(pid, qty, note) => { doAdjust(pid, -Math.abs(qty), "out", note || "Basi/Rusak"); setShowOut(false); notify("Stok keluar tercatat"); }} />}
    {showOpname && <StockModal title="Stock opname (Audit)" products={products} kind="opname" onClose={() => setShowOpname(false)} onSubmit={(pid, qty, note) => { doAdjust(pid, qty, "opname", note || "Adjust opname"); setShowOpname(false); notify("Stok disesuaikan"); }} />}
  </>;
}
function StockModal({ title, products, kind, onClose, onSubmit }) {
  const [pid, setPid] = useState(products[0]?.id || "");
  const [qty, setQty] = useState("");
  const [note, setNote] = useState("");
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => products.filter((p) => p.name.toLowerCase().includes(search.toLowerCase())), [products, search]);
  useEffect(() => { if (filtered.length && !filtered.find((p) => p.id === pid)) setPid(filtered[0].id); }, [filtered]);
  const submit = () => { const n = Number(qty); if (!n && kind !== "opname") return; onSubmit(pid, n || 0, note); };
  return <div className="modal-backdrop"><div className="pay-modal" data-testid="stock-modal">
    <button className="modal-close" onClick={onClose}><X size={18} /></button>
    <div className="pay-head"><h2>{title}</h2><span>Riwayat tersimpan otomatis</span></div>
    <div className="pay-body">
      <label>Cari produk</label>
      <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama produk..." data-testid="stock-search-input" />
      <label>Produk</label>
      <select value={pid} onChange={(e) => setPid(e.target.value)} data-testid="stock-product-select">{filtered.map((p) => <option key={p.id} value={p.id}>{p.name} (stok {p.stock})</option>)}</select>
      <label>{kind === "opname" ? "Stok fisik aktual" : "Jumlah"}</label>
      <input type="number" value={qty} onChange={(e) => setQty(e.target.value)} onFocus={numOnFocus} placeholder="Masukkan angka" data-testid="stock-qty-input" />
      <label>Catatan</label>
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Nomor nota / alasan" data-testid="stock-note-input" />
    </div>
    <button className="primary-btn full" onClick={submit} data-testid="stock-submit-button">Simpan</button>
  </div></div>;
}

// -------- Expenses --------
function Expenses({ expenses, reload, notify, session, shift }) {
  const [showAdd, setShowAdd] = useState(false);
  return <>
    <SectionHeader eyebrow="CASH CONTROL" title="Buku pengeluaran" description="Catat dan pantau seluruh biaya operasional outlet."
      action={<button className="primary-btn" data-testid="add-expense-button" onClick={() => setShowAdd(true)}><Plus size={16} /> Catat pengeluaran</button>} />
    <div className="expense-summary">
      <div><span>Total tercatat</span><strong>{money(expenses.reduce((a, e) => a + e.amount, 0))}</strong><small>Sync ke Supabase</small></div>
      <div className="expense-bars"><span style={{ height: "72%" }} /><span style={{ height: "45%" }} /><span style={{ height: "85%" }} /><span style={{ height: "58%" }} /><span style={{ height: "66%" }} /><span style={{ height: "38%" }} /><span style={{ height: "55%" }} /></div>
    </div>
    <section className="panel table-panel">
      <div className="panel-head"><div><h2>Transaksi pengeluaran</h2><span>{expenses.length} entri</span></div></div>
      <div className="data-table">
        <div className="table-row table-label"><span>Kategori</span><span>Keterangan</span><span>Tanggal</span><span>Metode</span><span>Nominal</span><span /></div>
        {expenses.map((e) => <div className="table-row" key={e.id}><span><b>{e.category}</b></span><span>{e.note}</span><span>{e.date}</span><span><span className="method-badge">{e.method}</span></span><span><b>{money(e.amount)}</b></span><button className="more-btn" data-testid={`expense-menu-${e.id}`}>•••</button></div>)}
      </div>
    </section>
    {showAdd && <ExpenseModal onClose={() => setShowAdd(false)} onSaved={() => { reload(); notify("Pengeluaran tersimpan"); }} session={session} shift={shift} />}
  </>;
}
function ExpenseModal({ onClose, onSaved, session, shift }) {
  const [form, setForm] = useState({ category: "Pembelian Bahan Baku", note: "", amount: "", date: new Date().toISOString().slice(0, 10), method: "Cash" });
  const save = async () => {
    const amt = Number(form.amount);
    if (!amt) return alert("Nominal wajib diisi");
    await axios.post(`${API}/expenses`, { ...form, amount: amt });
    onSaved(); onClose();
  };
  return <div className="modal-backdrop"><div className="pay-modal" data-testid="expense-modal">
    <button className="modal-close" onClick={onClose}><X size={18} /></button>
    <div className="pay-head"><h2>Catat pengeluaran</h2><span>Otomatis masuk P&L</span></div>
    <div className="pay-body">
      {session && <div className="bind-info" data-testid="expense-bind-info">
        <b>Pencatat</b> <span>{session.name} ({session.role})</span>
        {shift && <><b>Shift ID</b><span className="mono">{String(shift.id).slice(-8).toUpperCase()}</span></>}
      </div>}
      <label>Kategori</label>
      <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="expense-category-select">
        {["Sewa Tempat", "Gaji Karyawan", "Listrik & Air", "Pembelian Bahan Baku", "Transportasi/Kurir", "Maintenance", "Lain-Lain"].map((c) => <option key={c}>{c}</option>)}
      </select>
      <label>Keterangan</label>
      <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} data-testid="expense-note-input" />
      <label>Nominal (Rp)</label>
      <input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} onFocus={numOnFocus} placeholder="Masukkan nominal" data-testid="expense-amount-input" />
      <label>Tanggal</label>
      <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} data-testid="expense-date-input" />
      <label>Metode</label>
      <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })} data-testid="expense-method-select"><option>Cash</option><option>Transfer</option></select>
    </div>
    <button className="primary-btn full" onClick={save} data-testid="expense-save-button">Simpan</button>
  </div></div>;
}

// -------- Products --------
function Products({ products, merchants, outlets = [], session, reload, notify }) {
  const [form, setForm] = useState({ name: "", category: "Kopi", merchant_id: merchants[0]?.id || "", price: "", cost: "", stock: "", sku: "", is_active: true, is_global: false, outlet_id: session?.outlet_id || "", color: "#ffedd5", image_url: "", variants: [] });
  const [editProduct, setEditProduct] = useState(null);
  const [showImport, setShowImport] = useState(false);
  const [search, setSearch] = useState("");
  const [filterCat, setFilterCat] = useState("Semua");
  const [filterMerchant, setFilterMerchant] = useState("Semua");
  const [statusTab, setStatusTab] = useState("all"); // all | active | inactive
  useEffect(() => { if (!form.merchant_id && merchants.length) setForm((f) => ({ ...f, merchant_id: merchants[0].id })); }, [merchants]);

  const save = async () => {
    if (!form.name) return notify("Nama produk wajib diisi");
    const vendor = merchants.find((m) => m.id === form.merchant_id)?.name || "MJD Kupi";
    const outlet_id = form.is_global ? null : (form.outlet_id || session?.outlet_id || null);
    if (!form.is_global && !outlet_id) return notify("Pilih outlet target atau tandai 'Berlaku di semua outlet'");
    try {
      await axios.post(`${API}/products`, { ...form, outlet_id, vendor, price: Number(form.price) || 0, cost: Number(form.cost) || 0, stock: Number(form.stock) || 0, variants: form.variants || [] });
      setForm({ ...form, name: "", price: "", cost: "", stock: "", sku: "", image_url: "", variants: [] });
      reload();
      notify(`✅ Produk ${form.name} tersimpan ${form.is_global ? "(Berlaku di semua outlet)" : ""}`);
    } catch (e) { notify(`❌ ${e.response?.data?.detail || "Gagal simpan produk"}`); }
  };
  const handleImage = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => setForm({ ...form, image_url: r.result }); r.readAsDataURL(f); };
  const addFormVariant = () => setForm({ ...form, variants: [...(form.variants || []), { name: "", price: Number(form.price) || 0, cost: Number(form.cost) || 0, active: true }] });
  const updFormVariant = (i, patch) => setForm({ ...form, variants: form.variants.map((v, idx) => idx === i ? { ...v, ...patch } : v) });
  const rmFormVariant = (i) => setForm({ ...form, variants: form.variants.filter((_, idx) => idx !== i) });

  const toggleActive = async (p) => {
    try {
      await axios.put(`${API}/products/${p.id}`, { name: p.name, is_active: !(p.is_active !== false) });
      notify(p.is_active !== false ? `"${p.name}" dinonaktifkan — hilang dari POS & self-order` : `"${p.name}" diaktifkan kembali`);
      reload();
    } catch (e) { notify("Gagal ubah status produk"); }
  };

  // Filters
  const categories = useMemo(() => ["Semua", ...Array.from(new Set(products.map((p) => p.category).filter(Boolean)))], [products]);
  const filtered = useMemo(() => products.filter((p) => {
    if (statusTab === "active" && p.is_active === false) return false;
    if (statusTab === "inactive" && p.is_active !== false) return false;
    if (filterCat !== "Semua" && p.category !== filterCat) return false;
    if (filterMerchant !== "Semua" && p.merchant_id !== filterMerchant) return false;
    if (search) {
      const s = search.toLowerCase();
      if (!p.name.toLowerCase().includes(s) && !(p.sku || "").toLowerCase().includes(s)) return false;
    }
    return true;
  }), [products, search, filterCat, filterMerchant, statusTab]);
  const counts = useMemo(() => ({
    all: products.length,
    active: products.filter((p) => p.is_active !== false).length,
    inactive: products.filter((p) => p.is_active === false).length,
  }), [products]);

  // CSV Template & Export
  const downloadCSVTemplate = () => {
    const headers = ["nama_produk", "sku", "merchant_id", "kategori", "harga_jual", "hpp_per_porsi", "stok_awal", "outlet_id", "is_active"];
    const example = ["Es Kopi Pandan", "KP-001", merchants[0]?.id || "m-barista", "Kopi", "25000", "12000", "50", "outlet-sudirman", "true"];
    const csv = headers.join(",") + "\n" + example.map((v) => `"${v}"`).join(",");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "mjd-template-produk.csv";
    a.click();
    notify("Template CSV berhasil diunduh");
  };
  const exportCatalog = () => {
    const rows = products.map((p) => ({
      id: p.id, nama_produk: p.name, sku: p.sku || "", merchant_id: p.merchant_id || "",
      kategori: p.category, harga_jual: p.price, hpp_per_porsi: p.cost, stok_awal: p.stock,
      outlet_id: p.outlet_id || "outlet-sudirman", is_active: p.is_active !== false ? "true" : "false",
      varian: (p.variants || []).length,
      image_url: p.image_url ? "yes" : "",
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Katalog Produk");
    XLSX.writeFile(wb, `mjd-catalog-${new Date().toISOString().slice(0,10)}.xlsx`);
    notify(`${rows.length} produk diekspor ke Excel`);
  };

  return <>
    <SectionHeader eyebrow="CATALOG & COSTING" title="Produk & HPP" description="Bangun katalog menu, kelola varian, HPP, dan visibility ke POS/Self-Order."
      action={<div className="row-gap">
        <button className="outline-btn" onClick={downloadCSVTemplate} data-testid="download-csv-template-btn"><Download size={14}/> Unduh Template CSV</button>
        <button className="outline-btn" onClick={exportCatalog} data-testid="export-catalog-btn"><FileSpreadsheet size={14}/> Export Data</button>
        <button className="outline-btn" onClick={() => setShowImport(true)} data-testid="open-import-modal-btn"><Upload size={14}/> Import Produk</button>
        <button className="primary-btn" data-testid="new-product-button" onClick={() => document.querySelector("#new-product")?.focus()}><Plus size={16} /> Produk baru</button>
      </div>} />

    {/* Sticky Search & Filter Bar */}
    <div className="product-filter-bar" data-testid="product-filter-bar">
      <div className="pf-search">
        <Search size={16}/>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama atau SKU produk..." data-testid="product-search-input" />
      </div>
      <select value={filterCat} onChange={(e) => setFilterCat(e.target.value)} data-testid="filter-category-select">
        {categories.map((c) => <option key={c} value={c}>{c === "Semua" ? "Semua Kategori" : c}</option>)}
      </select>
      <select value={filterMerchant} onChange={(e) => setFilterMerchant(e.target.value)} data-testid="filter-merchant-select">
        <option value="Semua">Semua Merchant</option>
        {merchants.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
      </select>
      <div className="pf-tabs">
        <button className={statusTab === "all" ? "active" : ""} onClick={() => setStatusTab("all")} data-testid="status-tab-all">Semua ({counts.all})</button>
        <button className={statusTab === "active" ? "active" : ""} onClick={() => setStatusTab("active")} data-testid="status-tab-active">Aktif ({counts.active})</button>
        <button className={statusTab === "inactive" ? "active" : ""} onClick={() => setStatusTab("inactive")} data-testid="status-tab-inactive">Tidak Aktif ({counts.inactive})</button>
      </div>
    </div>

    <div className="product-form-v2 panel">
      <div className="form-heading"><div className="form-icon"><ClipboardList size={18} /></div><div><h2>Tambah menu cepat</h2><span>Bind ke merchant / tenant · unggah foto produk · varian harga</span></div></div>
      <div className="product-form-grid">
        <div className="product-image-picker">
          <label className="image-drop" data-testid="product-image-label">
            {form.image_url ? <img src={form.image_url} alt="preview" /> : <><ImageIcon size={30} /><span>Klik untuk unggah foto</span></>}
            <input type="file" accept="image/*" onChange={handleImage} style={{ display: "none" }} data-testid="product-image-input" />
          </label>
        </div>
        <div className="product-fields">
          <label className="field-lg"><span>Nama produk</span><input id="new-product" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Contoh: Es Kopi Pandan" data-testid="product-name-input" /></label>
          <label><span>SKU / Barcode</span><input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} placeholder="KP-001" data-testid="product-sku-input" /></label>
          <label><span>Merchant</span><select value={form.merchant_id} onChange={(e) => setForm({ ...form, merchant_id: e.target.value })} data-testid="product-merchant-select">{merchants.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
          {session?.role === "Super Admin" && <label className="switch-lg" data-testid="product-global-toggle-wrapper">
            <input type="checkbox" checked={form.is_global} onChange={(e) => setForm({ ...form, is_global: e.target.checked })} data-testid="product-global-toggle" />
            <i /><span>{form.is_global ? "🌐 SEMUA OUTLET" : "🏪 SPESIFIK OUTLET"}</span>
          </label>}
          {!form.is_global && <label><span>Outlet Target</span><select value={form.outlet_id} onChange={(e) => setForm({ ...form, outlet_id: e.target.value })} data-testid="product-outlet-select" disabled={session?.role !== "Super Admin"}>
            <option value="">— Pilih Outlet —</option>
            {outlets.filter((o) => o.active !== false).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select></label>}
          <label><span>Kategori</span><select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="product-category-select">{["Kopi", "Non-Kopi", "Makanan", "Snack"].map((c) => <option key={c}>{c}</option>)}</select></label>
          <label><span>Harga jual (Rp)</span><input type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} onFocus={numOnFocus} placeholder="0" data-testid="product-price-input" /></label>
          <label><span>HPP per porsi (Rp)</span><input type="number" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} onFocus={numOnFocus} placeholder="0" data-testid="product-cost-input" /></label>
          <label><span>Stok awal</span><input type="number" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} onFocus={numOnFocus} placeholder="0" data-testid="product-stock-input" /></label>
        </div>
      </div>
      <div className="variant-editor" data-testid="variant-editor">
        <div className="ve-head"><b>Varian Produk (opsional)</b><span>Contoh: Panas / Ice, Reg / Large — bisa harga & HPP berbeda</span>
          <button className="outline-btn" type="button" onClick={addFormVariant} data-testid="add-variant-button"><Plus size={13}/> Tambah Varian</button>
        </div>
        {(form.variants || []).length > 0 && <div className="ve-rows">
          <div className="ve-row ve-label"><span>Nama Varian</span><span>Harga Jual</span><span>HPP</span><span>Aktif</span><span /></div>
          {form.variants.map((v, i) => (
            <div className="ve-row" key={i}>
              <input value={v.name} onChange={(e) => updFormVariant(i, { name: e.target.value })} placeholder="Panas / Ice / Large" data-testid={`variant-name-${i}`} />
              <input type="number" value={v.price} onChange={(e) => updFormVariant(i, { price: Number(e.target.value) })} onFocus={numOnFocus} data-testid={`variant-price-${i}`} />
              <input type="number" value={v.cost} onChange={(e) => updFormVariant(i, { cost: Number(e.target.value) })} onFocus={numOnFocus} data-testid={`variant-cost-${i}`} />
              <label className="switch"><input type="checkbox" checked={v.active !== false} onChange={(e) => updFormVariant(i, { active: e.target.checked })} /><i /></label>
              <button className="icon-danger" type="button" onClick={() => rmFormVariant(i)} data-testid={`remove-variant-${i}`}><Trash2 size={13}/></button>
            </div>
          ))}
        </div>}
      </div>
      <button className="primary-btn full-row" onClick={save} data-testid="save-product-button"><Plus size={14}/> Simpan produk</button>
    </div>

    {filtered.length === 0 && <div className="empty-vendor" data-testid="products-empty"><Package size={30}/><b>Tidak ada produk sesuai filter</b><span>Ubah pencarian atau tab status di atas</span></div>}
    <div className="catalog-grid">
      {filtered.map((p) => {
        const inactive = p.is_active === false;
        return <div className={`catalog-item ${inactive ? "is-inactive" : ""}`} key={p.id} data-testid={`product-card-${p.id}`}>
          <div className="product-art" style={{ background: p.color }}>{p.image_url ? <img src={p.image_url} alt={p.name} className="product-img" /> : <Coffee size={26} />}
            {inactive && <span className="inactive-badge" data-testid={`inactive-badge-${p.id}`}>TIDAK AKTIF</span>}
          </div>
          <div><b>{p.name}</b><span>{p.vendor} · {p.category}{p.sku ? ` · SKU ${p.sku}` : ""}</span>
            <small>Margin <strong>{p.price ? Math.round((1 - p.cost / p.price) * 100) : 0}%</strong> · Stok {p.stock}
              {(p.variants || []).length > 0 && <em className="variant-chip"> · {p.variants.length} varian</em>}
            </small>
          </div>
          <div className="cat-actions">
            <label className="switch is-active-switch" title={inactive ? "Aktifkan produk" : "Nonaktifkan produk"} data-testid={`toggle-active-${p.id}`}>
              <input type="checkbox" checked={!inactive} onChange={() => toggleActive(p)} />
              <i />
            </label>
            <button className="small-action" onClick={() => setEditProduct(p)} data-testid={`edit-product-${p.id}`}><Pencil size={12}/> Edit</button>
            <button className="more-btn" onClick={async () => { if (window.confirm(`Hapus ${p.name}?`)) { await axios.delete(`${API}/products/${p.id}`); reload(); notify("Produk dihapus"); } }} data-testid={`product-menu-${p.id}`}><Trash2 size={13} /></button>
          </div>
        </div>;
      })}
    </div>
    {editProduct && <ProductEditModal product={editProduct} merchants={merchants} onClose={() => setEditProduct(null)} onSaved={() => { setEditProduct(null); reload(); notify("Produk tersimpan"); }} notify={notify} />}
    {showImport && <BulkImportModal merchants={merchants} onClose={() => setShowImport(false)} onDone={(msg) => { setShowImport(false); reload(); notify(msg); }} />}
  </>;
}

function ProductEditModal({ product, merchants, onClose, onSaved, notify }) {
  const [form, setForm] = useState({
    name: product.name || "",
    sku: product.sku || "",
    category: product.category || "Kopi",
    merchant_id: product.merchant_id || (merchants[0]?.id || ""),
    price: product.price || 0,
    cost: product.cost || 0,
    stock: product.stock || 0,
    is_active: product.is_active !== false,
    color: product.color || "#ffedd5",
    image_url: product.image_url || "",
    variants: (product.variants || []).map((v) => ({ ...v })),
  });
  const [saving, setSaving] = useState(false);
  const handleImage = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => setForm({ ...form, image_url: r.result }); r.readAsDataURL(f); };
  const addV = () => setForm({ ...form, variants: [...form.variants, { name: "", price: Number(form.price) || 0, cost: Number(form.cost) || 0, active: true }] });
  const updV = (i, patch) => setForm({ ...form, variants: form.variants.map((v, idx) => idx === i ? { ...v, ...patch } : v) });
  const rmV = (i) => setForm({ ...form, variants: form.variants.filter((_, idx) => idx !== i) });
  const save = async () => {
    if (!form.name) return notify("Nama produk wajib diisi");
    setSaving(true);
    try {
      const vendor = merchants.find((m) => m.id === form.merchant_id)?.name || "MJD Kupi";
      await axios.put(`${API}/products/${product.id}`, { ...form, vendor, price: Number(form.price) || 0, cost: Number(form.cost) || 0, stock: Number(form.stock) || 0, variants: form.variants });
      onSaved();
    } catch (e) { notify(e.response?.data?.detail || "Gagal simpan produk"); }
    setSaving(false);
  };
  return <div className="modal-backdrop"><div className="pay-modal wide" data-testid="product-edit-modal">
    <button className="modal-close" onClick={onClose}><X size={18}/></button>
    <div className="pay-head"><h2>Edit Produk</h2><span>{product.name}{product.sku ? ` · SKU ${product.sku}` : ""}</span></div>
    <div className="product-form-grid" style={{ marginTop: 8 }}>
      <div className="product-image-picker">
        <label className="image-drop" data-testid="edit-product-image-label">
          {form.image_url ? <img src={form.image_url} alt="preview" /> : <><ImageIcon size={30}/><span>Unggah foto baru</span></>}
          <input type="file" accept="image/*" onChange={handleImage} style={{ display: "none" }} data-testid="edit-product-image-input" />
        </label>
        <label className="switch-lg" style={{ marginTop: 12 }} data-testid="edit-is-active-wrapper">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} data-testid="edit-is-active-toggle" />
          <i />
          <span>{form.is_active ? "AKTIF (tampil di POS & Self-Order)" : "TIDAK AKTIF (disembunyikan)"}</span>
        </label>
      </div>
      <div className="product-fields">
        <label className="field-lg"><span>Nama produk</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="edit-product-name-input" /></label>
        <label><span>SKU / Barcode</span><input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} data-testid="edit-product-sku-input" /></label>
        <label><span>Merchant</span><select value={form.merchant_id} onChange={(e) => setForm({ ...form, merchant_id: e.target.value })} data-testid="edit-product-merchant-select">{merchants.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        <label><span>Kategori</span><select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="edit-product-category-select">{["Kopi", "Non-Kopi", "Makanan", "Snack"].map((c) => <option key={c}>{c}</option>)}</select></label>
        <label><span>Harga jual (Rp)</span><input type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} onFocus={numOnFocus} data-testid="edit-product-price-input" /></label>
        <label><span>HPP per porsi (Rp)</span><input type="number" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} onFocus={numOnFocus} data-testid="edit-product-cost-input" /></label>
        <label><span>Stok</span><input type="number" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} onFocus={numOnFocus} data-testid="edit-product-stock-input" /></label>
      </div>
    </div>
    <div className="variant-editor" data-testid="edit-variant-editor">
      <div className="ve-head"><b>Varian Produk</b><span>Kelola opsi: Size, Suhu, Topping</span>
        <button className="outline-btn" type="button" onClick={addV} data-testid="edit-add-variant-btn"><Plus size={13}/> Tambah Varian</button>
      </div>
      {form.variants.length > 0 && <div className="ve-rows">
        <div className="ve-row ve-label"><span>Nama Varian</span><span>Harga</span><span>HPP</span><span>Aktif</span><span/></div>
        {form.variants.map((v, i) => <div className="ve-row" key={i}>
          <input value={v.name} onChange={(e) => updV(i, { name: e.target.value })} data-testid={`edit-var-name-${i}`}/>
          <input type="number" value={v.price} onChange={(e) => updV(i, { price: Number(e.target.value) })} onFocus={numOnFocus} data-testid={`edit-var-price-${i}`}/>
          <input type="number" value={v.cost} onChange={(e) => updV(i, { cost: Number(e.target.value) })} onFocus={numOnFocus} data-testid={`edit-var-cost-${i}`}/>
          <label className="switch"><input type="checkbox" checked={v.active !== false} onChange={(e) => updV(i, { active: e.target.checked })} data-testid={`edit-var-active-${i}`} /><i/></label>
          <button className="icon-danger" type="button" onClick={() => rmV(i)} data-testid={`edit-var-remove-${i}`}><Trash2 size={13}/></button>
        </div>)}
      </div>}
      {form.variants.length === 0 && <div className="empty-hint">Belum ada varian. Klik "Tambah Varian" untuk mulai.</div>}
    </div>
    <div className="modal-actions">
      <button className="outline-btn" onClick={onClose}>Batal</button>
      <button className="primary-btn" onClick={save} disabled={saving} data-testid="save-edit-product-btn"><Check size={14}/> {saving ? "Menyimpan…" : "Simpan Perubahan"}</button>
    </div>
  </div></div>;
}

function BulkImportModal({ merchants, onClose, onDone }) {
  const [rows, setRows] = useState([]);
  const [errors, setErrors] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState("");

  const parseFile = async (file) => {
    setFileName(file.name);
    setErrors([]);
    try {
      const buf = await file.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array" });
      const raw = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]]);
      const seenSku = new Set();
      const dedup = [];
      const errs = [];
      raw.forEach((r, i) => {
        const name = String(r.nama_produk || r.name || r.Nama || "").trim();
        const sku = String(r.sku || r.SKU || "").trim();
        if (!name) { errs.push({ row: i + 2, error: "nama_produk kosong" }); return; }
        if (sku && seenSku.has(sku)) { errs.push({ row: i + 2, error: `SKU duplikat: ${sku}` }); return; }
        if (sku) seenSku.add(sku);
        const isActiveRaw = String(r.is_active ?? "true").toLowerCase();
        dedup.push({
          id: r.id || null,
          name,
          sku,
          category: String(r.kategori || r.category || "Lain-lain"),
          merchant_id: r.merchant_id || null,
          outlet_id: r.outlet_id || "outlet-sudirman",
          price: Number(r.harga_jual || r.price || r.Harga || 0),
          cost: Number(r.hpp_per_porsi || r.cost || r.HPP || 0),
          stock: Number(r.stok_awal || r.stock || r.Stok || 0),
          is_active: !(isActiveRaw === "false" || isActiveRaw === "0" || isActiveRaw === "tidak"),
          color: r.color || "#ffedd5",
        });
      });
      setRows(dedup); setErrors(errs);
    } catch (e) { setErrors([{ row: 0, error: "Gagal parsing file: " + e.message }]); }
  };

  const upload = async () => {
    if (!rows.length) return;
    setUploading(true);
    try {
      const { data } = await axios.post(`${API}/products/bulk-import`, { rows, mode: "upsert" });
      onDone(`Import selesai: ${data.created} baru, ${data.updated} diperbarui, ${(data.errors?.length || 0) + errors.length} error`);
    } catch (e) { setErrors([{ row: 0, error: e.response?.data?.detail || "Upload gagal" }]); }
    setUploading(false);
  };

  return <div className="modal-backdrop"><div className="pay-modal wide" data-testid="bulk-import-modal">
    <button className="modal-close" onClick={onClose}><X size={18}/></button>
    <div className="pay-head"><h2>Import Produk (Bulk)</h2><span>Upload file .csv / .xlsx / .xls — auto dedup by SKU</span></div>
    <div className="excel-card" style={{ padding: 20, border: "1px dashed #e5e7eb", borderRadius: 12, margin: "12px 0" }}>
      <label className="primary-btn" data-testid="bulk-import-file-label" style={{ display: "inline-flex" }}>
        <Upload size={14}/> Pilih File
        <input type="file" accept=".xlsx,.xls,.csv" onChange={(e) => e.target.files?.[0] && parseFile(e.target.files[0])} style={{ display: "none" }} data-testid="bulk-import-file-input"/>
      </label>
      {fileName && <span style={{ marginLeft: 12, color: "#6b7280", fontSize: 13 }}>{fileName} · <b>{rows.length}</b> baris valid{errors.length ? ` · ${errors.length} error` : ""}</span>}
    </div>
    {rows.length > 0 && <div className="data-table" style={{ maxHeight: 260, overflowY: "auto" }} data-testid="bulk-import-preview">
      <div className="table-row table-label"><span>Nama</span><span>SKU</span><span>Kategori</span><span>Harga</span><span>HPP</span><span>Stok</span><span>Status</span></div>
      {rows.slice(0, 20).map((r, i) => <div className="table-row" key={i}>
        <span><b>{r.name}</b></span>
        <span><small>{r.sku || "—"}</small></span>
        <span>{r.category}</span>
        <span>{money(r.price)}</span>
        <span>{money(r.cost)}</span>
        <span>{r.stock}</span>
        <span><span className="method-badge" style={{ background: r.is_active ? "#dcfce7" : "#fee2e2", color: r.is_active ? "#166534" : "#991b1b" }}>{r.is_active ? "Aktif" : "Nonaktif"}</span></span>
      </div>)}
      {rows.length > 20 && <div className="empty-hint">…dan {rows.length - 20} baris lainnya</div>}
    </div>}
    {errors.length > 0 && <div className="empty-hint" data-testid="bulk-import-errors" style={{ background: "#fef2f2", color: "#991b1b" }}>
      <b>{errors.length} error terdeteksi:</b>
      <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>{errors.slice(0, 5).map((er, i) => <li key={i}>Baris {er.row}: {er.error}</li>)}</ul>
    </div>}
    <div className="modal-actions">
      <button className="outline-btn" onClick={onClose}>Batal</button>
      <button className="primary-btn" onClick={upload} disabled={!rows.length || uploading} data-testid="bulk-import-submit-btn"><Upload size={14}/> {uploading ? "Mengunggah…" : `Import ${rows.length} Produk`}</button>
    </div>
  </div></div>;
}

function VariantEditModal({ product, onClose, onSaved }) {
  // Deprecated: kept for backward compatibility; use ProductEditModal for full edit
  const [rows, setRows] = useState(product.variants || []);
  const add = () => setRows([...rows, { name: "", price: 0, cost: 0, active: true }]);
  const upd = (i, patch) => setRows(rows.map((v, idx) => idx === i ? { ...v, ...patch } : v));
  const rm = (i) => setRows(rows.filter((_, idx) => idx !== i));
  const save = async () => {
    try {
      await axios.put(`${API}/products/${product.productId}`, { name: product.name, variants: rows });
      onSaved();
    } catch (e) { alert(e.response?.data?.detail || "Gagal simpan varian"); }
  };
  return <div className="modal-backdrop"><div className="pay-modal wide" data-testid="variant-modal">
    <button className="modal-close" onClick={onClose}><X size={18}/></button>
    <div className="pay-head"><h2>Kelola Varian</h2><span>{product.name}</span></div>
    <div className="ve-rows">
      <div className="ve-row ve-label"><span>Nama Varian</span><span>Harga Jual</span><span>HPP</span><span>Aktif</span><span/></div>
      {rows.map((v, i) => <div className="ve-row" key={i}>
        <input value={v.name} onChange={(e) => upd(i, { name: e.target.value })} placeholder="Panas / Ice / Large" data-testid={`edit-var-name-${i}`}/>
        <input type="number" value={v.price} onChange={(e) => upd(i, { price: Number(e.target.value) })} onFocus={numOnFocus} data-testid={`edit-var-price-${i}`}/>
        <input type="number" value={v.cost} onChange={(e) => upd(i, { cost: Number(e.target.value) })} onFocus={numOnFocus} data-testid={`edit-var-cost-${i}`}/>
        <label className="switch"><input type="checkbox" checked={v.active !== false} onChange={(e) => upd(i, { active: e.target.checked })}/><i/></label>
        <button className="icon-danger" onClick={() => rm(i)}><Trash2 size={13}/></button>
      </div>)}
      {rows.length === 0 && <div className="empty-hint">Belum ada varian. Klik "Tambah Varian" untuk mulai.</div>}
    </div>
    <div className="modal-actions">
      <button className="outline-btn" onClick={add} data-testid="add-variant-modal-button"><Plus size={13}/> Tambah Varian</button>
      <button className="primary-btn" onClick={save} data-testid="save-variants-button"><Check size={14}/> Simpan</button>
    </div>
  </div></div>;
}

// -------- Merchants --------
function Merchants({ merchants, reload, notify }) {
  const [form, setForm] = useState({ name: "", category: "F&B", commission_scheme: "percent", commission_percent: 10, commission_fixed: 1000, phone: "", color: "#ffedd5" });
  const [editing, setEditing] = useState(null);
  const save = async () => {
    if (!form.name) return notify("Nama merchant wajib diisi");
    await axios.post(`${API}/merchants`, form);
    setForm({ ...form, name: "", phone: "" });
    reload(); notify("Merchant terdaftar");
  };
  const remove = async (m) => { if (!window.confirm(`Hapus merchant ${m.name}?`)) return; try { await axios.delete(`${API}/merchants/${m.id}`); reload(); notify("Merchant dihapus"); } catch (e) { notify(e.response?.data?.detail || "Gagal menghapus"); } };
  const commissionLabel = (m) => m.commission_scheme === "fixed" ? `${money(m.commission_fixed || 0)} / item` : `${m.commission_percent}%`;
  return <>
    <SectionHeader eyebrow="TENANT & WHITE-LABEL" title="Merchant & Mitra Toko" description="Kelola mitra, komisi (Persentase / Nominal Tetap), branding kustom, dan status langganan SaaS."
      action={<div className="live-pill"><i /> {merchants.length} tenant aktif</div>} />
    <div className="product-form panel">
      <div className="form-heading"><div className="form-icon"><Store size={18} /></div><div><h2>Tambah merchant / tenant</h2><span>Skema komisi berlaku otomatis di Vendor Settlement Center.</span></div></div>
      <div className="form-fields" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1.2fr 1.2fr auto" }}>
        <label><span>Nama</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="merchant-name-input" /></label>
        <label><span>Kategori</span><select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="merchant-category-select">{["F&B", "Kopi", "Makanan", "Snack", "Minuman"].map((c) => <option key={c}>{c}</option>)}</select></label>
        <label><span>Skema Komisi</span>
          <select value={form.commission_scheme} onChange={(e) => setForm({ ...form, commission_scheme: e.target.value })} data-testid="merchant-scheme-select">
            <option value="percent">Persentase (%)</option>
            <option value="fixed">Nominal Tetap (Rp)</option>
          </select>
        </label>
        {form.commission_scheme === "fixed"
          ? <label><span>Nilai (Rp / item)</span><input type="number" value={form.commission_fixed} onChange={(e) => setForm({ ...form, commission_fixed: Number(e.target.value) })} onFocus={numOnFocus} placeholder="1000" data-testid="merchant-commission-fixed-input"/></label>
          : <label><span>Persentase (%)</span><input type="number" value={form.commission_percent} onChange={(e) => setForm({ ...form, commission_percent: Number(e.target.value) })} onFocus={numOnFocus} placeholder="10" data-testid="merchant-commission-input"/></label>}
        <label><span>WhatsApp (628…)</span><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="merchant-phone-input" /></label>
        <button className="primary-btn" onClick={save} data-testid="save-merchant-button">Simpan</button>
      </div>
    </div>
    <section className="panel table-panel">
      <div className="panel-head"><div><h2>Merchant terdaftar</h2><span>Klik "White-Label" untuk custom branding, subscription, & feature access</span></div></div>
      <div className="data-table">
        <div className="table-row wl-row table-label"><span>Merchant</span><span>Kategori</span><span>Skema Komisi</span><span>Slug/Domain</span><span>Subscription</span><span>Status</span><span /></div>
        {merchants.map((m) => <div className="table-row wl-row" key={m.id} data-testid={`merchant-row-${m.id}`}>
          <span className="table-product">
            <div className="product-dot" style={{ background: m.theme_color || m.color || "#ffedd5" }}>{m.logo_url ? <img src={m.logo_url} alt="" style={{width:22,height:22,borderRadius:6}}/> : <Store size={14} />}</div>
            <b>{m.name}</b>
          </span>
          <span>{m.category}</span>
          <span><b>{commissionLabel(m)}</b><small style={{ display: "block", color: "#6b7280" }}>{m.commission_scheme === "fixed" ? "Flat fee" : "Persentase"}</small></span>
          <span className="mono-small">{m.slug ? `${m.slug}.mjdkupi.com` : "—"}</span>
          <span><i className={`status-dot ${m.subscription_status === "active" ? "good" : m.subscription_status === "suspended" ? "low" : "warn"}`} />{m.subscription_status || "active"}</span>
          <span><i className={`status-dot ${m.active ? "good" : "low"}`} />{m.active ? "Aktif" : "Nonaktif"}</span>
          <span className="wl-actions">
            <button className="small-action" onClick={() => setEditing(m)} data-testid={`edit-merchant-${m.id}`}><Settings2 size={12}/> White-Label</button>
            <button className="small-action" onClick={() => remove(m)} data-testid={`delete-merchant-${m.id}`}><Trash2 size={12} /> Hapus</button>
          </span>
        </div>)}
      </div>
    </section>
    {editing && <WhiteLabelModal merchant={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); notify("White-Label mitra tersimpan"); }} />}
  </>;
}

function WhiteLabelModal({ merchant, onClose, onSaved }) {
  const [f, setF] = useState({
    name: merchant.name || "",
    category: merchant.category || "F&B",
    commission_scheme: merchant.commission_scheme || "percent",
    commission_percent: merchant.commission_percent || 10,
    commission_fixed: merchant.commission_fixed || 1000,
    phone: merchant.phone || "",
    color: merchant.color || "#ffedd5",
    active: merchant.active !== false,
    slug: merchant.slug || "",
    logo_url: merchant.logo_url || "",
    theme_color: merchant.theme_color || "#f97316",
    banner_url: merchant.banner_url || "",
    receipt_header: merchant.receipt_header || "",
    receipt_footer: merchant.receipt_footer || "",
    wifi_password: merchant.wifi_password || "",
    subscription_status: merchant.subscription_status || "active",
    features_enabled: merchant.features_enabled || {},
  });
  const setFile = (key) => (e) => { const file = e.target.files?.[0]; if (!file) return; const r = new FileReader(); r.onload = () => setF((s) => ({ ...s, [key]: r.result })); r.readAsDataURL(file); };
  const toggleFeature = (k) => setF((s) => ({ ...s, features_enabled: { ...s.features_enabled, [k]: s.features_enabled[k] === false ? true : false } }));
  const save = async () => {
    try {
      await axios.put(`${API}/merchants/${merchant.id}`, f);
      onSaved();
    } catch (e) { alert(e.response?.data?.detail || "Gagal simpan"); }
  };
  const FEATURES_M = [
    { key: "pos", label: "Akses Terminal POS" },
    { key: "self_order", label: "Customer Self-Order QR" },
    { key: "kds", label: "Kitchen Display (KDS)" },
    { key: "multi_merchant", label: "Multi-Merchant/Tenant" },
    { key: "reports", label: "Laporan Keuangan & HPP" },
    { key: "inventory", label: "Inventori & Stok Opname" },
  ];
  return <div className="modal-backdrop"><div className="pay-modal wl-modal" data-testid="white-label-modal">
    <button className="modal-close" onClick={onClose}><X size={18}/></button>
    <div className="pay-head"><h2>White-Label · {merchant.name}</h2><span>Konfigurasi identitas 100% brand mitra</span></div>
    <div className="wl-grid">
      <div className="wl-col">
        <div className="wl-section">
          <b>Identitas & Domain</b>
          <label>Nama Mitra / Nama Usaha<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="wl-name"/></label>
          <label>Slug / Subdomain <em>(huruf kecil, tanpa spasi)</em><input value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} placeholder="acehjaya" data-testid="wl-slug"/></label>
          <div className="mono-small">→ {f.slug ? `${f.slug}.mjdkupi.com` : "belum diisi"}</div>
          <label>WhatsApp<input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} placeholder="6281100000000"/></label>
        </div>
        <div className="wl-section">
          <b>Branding Visual</b>
          <label>Warna Aksen<input type="color" value={f.theme_color} onChange={(e) => setF({ ...f, theme_color: e.target.value })} data-testid="wl-color"/></label>
          <label>Logo Mitra (PNG/JPG)
            {f.logo_url && <img src={f.logo_url} alt="logo" className="wl-preview"/>}
            <input type="file" accept="image/*" onChange={setFile("logo_url")} data-testid="wl-logo-input"/>
          </label>
          <label>Banner Promosi Self-Order
            {f.banner_url && <img src={f.banner_url} alt="banner" className="wl-preview banner"/>}
            <input type="file" accept="image/*" onChange={setFile("banner_url")} data-testid="wl-banner-input"/>
          </label>
        </div>
      </div>
      <div className="wl-col">
        <div className="wl-section">
          <b>Struk & Wi-Fi</b>
          <label>Header Struk<textarea rows={2} value={f.receipt_header} onChange={(e) => setF({ ...f, receipt_header: e.target.value })} placeholder="Alamat, No. Telp"/></label>
          <label>Footer Struk<textarea rows={2} value={f.receipt_footer} onChange={(e) => setF({ ...f, receipt_footer: e.target.value })} placeholder="Terima kasih atas kunjungannya"/></label>
          <label>Password Wi-Fi<input value={f.wifi_password} onChange={(e) => setF({ ...f, wifi_password: e.target.value })} placeholder="kopi123"/></label>
        </div>
        <div className="wl-section">
          <b>Skema Komisi Platform</b>
          <label>Tipe Komisi
            <select value={f.commission_scheme} onChange={(e) => setF({ ...f, commission_scheme: e.target.value })} data-testid="wl-scheme-select">
              <option value="percent">Persentase (%) — cocok untuk margin tinggi</option>
              <option value="fixed">Nominal Tetap (Rp) — cocok untuk item volume</option>
            </select>
          </label>
          {f.commission_scheme === "fixed"
            ? <label>Nilai per Item Terjual (Rp)<input type="number" value={f.commission_fixed} onChange={(e) => setF({ ...f, commission_fixed: Number(e.target.value) })} onFocus={numOnFocus} placeholder="1000" data-testid="wl-commission-fixed"/></label>
            : <label>Persentase (%)<input type="number" value={f.commission_percent} onChange={(e) => setF({ ...f, commission_percent: Number(e.target.value) })} onFocus={numOnFocus} placeholder="10" data-testid="wl-commission-percent"/></label>}
          <div className="empty-hint" style={{ background: "#fff7ed", color: "#9a3412", margin: 0 }}>
            Preview: <b>{f.commission_scheme === "fixed" ? `${money(f.commission_fixed || 0)} / item` : `${f.commission_percent || 0}% dari harga jual`}</b>
          </div>
        </div>
        <div className="wl-section">
          <b>Subscription / Masa Aktif</b>
          <label>Status<select value={f.subscription_status} onChange={(e) => setF({ ...f, subscription_status: e.target.value })} data-testid="wl-sub-status">
            <option value="active">Aktif</option>
            <option value="trial">Trial</option>
            <option value="pending">Pending</option>
            <option value="suspended">Suspend (blokir login)</option>
          </select></label>
        </div>
        <div className="wl-section">
          <b>Paket Fitur (SaaS Toggle)</b>
          <div className="wl-features">
            {FEATURES_M.map((ft) => {
              const on = f.features_enabled[ft.key] !== false;
              return <label key={ft.key} className={`ft-cell mini ${on ? "on" : "off"}`} data-testid={`wl-feat-${ft.key}`}>
                <input type="checkbox" checked={on} onChange={() => toggleFeature(ft.key)}/>
                <b>{ft.label}</b><span>{on ? "Aktif" : "Nonaktif"}</span>
              </label>;
            })}
          </div>
        </div>
      </div>
    </div>
    <div className="modal-actions">
      <button className="outline-btn" onClick={onClose}>Batal</button>
      <button className="primary-btn" onClick={save} data-testid="save-white-label"><Check size={14}/> Simpan White-Label</button>
    </div>
  </div></div>;
}

// -------- Reports --------
function Reports({ products, expenses }) {
  const [dash, setDash] = useState({ sales_total: 0, expense_total: 0 });
  useEffect(() => { axios.get(`${API}/dashboard`).then(({ data }) => setDash(data)).catch(() => {}); }, []);
  const sales = dash.sales_total || 0;
  const cogs = Math.round(sales * 0.42);
  const exp = expenses.reduce((a, e) => a + e.amount, 0);
  return <>
    <SectionHeader eyebrow="FINANCIAL STATEMENT" title="Laporan keuangan" description="Gambaran profitabilitas Outlet bulan ini."
      action={<button className="outline-btn" data-testid="export-report-button" onClick={() => { const rows = [["MJD Kupi Laporan"], ["Omset", sales], ["HPP", cogs], ["Pengeluaran", exp], ["Laba bersih", sales - cogs - exp]]; const csv = rows.map((r) => r.join(",")).join("\n"); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "mjd-kupi-laporan.csv"; a.click(); }}><FileText size={15} /> Export CSV</button>} />
    <div className="profit-hero"><div><span>Estimasi laba bersih</span><strong>{money(sales - cogs - exp)}</strong><small><i>↑</i> vs bulan lalu</small></div><div className="profit-ring"><div><b>{sales ? Math.round((1 - cogs / sales) * 100) : 0}%</b><span>gross margin</span></div></div></div>
    <section className="panel statement">
      <div className="panel-head"><div><h2>Profit & Loss Statement</h2><span>Data live Supabase</span></div></div>
      {[["Penjualan bersih", sales, "income"], ["(-) HPP terjual", -cogs, "cost"], ["Laba kotor", sales - cogs, "strong"], ["(-) Pengeluaran operasional", -exp, "cost"], ["Laba bersih", sales - cogs - exp, "total"]].map(([l, v, c]) => <div className={`statement-row ${c}`} key={l}><span>{l}</span><b>{money(v)}</b></div>)}
    </section>
  </>;
}

// -------- Tables (QR) --------
function Tables({ notify, activeOutlet, branding }) {
  const [count, setCount] = useState(() => {
    try { return Math.max(1, Math.min(500, Number(localStorage.getItem("mjd_qr_count")) || 12)); } catch { return 12; }
  });
  const [baseUrl, setBaseUrl] = useState(() => {
    try { return localStorage.getItem("mjd_qr_base_url") || ORIGIN; } catch { return ORIGIN; }
  });
  const [storeId, setStoreId] = useState(() => {
    try { return localStorage.getItem("mjd_qr_store_id") || (branding?.slug || ""); } catch { return ""; }
  });
  const [pdfProgress, setPdfProgress] = useState(null); // { done, total } | null
  const qrRefs = useRef({}); // { [tableNo]: SVG element }
  useEffect(() => { try { localStorage.setItem("mjd_qr_base_url", baseUrl); } catch {} }, [baseUrl]);
  useEffect(() => { try { localStorage.setItem("mjd_qr_store_id", storeId); } catch {} }, [storeId]);
  useEffect(() => { try { localStorage.setItem("mjd_qr_count", String(count)); } catch {} }, [count]);
  const meja = useMemo(() => Array.from({ length: count }, (_, i) => String(i + 1).padStart(String(count).length >= 3 ? 3 : 2, "0")), [count]);
  const outletId = activeOutlet && activeOutlet !== "all" ? activeOutlet : "outlet-sudirman";
  const linkFor = (t) => {
    const parts = [`table=${t}`, `outlet_id=${outletId}`];
    if (storeId) parts.unshift(`store_id=${storeId}`);
    return `${baseUrl}/self-order?${parts.join("&")}`;
  };

  // Render a single QR card SVG → canvas dataURL (PNG). Returns { dataUrl, w, h }.
  const renderQRCanvas = async (tableNo, size = 512) => {
    const svg = qrRefs.current[tableNo];
    if (!svg) return null;
    // Compose a printable card: brand + QR + label
    const cardW = size + 80;
    const cardH = size + 220;
    const canvas = document.createElement("canvas");
    canvas.width = cardW; canvas.height = cardH;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, cardW, cardH);
    // Brand text
    ctx.fillStyle = "#18212b"; ctx.textAlign = "center";
    ctx.font = "bold 34px 'Space Grotesk', sans-serif";
    ctx.fillText(branding?.name || "MJD Kupi", cardW / 2, 60);
    // QR: convert SVG → img → draw
    const xml = new XMLSerializer().serializeToString(svg);
    const svg64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
    await new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => { ctx.drawImage(img, 40, 90, size, size); res(); };
      img.onerror = rej;
      img.src = svg64;
    });
    // Table label
    ctx.fillStyle = "#f97316"; ctx.font = "bold 48px 'Space Grotesk', sans-serif";
    ctx.fillText(`MEJA ${tableNo}`, cardW / 2, size + 155);
    ctx.fillStyle = "#6b7280"; ctx.font = "18px sans-serif";
    ctx.fillText("Scan QR untuk Pesan", cardW / 2, size + 190);
    return { dataUrl: canvas.toDataURL("image/png"), w: cardW, h: cardH };
  };

  const downloadPNG = async (tableNo) => {
    try {
      const r = await renderQRCanvas(tableNo, 512);
      if (!r) return notify("QR belum siap");
      const a = document.createElement("a");
      a.href = r.dataUrl; a.download = `qr-meja-${tableNo}.png`; a.click();
      notify(`QR Meja ${tableNo} diunduh (PNG)`);
    } catch (e) { notify("Gagal unduh QR"); }
  };

  const downloadSinglePDF = async (tableNo) => {
    try {
      const { jsPDF } = await import("jspdf");
      const r = await renderQRCanvas(tableNo, 512);
      if (!r) return notify("QR belum siap");
      const pdf = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
      const pageW = 210, pageH = 297;
      const imgW = 120, imgH = (r.h / r.w) * imgW;
      pdf.addImage(r.dataUrl, "PNG", (pageW - imgW) / 2, (pageH - imgH) / 2, imgW, imgH, undefined, "FAST");
      pdf.save(`qr-meja-${tableNo}.pdf`);
      notify(`QR Meja ${tableNo} diunduh (PDF)`);
    } catch (e) { notify("Gagal unduh PDF"); }
  };

  // Batch print ALL as PDF (2 per page landscape or 4 per page portrait)
  const printAllPDF = async () => {
    try {
      setPdfProgress({ done: 0, total: meja.length });
      const { jsPDF } = await import("jspdf");
      const pdf = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
      const pageW = 210, pageH = 297;
      const perPage = 4; // 2x2 grid
      const cols = 2, rows = 2;
      const cellW = pageW / cols, cellH = pageH / rows;
      const marginX = 8, marginY = 8;
      for (let i = 0; i < meja.length; i++) {
        const tableNo = meja[i];
        const posInPage = i % perPage;
        if (i > 0 && posInPage === 0) pdf.addPage();
        const col = posInPage % cols, row = Math.floor(posInPage / cols);
        const r = await renderQRCanvas(tableNo, 384);
        if (r) {
          const availW = cellW - marginX * 2;
          const availH = cellH - marginY * 2;
          const ratio = Math.min(availW / r.w, availH / r.h) * 2.83; // dataUrl in px → mm rough
          const drawW = Math.min(availW, r.w * ratio / 2.83);
          const drawH = (r.h / r.w) * drawW;
          const x = col * cellW + (cellW - drawW) / 2;
          const y = row * cellH + (cellH - drawH) / 2;
          pdf.addImage(r.dataUrl, "PNG", x, y, drawW, drawH, undefined, "FAST");
        }
        setPdfProgress({ done: i + 1, total: meja.length });
        // Yield to browser every 5 cards → prevent mobile browser crash
        if (i % 5 === 4) await new Promise((res) => setTimeout(res, 30));
      }
      pdf.save(`qr-meja-${meja.length}-${outletId}-${Date.now()}.pdf`);
      setPdfProgress(null);
      notify(`✅ PDF berisi ${meja.length} QR meja berhasil diunduh`);
    } catch (e) {
      setPdfProgress(null);
      notify(`Gagal cetak PDF: ${e.message || e}`);
    }
  };

  const commitCount = (val) => {
    const v = Math.max(1, Math.min(500, Number(val) || 1));
    setCount(v);
  };

  return <>
    <SectionHeader eyebrow="SELF-ORDER STUDIO" title="QR meja pelanggan" description="Generate QR unik per meja (1-500). Download individual PNG/PDF atau cetak semua sekaligus."
      action={<div className="row-gap">
        <label className="mini-num">Jumlah meja<input type="number" value={count} min={1} max={500} onChange={(e) => commitCount(e.target.value)} onFocus={numOnFocus} data-testid="tables-count-input" /></label>
        <button className="outline-btn" onClick={printAllPDF} disabled={!!pdfProgress} data-testid="print-all-qr-button"><Printer size={14}/> {pdfProgress ? `Membuat PDF... ${pdfProgress.done}/${pdfProgress.total}` : "Cetak Semua QR (PDF)"}</button>
        <button className="primary-btn" data-testid="generate-qr-button" onClick={() => notify(`${count} QR meja siap cetak`)}><Plus size={16} /> Generate</button>
      </div>} />
    {pdfProgress && <div className="pdf-progress" data-testid="pdf-progress-bar">
      <div className="pdf-progress-bar"><div style={{ width: `${(pdfProgress.done / pdfProgress.total) * 100}%` }}/></div>
      <span>Merender QR {pdfProgress.done} dari {pdfProgress.total}… Jangan tutup halaman.</span>
    </div>}
    {/* Configuration form */}
    <div className="qr-config panel" data-testid="qr-config">
      <div className="form-heading"><div className="form-icon"><LinkIcon size={18}/></div>
        <div><h2>Konfigurasi URL QR</h2><span>Base URL dinamis — perubahan otomatis render ulang semua QR di bawah. Tersimpan otomatis di browser.</span></div>
      </div>
      <div className="qr-config-grid">
        <label>Domain / Base URL Order
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value.trim().replace(/\/$/, ""))} placeholder="https://mjdkupi.com" data-testid="qr-base-url-input"/>
        </label>
        <label>Store ID / Slug (opsional)
          <input value={storeId} onChange={(e) => setStoreId(e.target.value.trim())} placeholder="mjdkupi-jakarta" data-testid="qr-store-id-input"/>
        </label>
        <label>Outlet Target
          <input value={outletId} disabled/>
        </label>
      </div>
      <div className="qr-preview-url"><b>Preview URL:</b> <span className="mono">{linkFor(meja[0] || "01")}</span></div>
    </div>
    <div className="table-grid-v2 qr-cards-print">
      {meja.map((t) => <div className="table-card-v2 qr-print-card" key={t} data-testid={`table-card-${t}`}>
        <div className="qr-print-brand">
          {branding?.logo_url ? <img src={branding.logo_url} alt="" className="qr-brand-logo"/> : <Coffee size={22}/>}
          <b>{branding?.name || "MJD Kupi"}</b>
        </div>
        <div className="table-qr-real"><QRCodeSVG ref={(el) => { if (el) qrRefs.current[t] = el; }} value={linkFor(t)} size={140} level="H" includeMargin={true} /></div>
        <strong className="qr-table-no">MEJA {t}</strong>
        <span className="qr-cta">Scan QR untuk Pilih Menu & Pesan</span>
        <div className="table-card-actions no-print">
          <button className="small-action" onClick={() => { navigator.clipboard?.writeText(linkFor(t)); notify(`Link Meja ${t} disalin`); }} data-testid={`copy-table-${t}`}><Copy size={12} /> Salin</button>
          <button className="small-action" onClick={() => downloadPNG(t)} data-testid={`download-png-${t}`}><Download size={12} /> PNG</button>
          <button className="small-action" onClick={() => downloadSinglePDF(t)} data-testid={`download-pdf-${t}`}><FileText size={12} /> PDF</button>
        </div>
      </div>)}
    </div>
  </>;
}

// -------- Self-Service Management (per outlet banner, marquee, status) --------
function SelfService({ products, notify, activeOutlet, outlets }) {
  const validOutlets = (outlets && outlets.length ? outlets : [{ id: "outlet-sudirman", name: "Outlet Sudirman" }, { id: "outlet-kemang", name: "Outlet Kemang" }]);
  const [pickOutlet, setPickOutlet] = useState(activeOutlet && activeOutlet !== "all" ? activeOutlet : validOutlets[0]?.id);
  const [settings, setSettings] = useState({ banners: [], marquee_text: "", logo_url: "", header_image: "", force_closed: false, closed_message: "" });
  const [loading, setLoading] = useState(false);
  const [shiftOpen, setShiftOpen] = useState(false);
  useEffect(() => {
    if (!pickOutlet) return;
    setLoading(true);
    axios.get(`${API}/outlets/${pickOutlet}/self-service`).then(({ data }) => setSettings(data)).finally(() => setLoading(false)).catch(() => setLoading(false));
    axios.get(`${API}/outlets/${pickOutlet}/shift-status`).then(({ data }) => setShiftOpen(!!data.open)).catch(() => {});
  }, [pickOutlet]);
  const upd = (patch) => setSettings((s) => ({ ...s, ...patch }));
  const upload = (key) => (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => upd({ [key]: r.result }); r.readAsDataURL(f); };
  const addBanner = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => upd({ banners: [...(settings.banners || []), r.result] }); r.readAsDataURL(f); };
  const removeBanner = (i) => upd({ banners: settings.banners.filter((_, idx) => idx !== i) });
  const save = async () => {
    try { await axios.post(`${API}/outlets/${pickOutlet}/self-service`, settings); notify(`Konfigurasi ${validOutlets.find(o=>o.id===pickOutlet)?.name || pickOutlet} tersimpan`); }
    catch (e) { notify(e.response?.data?.detail || "Gagal simpan"); }
  };
  const previewLink = `${ORIGIN}/self-order?table=05&outlet_id=${pickOutlet}`;
  return <>
    <SectionHeader eyebrow="SELF-SERVICE STUDIO" title="Pengaturan Self-Service & QR Meja" description="Kelola banner, marquee, logo, dan status buka/tutup per outlet."
      action={<div className="row-gap">
        <label className="outlet-picker" data-testid="self-service-outlet-picker-wrap">
          <Building2 size={14}/>
          <select value={pickOutlet || ""} onChange={(e) => setPickOutlet(e.target.value)} data-testid="self-service-outlet-picker">
            {validOutlets.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </label>
        <a className="outline-btn" href={previewLink} target="_blank" rel="noreferrer" data-testid="preview-self-order"><QrCode size={14}/> Preview Order</a>
        <button className="primary-btn" onClick={save} disabled={loading} data-testid="save-self-service"><Check size={14}/> Simpan Pengaturan</button>
      </div>} />
    <div className="ss-grid">
      <section className="panel ss-panel">
        <div className="form-heading"><div className="form-icon"><StopCircle size={18}/></div>
          <div><h2>Status Toko</h2><span>Shift kasir: <b className={shiftOpen ? "" : "danger"}>{shiftOpen ? "AKTIF (buka)" : "BELUM DIBUKA"}</b></span></div>
        </div>
        <div className="ss-status-row">
          <label className="switch-lg">
            <input type="checkbox" checked={settings.force_closed} onChange={(e) => upd({ force_closed: e.target.checked })} data-testid="ss-force-closed-toggle"/>
            <i/>
            <span>{settings.force_closed ? "TERPAKSA TUTUP" : "IKUTI SHIFT KASIR"}</span>
          </label>
          <label className="ss-full">Pesan penutupan (opsional)
            <input value={settings.closed_message} onChange={(e) => upd({ closed_message: e.target.value })} placeholder="Contoh: Sedang cuti bersama, buka kembali besok pkl 08.00" data-testid="ss-closed-msg"/>
          </label>
        </div>
      </section>
      <section className="panel ss-panel">
        <div className="form-heading"><div className="form-icon"><Store size={18}/></div>
          <div><h2>Logo & Header</h2><span>Logo bulat di header + header image opsional</span></div>
        </div>
        <div className="ss-media-row">
          <label className="ss-media">
            <b>Logo Outlet</b>
            {settings.logo_url ? <img src={settings.logo_url} alt="logo" className="ss-logo-preview"/> : <div className="ss-media-empty"><Store size={26}/></div>}
            <input type="file" accept="image/*" onChange={upload("logo_url")} data-testid="ss-logo-input"/>
          </label>
          <label className="ss-media wide">
            <b>Header Image (opsional)</b>
            {settings.header_image ? <img src={settings.header_image} alt="header" className="ss-header-preview"/> : <div className="ss-media-empty"><ImageIcon size={26}/></div>}
            <input type="file" accept="image/*" onChange={upload("header_image")} data-testid="ss-header-input"/>
          </label>
        </div>
      </section>
      <section className="panel ss-panel span-2">
        <div className="form-heading"><div className="form-icon"><ImageIcon size={18}/></div>
          <div><h2>Banner Promo (Carousel)</h2><span>Multi-banner untuk hero self-order · disarankan 1200×400px</span></div>
        </div>
        <div className="ss-banners">
          {(settings.banners || []).map((b, i) => <div className="ss-banner-thumb" key={i}>
            <img src={b} alt={`banner-${i}`}/>
            <button className="icon-danger" onClick={() => removeBanner(i)} data-testid={`remove-banner-${i}`}><X size={13}/></button>
          </div>)}
          <label className="ss-banner-add">
            <Plus size={20}/>
            <span>Tambah Banner</span>
            <input type="file" accept="image/*" onChange={addBanner} data-testid="add-banner-input"/>
          </label>
        </div>
      </section>
      <section className="panel ss-panel span-2">
        <div className="form-heading"><div className="form-icon"><Bell size={18}/></div>
          <div><h2>Marquee / Pengumuman Berjalan</h2><span>Teks berjalan di atas halaman self-order</span></div>
        </div>
        <input className="ss-marquee-input" value={settings.marquee_text} onChange={(e) => upd({ marquee_text: e.target.value })} placeholder="Contoh: 🎉 Diskon Kopi 20% s/d 20 Feb! · Menu baru: Kopi Pandan · Wi-Fi: kopi123" data-testid="ss-marquee-input"/>
        {settings.marquee_text && <div className="ss-marquee-preview" data-testid="ss-marquee-preview"><div className="marquee-text">{settings.marquee_text} · {settings.marquee_text}</div></div>}
      </section>
    </div>
  </>;
}

// -------- Vendor center --------
function VendorCenter({ notify }) {
  const [orders, setOrders] = useState([]);
  const [settlement, setSettlement] = useState({ gross: 0, commission: 0, net: 0, payout_status: "Memuat" });
  const [preview, setPreview] = useState({ breakdown: [], totals: { gross: 0, commission: 0, net: 0, item_count: 0 } });
  const [payouts, setPayouts] = useState([]);
  const [tab, setTab] = useState("queue"); // queue | settlement | payouts
  const today = new Date().toISOString().slice(0, 10);
  const firstOfMonth = new Date(); firstOfMonth.setDate(1);
  const [period, setPeriod] = useState({ from: firstOfMonth.toISOString().slice(0, 10), to: today });
  const [payoutModal, setPayoutModal] = useState(null); // { merchant_id, merchant_name, ... }

  const load = () => {
    axios.get(`${API}/vendor/orders`).then(({ data }) => setOrders(data)).catch(() => {});
    axios.get(`${API}/vendor/settlement`).then(({ data }) => setSettlement(data)).catch(() => {});
  };
  const loadPreview = () => {
    const params = new URLSearchParams({ date_from: period.from, date_to: period.to });
    axios.get(`${API}/settlement/preview?${params.toString()}`).then(({ data }) => setPreview(data)).catch(() => {});
  };
  const loadPayouts = () => axios.get(`${API}/settlement/payouts`).then(({ data }) => setPayouts(data)).catch(() => {});

  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  useEffect(() => { if (tab === "settlement") loadPreview(); if (tab === "payouts") loadPayouts(); /* eslint-disable-next-line */ }, [tab, period.from, period.to]);

  const update = (id, status) => axios.patch(`${API}/vendor/orders/${id}?status=${encodeURIComponent(status)}`).then(load).then(() => notify("Status order diperbarui"));

  const submitPayout = async (note) => {
    if (!payoutModal) return;
    try {
      await axios.post(`${API}/settlement/payouts`, {
        merchant_id: payoutModal.merchant_id,
        period_start: period.from,
        period_end: period.to,
        note: note || "",
      });
      notify(`Payout ${payoutModal.merchant_name} sebesar ${money(payoutModal.net)} tercatat`);
      setPayoutModal(null); loadPreview(); loadPayouts();
    } catch (e) { notify(e.response?.data?.detail || "Gagal membuat payout"); }
  };

  return <>
    <SectionHeader eyebrow="VENDOR OPERATIONS" title="Pusat vendor" description="Antrean dapur, settlement per-merchant, dan riwayat payout."
      action={<button className="outline-btn" data-testid="refresh-vendor-button" onClick={load}><Bell size={15} /> Refresh</button>} />
    <div className="vendor-metrics">
      <Metric label="Omset tenant" value={money(settlement.gross)} change="periode berjalan" tone="orange" icon={Receipt} />
      <Metric label="Komisi platform" value={money(settlement.commission)} change="rata-rata 10%" tone="blue" icon={BarChart3} />
      <Metric label="Net payout" value={money(settlement.net)} change={settlement.payout_status} tone="green" icon={Wallet} />
    </div>
    <div className="ft-tabs" style={{ marginBottom: 12 }}>
      <button className={tab === "queue" ? "active" : ""} onClick={() => setTab("queue")} data-testid="vendor-tab-queue"><ChefHat size={14} /> Antrean Order</button>
      <button className={tab === "settlement" ? "active" : ""} onClick={() => setTab("settlement")} data-testid="vendor-tab-settlement"><Wallet size={14} /> Settlement per Merchant</button>
      <button className={tab === "payouts" ? "active" : ""} onClick={() => setTab("payouts")} data-testid="vendor-tab-payouts"><FileText size={14} /> Riwayat Payout</button>
    </div>
    {tab === "queue" && <div className="vendor-grid">
      <section className="panel vendor-queue">
        <div className="panel-head"><div><h2>Antrean self-order</h2><span>Otomatis polling 5 detik</span></div><span className="live-pill"><i /> Live</span></div>
        {orders.length ? orders.map((order) => <div className="order-ticket" key={order.id}>
          <div><b>#{String(order.id).slice(-6)} · {order.table_no}</b><span>{order.lines?.map((line) => `${line.quantity}× ${line.name}`).join(", ")}</span></div>
          <select value={order.status} onChange={(e) => update(order.id, e.target.value)} data-testid={`order-status-${order.id}`}>
            <option>Menunggu kasir</option><option>Diproses</option><option>Siap diambil</option><option>Selesai</option>
          </select>
        </div>) : <div className="empty-vendor"><ChefHat size={30} /><b>Antrean masih kosong</b><span>Pesanan self-service baru akan tampil di sini</span></div>}
      </section>
      <section className="panel payout-card">
        <div className="panel-head"><div><h2>Ringkasan platform</h2><span>Snapshot cepat</span></div></div>
        <div className="settlement-line"><span>Omset kotor</span><b>{money(settlement.gross)}</b></div>
        <div className="settlement-line"><span>Komisi platform</span><b className="red-text">−{money(settlement.commission)}</b></div>
        <div className="settlement-line net"><span>Total net vendor</span><strong>{money(settlement.net)}</strong></div>
        <button className="primary-btn full" data-testid="vendor-goto-settlement" onClick={() => setTab("settlement")}>Buka Settlement Center <span>→</span></button>
      </section>
    </div>}
    {tab === "settlement" && <>
      <section className="panel" data-testid="settlement-panel">
        <div className="panel-head">
          <div><h2>Settlement per-merchant</h2><span>Bagi hasil otomatis berdasarkan skema komisi setiap merchant</span></div>
          <div className="row-gap">
            <label><small style={{ display: "block", fontSize: 11, color: "#6b7280" }}>Dari</small><input type="date" value={period.from} onChange={(e) => setPeriod({ ...period, from: e.target.value })} data-testid="period-from" /></label>
            <label><small style={{ display: "block", fontSize: 11, color: "#6b7280" }}>Sampai</small><input type="date" value={period.to} onChange={(e) => setPeriod({ ...period, to: e.target.value })} data-testid="period-to" /></label>
            <button className="outline-btn" onClick={loadPreview} data-testid="settlement-reload"><RefreshCw size={14} /> Hitung</button>
          </div>
        </div>
        <div className="metric-grid three" style={{ marginTop: 12 }}>
          <Metric label="Omset periode" value={money(preview.totals.gross)} change={`${preview.totals.item_count} item terjual`} tone="orange" icon={Receipt} />
          <Metric label="Komisi platform" value={money(preview.totals.commission)} change={`${preview.breakdown.length} merchant`} tone="blue" icon={BarChart3} />
          <Metric label="Net vendor" value={money(preview.totals.net)} change="Bersih ke tenant" tone="green" icon={Wallet} />
        </div>
        <div className="data-table" style={{ marginTop: 16 }}>
          <div className="table-row table-label"><span>Merchant</span><span>Item</span><span>Skema</span><span>Gross</span><span>Komisi</span><span>Net</span><span /></div>
          {!preview.breakdown.length && <div className="empty-vendor"><Wallet size={30} /><b>Belum ada omset di periode ini</b><span>Ubah rentang tanggal atau lakukan transaksi POS</span></div>}
          {preview.breakdown.map((b) => <div className="table-row" key={b.merchant_id} data-testid={`settlement-row-${b.merchant_id}`}>
            <span><b>{b.merchant_name}</b></span>
            <span>{b.item_count}</span>
            <span><small>{b.commission_scheme === "fixed" ? `Fix ${money(b.commission_fixed)}/item` : `${b.commission_percent}%`}</small></span>
            <span><b>{money(b.gross)}</b></span>
            <span className="red-text">−{money(b.commission)}</span>
            <span style={{ color: "#059669", fontWeight: 700 }}>{money(b.net)}</span>
            <button className="primary-btn" style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => setPayoutModal(b)} data-testid={`payout-btn-${b.merchant_id}`}>Bayar →</button>
          </div>)}
        </div>
      </section>
    </>}
    {tab === "payouts" && <>
      <section className="panel" data-testid="payouts-panel">
        <div className="panel-head"><div><h2>Riwayat payout</h2><span>{payouts.length} entri tercatat</span></div><button className="outline-btn" onClick={loadPayouts}><RefreshCw size={14}/> Refresh</button></div>
        <div className="data-table">
          <div className="table-row table-label"><span>Tanggal</span><span>Merchant</span><span>Periode</span><span>Item</span><span>Gross</span><span>Net</span><span>Status</span></div>
          {!payouts.length && <div className="empty-vendor"><FileText size={30} /><b>Belum ada payout tercatat</b><span>Buat payout dari tab Settlement</span></div>}
          {payouts.map((p) => <div className="table-row" key={p.id} data-testid={`payout-row-${p.id}`}>
            <span><small>{new Date(p.created_at).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" })}</small></span>
            <span><b>{p.merchant_id?.slice(0, 12)}…</b></span>
            <span><small>{p.period_start} → {p.period_end}</small></span>
            <span>{p.item_count}</span>
            <span>{money(p.gross)}</span>
            <span style={{ color: "#059669", fontWeight: 700 }}>{money(p.net)}</span>
            <span><span className="method-badge" style={{ background: "#dcfce7", color: "#166534" }}>{p.status}</span></span>
          </div>)}
        </div>
      </section>
    </>}
    {payoutModal && <PayoutConfirmModal entry={payoutModal} period={period} onClose={() => setPayoutModal(null)} onConfirm={submitPayout} />}
  </>;
}

function PayoutConfirmModal({ entry, period, onClose, onConfirm }) {
  const [note, setNote] = useState("");
  return <div className="modal-backdrop"><div className="pay-modal" data-testid="payout-confirm-modal">
    <button className="modal-close" onClick={onClose}><X size={18}/></button>
    <div className="pay-head"><h2>Konfirmasi Payout</h2><span>Merchant: {entry.merchant_name}</span></div>
    <div className="pay-body">
      <div className="bind-info"><b>Periode</b><span>{period.from} → {period.to}</span><b>Total Item</b><span>{entry.item_count}</span><b>Gross</b><span>{money(entry.gross)}</span><b>Komisi</b><span className="red-text">−{money(entry.commission)}</span><b>Net Payout</b><span style={{ color: "#059669", fontWeight: 700 }}>{money(entry.net)}</span></div>
      <label>Catatan (opsional)</label>
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Contoh: Transfer BCA 04/12" data-testid="payout-note-input" />
    </div>
    <button className="primary-btn full" onClick={() => onConfirm(note)} data-testid="payout-confirm-button"><Check size={14}/> Bayar {money(entry.net)}</button>
  </div></div>;
}

// -------- Settings (Printer + Branding + Outlets, Super Admin only) --------
function SettingsPage({ notify, role, brandingText, onBrandingTextSaved, onFeatureToggleSaved, pinDisabled }) {
  const [printer, setPrinter] = useState({ size: "58mm", auto_print: true, split_kitchen: true, device: "Bluetooth" });
  const [logo, setLogo] = useState("");
  const [outlets, setOutlets] = useState([]);
  const [outletForm, setOutletForm] = useState({ name: "", address: "", phone: "" });
  const [pairName, setPairName] = useState(pairedPrinterName());
  const [connected, setConnected] = useState(isPrinterConnected());
  const isSuper = role === "Super Admin";

  const loadOutlets = () => axios.get(`${API}/outlets?include_inactive=1`).then(({ data }) => setOutlets(data)).catch(() => {});
  useEffect(() => {
    axios.get(`${API}/settings/printer`).then(({ data }) => { if (data && Object.keys(data).length) setPrinter((p) => ({ ...p, ...data })); }).catch(() => {});
    axios.get(`${API}/settings/logo`).then(({ data }) => setLogo(data?.logo_data || "")).catch(() => {});
    loadOutlets();
    const t = setInterval(() => setConnected(isPrinterConnected()), 2000);
    return () => clearInterval(t);
  }, []);

  const savePrinter = async () => { await axios.post(`${API}/settings`, { key: "printer", value: printer }); notify("Pengaturan printer tersimpan"); };
  const saveLogo = async (dataUrl) => { setLogo(dataUrl); await axios.post(`${API}/settings`, { key: "logo", value: { logo_data: dataUrl } }); notify("Logo diperbarui — akan muncul di navbar & struk"); };
  const handleLogo = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => saveLogo(r.result); r.readAsDataURL(f); };
  const pair = async () => { try { const { name } = await pairPrinter(); setPairName(name); setConnected(true); notify(`Printer "${name}" tersambung`); } catch (e) { notify(e.message || "Gagal sambung printer"); } };
  const saveOutlet = async () => {
    if (!outletForm.name) return notify("Nama outlet wajib");
    try {
      await axios.post(`${API}/outlets`, outletForm);
      setOutletForm({ name: "", address: "", phone: "" }); loadOutlets(); notify("Outlet ditambahkan");
    } catch (e) { notify(e.response?.data?.detail || "Gagal menambahkan outlet"); }
  };
  const deleteOutlet = async (o) => {
    const active = o.active !== false;
    const label = active ? "nonaktifkan" : "AKTIFKAN kembali";
    if (!window.confirm(`Yakin ${label} outlet "${o.name}"?\n\n${active ? "⚠️ Semua user pada outlet ini akan diblokir login. Data historis tetap tersimpan." : "User yang tadinya nonaktif harus di-aktifkan ulang manual dari halaman User & Security."}`)) return;
    try {
      if (active) {
        const { data } = await axios.delete(`${API}/outlets/${o.id}`);
        loadOutlets();
        notify(`✅ Outlet "${o.name}" dinonaktifkan (${data.affected_users} user auto-blocked)`);
      } else {
        await axios.put(`${API}/outlets/${o.id}`, { name: o.name, address: o.address || "", active: true });
        loadOutlets();
        notify(`✅ Outlet "${o.name}" aktif kembali`);
      }
    } catch (e) { notify(`❌ ${e.response?.data?.detail || "Gagal"}`); }
  };

  return <>
    <SectionHeader eyebrow="OPERATIONS" title="Pengaturan Sistem" description="Printer thermal, branding, dan multi-outlet." />
    <section className="panel product-form-v2">
      <div className="form-heading"><div className="form-icon"><Bluetooth size={18} /></div>
        <div><h2>Printer thermal (Web Bluetooth ESC/POS)</h2><span>{isPrinterSupported() ? "Chrome/Edge di HP atau desktop mendukung fitur ini" : "⚠️ Browser tidak mendukung Web Bluetooth"}</span></div>
      </div>
      <div className="form-fields" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
        <label><span>Ukuran kertas</span><select value={printer.size} onChange={(e) => setPrinter({ ...printer, size: e.target.value })} data-testid="printer-size-select"><option>58mm</option><option>80mm</option></select></label>
        <label><span>Device</span><select value={printer.device} onChange={(e) => setPrinter({ ...printer, device: e.target.value })} data-testid="printer-device-select"><option>Bluetooth</option><option>USB</option><option>Network</option></select></label>
        <label><span>Auto-print</span><select value={String(printer.auto_print)} onChange={(e) => setPrinter({ ...printer, auto_print: e.target.value === "true" })} data-testid="printer-auto-select"><option value="true">Aktif</option><option value="false">Nonaktif</option></select></label>
        <label><span>Split kitchen</span><select value={String(printer.split_kitchen)} onChange={(e) => setPrinter({ ...printer, split_kitchen: e.target.value === "true" })} data-testid="printer-split-select"><option value="true">Per merchant</option><option value="false">Satu struk</option></select></label>
      </div>
      <div className="printer-status-row">
        <div className={`printer-status ${connected ? "on" : ""}`} data-testid="printer-status"><i /> {connected ? `Terhubung: ${pairName || "printer"}` : "Belum tersambung"}</div>
        <div className="row-gap">
          <button className="outline-btn" onClick={pair} data-testid="pair-printer-button"><Bluetooth size={14} /> Pair Bluetooth</button>
          <button className="primary-btn" onClick={savePrinter} data-testid="save-printer-button"><Check size={14} /> Simpan pengaturan</button>
        </div>
      </div>
    </section>

    {isSuper && <>
      <BrandingTextSettings notify={notify} initial={brandingText} onSaved={onBrandingTextSaved} />
      <section className="panel product-form-v2">
        <div className="form-heading"><div className="form-icon"><ImageIcon size={18} /></div>
          <div><h2>Logo usaha</h2><span>Otomatis muncul di Navbar, Dashboard, dan Struk Thermal</span></div>
        </div>
        <div className="brand-row">
          <div className="brand-preview">
            {logo ? <img src={logo} alt="logo" /> : <Coffee size={44} color="#f97316" />}
          </div>
          <div>
            <label className="upload-btn" data-testid="upload-logo-label"><Upload size={14} /> Upload Logo PNG/JPG<input type="file" accept="image/*" onChange={handleLogo} style={{ display: "none" }} data-testid="logo-upload-input" /></label>
            {logo && <button className="outline-btn" onClick={() => saveLogo("")} data-testid="remove-logo-button">Hapus logo</button>}
          </div>
        </div>
      </section>

      <section className="panel product-form-v2">
        <div className="form-heading"><div className="form-icon"><Building2 size={18} /></div>
          <div><h2>Manajemen Multi-Outlet</h2><span>Cabang / lokasi outlet (data muncul di struk)</span></div>
        </div>
        <div className="form-fields" style={{ gridTemplateColumns: "1.4fr 1.8fr 1fr auto" }}>
          <label><span>Nama outlet</span><input value={outletForm.name} onChange={(e) => setOutletForm({ ...outletForm, name: e.target.value })} data-testid="outlet-name-input" /></label>
          <label><span>Alamat</span><input value={outletForm.address} onChange={(e) => setOutletForm({ ...outletForm, address: e.target.value })} data-testid="outlet-address-input" /></label>
          <label><span>No. Telp</span><input value={outletForm.phone} onChange={(e) => setOutletForm({ ...outletForm, phone: e.target.value })} data-testid="outlet-phone-input" /></label>
          <button className="primary-btn" onClick={saveOutlet} data-testid="save-outlet-button"><Plus size={14} /> Tambah</button>
        </div>
        <div className="data-table" style={{ marginTop: 12 }}>
          <div className="table-row outlet-row table-label"><span>Outlet</span><span>Alamat</span><span>Telp</span><span>Status</span><span /></div>
          {outlets.map((o) => <div className="table-row outlet-row" key={o.id} data-testid={`outlet-row-${o.id}`}>
            <span><b>{o.name}</b></span>
            <span>{o.address || "-"}</span>
            <span>{o.phone || "-"}</span>
            <span><i className={`status-dot ${o.active ? "good" : "low"}`} />{o.active ? "Aktif" : "Nonaktif"}</span>
            <button className={`small-action ${o.active !== false ? "" : "green"}`} onClick={() => deleteOutlet(o)} data-testid={`delete-outlet-${o.id}`}>
              {o.active !== false ? <><Trash2 size={12} /> Nonaktifkan</> : <><Check size={12} /> Aktifkan</>}
            </button>
          </div>)}
        </div>
      </section>
    </>}
    {(role === "Super Admin" || role === "Admin") && <PaymentSettings notify={notify} />}
    {(role === "Super Admin" || role === "Admin") && <TaxSettings notify={notify} />}
    {(role === "Super Admin" || role === "Admin") && <SoundSettings notify={notify} />}
    {(role === "Super Admin" || role === "Admin") && <PinGenerator notify={notify} disabled={pinDisabled} />}
    {isSuper && <FeatureToggleMatrix notify={notify} outlets={outlets} onSaved={onFeatureToggleSaved} />}
  </>;
}

// -------- Branding Text Settings (Brand Name + Subtitle) --------
function BrandingTextSettings({ notify, initial, onSaved }) {
  const [form, setForm] = useState({ name: initial?.name || "MJD Kupi", subtitle: initial?.subtitle || "Retail Command Center" });
  useEffect(() => { setForm({ name: initial?.name || "MJD Kupi", subtitle: initial?.subtitle || "Retail Command Center" }); }, [initial?.name, initial?.subtitle]);
  const save = async () => {
    const payload = { name: form.name.trim() || "MJD Kupi", subtitle: form.subtitle.trim() || "Retail Command Center" };
    try {
      await axios.post(`${API}/settings`, { key: "branding_text", value: payload });
      if (onSaved) onSaved(payload);
      notify(`Brand diperbarui: ${payload.name} · ${payload.subtitle}`);
    } catch (e) { notify(e.response?.data?.detail || "Gagal simpan branding"); }
  };
  return <section className="panel product-form-v2" data-testid="branding-text-panel">
    <div className="form-heading"><div className="form-icon"><Store size={18}/></div>
      <div><h2>Identitas Brand</h2><span>Nama & tagline muncul di sidebar, topbar, login, dan struk</span></div>
    </div>
    <div className="form-fields" style={{ gridTemplateColumns: "1fr 1.4fr auto" }}>
      <label><span>Nama Usaha / Brand</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="MJD Kupi" data-testid="branding-name-input" /></label>
      <label><span>Subtitle / Tagline</span><input value={form.subtitle} onChange={(e) => setForm({ ...form, subtitle: e.target.value })} placeholder="Retail Command Center" data-testid="branding-subtitle-input" /></label>
      <button className="primary-btn" onClick={save} data-testid="save-branding-text-button"><Check size={14}/> Simpan Brand</button>
    </div>
    <div className="empty-hint" style={{ marginTop: 8, background: "#fff7ed", color: "#9a3412" }}>
      Preview: <b>{form.name}</b> · <em>{form.subtitle}</em>
    </div>
  </section>;
}

// -------- PPN / Tax Settings (Feature #7.3) --------
function TaxSettings({ notify }) {
  const [cfg, setCfg] = useState({ enabled: false, percent: 10 });
  useEffect(() => {
    axios.get(`${API}/settings/tax_config`).then(({ data }) => {
      if (data && typeof data === "object") setCfg({ enabled: !!data.enabled, percent: Number(data.percent || 10) });
    }).catch(() => {});
  }, []);
  const save = async () => {
    try {
      await axios.post(`${API}/settings`, { key: "tax_config", value: { enabled: cfg.enabled, percent: Number(cfg.percent) } });
      notify(cfg.enabled ? `PPN ${cfg.percent}% aktif — akan diterapkan di POS & struk` : "PPN dinonaktifkan (0%)");
    } catch (e) { notify("Gagal simpan pengaturan PPN"); }
  };
  return <section className="panel product-form-v2" data-testid="tax-settings-panel">
    <div className="form-heading"><div className="form-icon"><Receipt size={18}/></div>
      <div><h2>Pajak / PPN Restoran</h2><span>Aktif/nonaktifkan pajak restoran. Diterapkan real-time di POS, Self-Order, dan struk.</span></div>
    </div>
    <div className="tax-row">
      <label className="switch-lg" data-testid="tax-toggle-wrapper">
        <input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} data-testid="tax-toggle" />
        <i />
        <span>{cfg.enabled ? "PPN AKTIF" : "PPN NONAKTIF"}</span>
      </label>
      <label className="tax-percent">
        <span>Persentase PPN (%)</span>
        <input type="number" value={cfg.percent} min={0} max={20} disabled={!cfg.enabled}
          onFocus={numOnFocus} onChange={(e) => setCfg({ ...cfg, percent: Number(e.target.value) })}
          data-testid="tax-percent-input" />
      </label>
      <div className="tax-preview" data-testid="tax-preview">
        <b>Preview subtotal Rp 100.000</b>
        <span>Total: {money(100000 + (cfg.enabled ? Math.round(100000 * cfg.percent / 100) : 0))}</span>
      </div>
      <button className="primary-btn" onClick={save} data-testid="save-tax-config"><Check size={14}/> Simpan</button>
    </div>
  </section>;
}

// -------- Sound Notification Settings (Batch C bonus) --------
function SoundSettings({ notify }) {
  const [cfg, setCfg] = useState({ enabled: true, volume: 70, chime_new_order: true, chime_kds_ready: true });
  useEffect(() => {
    axios.get(`${API}/settings/sound_config`).then(({ data }) => {
      if (data && typeof data === "object" && "enabled" in data) setCfg((c) => ({ ...c, ...data }));
    }).catch(() => {});
  }, []);
  const save = async () => {
    try {
      await axios.post(`${API}/settings`, { key: "sound_config", value: cfg });
      try { localStorage.setItem("mjd_sound_config", JSON.stringify(cfg)); } catch {}
      notify(cfg.enabled ? `Suara notifikasi ON — volume ${cfg.volume}%` : "Suara notifikasi dinonaktifkan");
    } catch (e) { notify("Gagal simpan pengaturan suara"); }
  };
  const testChime = () => {
    if (!cfg.enabled) return notify("Aktifkan dulu untuk test");
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator(); const g = ctx.createGain();
      o.type = "sine"; o.frequency.value = 880;
      g.gain.value = (cfg.volume / 100) * 0.35;
      o.connect(g).connect(ctx.destination); o.start();
      setTimeout(() => { o.frequency.value = 1174; }, 120);
      setTimeout(() => { o.stop(); ctx.close(); }, 380);
    } catch { notify("Browser tidak mendukung Web Audio"); }
  };
  return <section className="panel product-form-v2" data-testid="sound-settings-panel">
    <div className="form-heading"><div className="form-icon"><Volume2 size={18}/></div>
      <div><h2>Notifikasi Suara</h2><span>Chime saat pesanan baru masuk & tiket siap diambil di KDS</span></div>
    </div>
    <div className="tax-row">
      <label className="switch-lg" data-testid="sound-toggle-wrapper">
        <input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} data-testid="sound-toggle" />
        <i />
        <span>{cfg.enabled ? "SUARA AKTIF" : "SUARA NONAKTIF"}</span>
      </label>
      <label className="tax-percent">
        <span>Volume ({cfg.volume}%)</span>
        <input type="range" min={0} max={100} value={cfg.volume} disabled={!cfg.enabled}
          onChange={(e) => setCfg({ ...cfg, volume: Number(e.target.value) })}
          data-testid="sound-volume-input" />
      </label>
      <div className="row-gap">
        <button className="outline-btn" onClick={testChime} data-testid="sound-test-button" disabled={!cfg.enabled}><Volume2 size={14}/> Tes Chime</button>
        <button className="primary-btn" onClick={save} data-testid="save-sound-config"><Check size={14}/> Simpan</button>
      </div>
    </div>
    <div className="form-fields" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 12 }}>
      <label><input type="checkbox" checked={cfg.chime_new_order} onChange={(e) => setCfg({ ...cfg, chime_new_order: e.target.checked })} data-testid="chime-new-order-toggle" disabled={!cfg.enabled} /> <span>🔔 Bunyikan saat pesanan online baru masuk</span></label>
      <label><input type="checkbox" checked={cfg.chime_kds_ready} onChange={(e) => setCfg({ ...cfg, chime_kds_ready: e.target.checked })} data-testid="chime-kds-toggle" disabled={!cfg.enabled} /> <span>👨‍🍳 Bunyikan saat pesanan KDS "Siap diambil"</span></label>
    </div>
  </section>;
}

// -------- Feature Toggle Matrix (Super Admin only) --------
const ROLE_LIST = ["Super Admin", "Admin", "Kasir", "Vendor"];
const FEATURE_LIST = [
  { key: "overview", label: "Ringkasan Dashboard" },
  { key: "pos", label: "Terminal POS" },
  { key: "self-service", label: "Customer Self-Order" },
  { key: "kds", label: "Kitchen Display (KDS)" },
  { key: "inventory", label: "Inventori & Stok" },
  { key: "expenses", label: "Pengeluaran" },
  { key: "reports", label: "Laporan Keuangan" },
  { key: "products", label: "Produk & HPP" },
  { key: "merchants", label: "Merchant / Tenant" },
  { key: "cashiers", label: "Monitoring Kasir" },
  { key: "tables", label: "QR Meja" },
  { key: "vendor-center", label: "Pusat Vendor" },
  { key: "users", label: "User & Security" },
  { key: "printer", label: "Pengaturan Printer" },
  { key: "settings", label: "Pengaturan Sistem" },
  { key: "cashier_pin", label: "Kode Otorisasi Kasir (PIN)" },
];

function FeatureToggleMatrix({ notify, outlets, onSaved }) {
  const [matrix, setMatrix] = useState({});
  const [mode, setMode] = useState("role"); // role | outlet
  const [target, setTarget] = useState("Kasir");
  useEffect(() => {
    axios.get(`${API}/feature-toggles`).then(({ data }) => setMatrix(data?.matrix || {})).catch(() => {});
  }, []);
  useEffect(() => {
    if (mode === "outlet" && outlets?.length && !outlets.some(o => o.id === target)) setTarget(outlets[0].id);
    if (mode === "role" && !ROLE_LIST.includes(target)) setTarget("Kasir");
  }, [mode, outlets]);
  const key = mode === "role" ? `role:${target}` : `outlet:${target}`;
  const scope = matrix[key] || {};
  const toggle = (fkey) => setMatrix((m) => {
    const cur = { ...(m[key] || {}) };
    cur[fkey] = cur[fkey] === false ? true : false;
    return { ...m, [key]: cur };
  });
  const allOn = () => setMatrix((m) => ({ ...m, [key]: Object.fromEntries(FEATURE_LIST.map(f => [f.key, true])) }));
  const allOff = () => setMatrix((m) => ({ ...m, [key]: Object.fromEntries(FEATURE_LIST.map(f => [f.key, false])) }));
  const save = async () => {
    try {
      await axios.post(`${API}/feature-toggles`, { matrix });
      notify("Feature toggles tersimpan — sidebar akan langsung diperbarui");
      if (onSaved) onSaved();
    } catch (e) { notify(e.response?.data?.detail || "Gagal simpan"); }
  };
  return <section className="panel product-form-v2" data-testid="feature-toggle-panel">
    <div className="form-heading"><div className="form-icon"><Shield size={18}/></div>
      <div><h2>Feature Access Control</h2><span>Aktif/Non-aktifkan modul per Role atau per Outlet — sidebar user akan otomatis filter</span></div>
    </div>
    <div className="ft-tabs">
      <button className={mode === "role" ? "active" : ""} onClick={() => setMode("role")} data-testid="ft-mode-role">Per Role</button>
      <button className={mode === "outlet" ? "active" : ""} onClick={() => setMode("outlet")} data-testid="ft-mode-outlet">Per Outlet</button>
      <select value={target} onChange={(e) => setTarget(e.target.value)} data-testid="ft-target-select">
        {mode === "role" ? ROLE_LIST.map(r => <option key={r}>{r}</option>)
                        : (outlets || []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
      <button className="outline-btn" onClick={allOn} data-testid="ft-all-on" style={{ marginLeft: 8 }}>Aktifkan Semua</button>
      <button className="outline-btn" onClick={allOff} data-testid="ft-all-off">Matikan Semua</button>
    </div>
    <div className="ft-grid">
      {FEATURE_LIST.map((f) => {
        const on = scope[f.key] !== false;
        return <label key={f.key} className={`ft-cell ${on ? "on" : "off"}`} data-testid={`ft-${f.key}`}>
          <input type="checkbox" checked={on} onChange={() => toggle(f.key)} data-testid={`ft-toggle-${f.key}`} />
          <b>{f.label}</b>
          <span>{on ? "Aktif" : "Nonaktif"}</span>
        </label>;
      })}
    </div>
    <div className="modal-actions">
      <button className="primary-btn" onClick={save} data-testid="save-feature-toggles"><Check size={14}/> Simpan Feature Toggles</button>
    </div>
  </section>;
}

// -------- Payment Settings: Bank Accounts + QRIS image --------
function PaymentSettings({ notify }) {
  const [banks, setBanks] = useState([]);
  const [form, setForm] = useState({ bank_name: "", account_number: "", holder_name: "" });
  const [qrisImg, setQrisImg] = useState("");
  const load = () => {
    axios.get(`${API}/settings/bank-accounts`).then(({ data }) => setBanks(data?.accounts || [])).catch(() => {});
    axios.get(`${API}/settings/qris-image:outlet-sudirman`).then(({ data }) => setQrisImg(data?.image || "")).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  const add = async () => {
    if (!form.bank_name || !form.account_number || !form.holder_name) return notify("Lengkapi data rekening");
    try { await axios.post(`${API}/settings/bank-accounts`, form); setForm({ bank_name: "", account_number: "", holder_name: "" }); load(); notify("Rekening ditambahkan"); }
    catch { notify("Gagal menambahkan rekening"); }
  };
  const remove = async (id) => { if (!window.confirm("Hapus rekening ini?")) return; await axios.delete(`${API}/settings/bank-accounts/${id}`); load(); notify("Rekening dihapus"); };
  const handleQris = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = async () => { setQrisImg(r.result); await axios.post(`${API}/settings`, { key: "qris-image:outlet-sudirman", value: { image: r.result } }); notify("QRIS Toko diperbarui"); }; r.readAsDataURL(f); };
  return <section className="panel product-form-v2">
    <div className="form-heading"><div className="form-icon"><CreditCard size={18} /></div><div><h2>Pengaturan Pembayaran Toko</h2><span>Rekening Bank & QRIS Toko untuk Self-Order dan Kasir</span></div></div>
    <div className="form-fields" style={{ gridTemplateColumns: "1.2fr 1.4fr 1.4fr auto" }}>
      <label><span>Nama Bank</span><input value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} placeholder="Contoh: BCA" data-testid="bank-name-input" /></label>
      <label><span>Nomor Rekening</span><input value={form.account_number} onChange={(e) => setForm({ ...form, account_number: e.target.value })} placeholder="4820011..." data-testid="bank-account-input" /></label>
      <label><span>Atas Nama</span><input value={form.holder_name} onChange={(e) => setForm({ ...form, holder_name: e.target.value })} placeholder="Nama Pemilik" data-testid="bank-holder-input" /></label>
      <button className="primary-btn" onClick={add} data-testid="add-bank-button"><Plus size={14}/> Tambah</button>
    </div>
    <div className="data-table" style={{ marginTop: 12 }}>
      <div className="table-row bank-row table-label"><span>Bank</span><span>Nomor</span><span>Atas Nama</span><span /></div>
      {banks.map((b) => <div className="table-row bank-row" key={b.id} data-testid={`bank-row-${b.id}`}>
        <span><b>{b.bank_name}</b></span><span className="mono">{b.account_number}</span><span>{b.holder_name}</span>
        <button className="small-action" onClick={() => remove(b.id)} data-testid={`delete-bank-${b.id}`}><Trash2 size={12}/></button>
      </div>)}
      {banks.length === 0 && <div className="empty-vendor" style={{ padding: "20px 0" }}><CreditCard size={20} /><b>Belum ada rekening</b></div>}
    </div>
    <div className="brand-row" style={{ marginTop: 16 }}>
      <div className="brand-preview" data-testid="qris-preview">
        {qrisImg ? <img src={qrisImg} alt="QRIS Toko" /> : <QrCode size={44} color="#f97316" />}
      </div>
      <div>
        <label className="upload-btn" data-testid="upload-qris-label"><Upload size={14} /> Upload QRIS Toko<input type="file" accept="image/*" onChange={handleQris} style={{ display: "none" }} data-testid="qris-image-input" /></label>
      </div>
    </div>
  </section>;
}

// -------- PIN Generator (rolling 15 min) --------
function PinGenerator({ notify, disabled }) {
  const [pin, setPin] = useState("");
  const [expires, setExpires] = useState("");
  const [remaining, setRemaining] = useState(0);
  useEffect(() => { const t = setInterval(() => {
    if (!expires) return;
    const diff = Math.max(0, Math.floor((new Date(expires).getTime() - Date.now()) / 1000));
    setRemaining(diff);
    if (diff <= 0) setPin("");
  }, 1000); return () => clearInterval(t); }, [expires]);
  const generate = async () => {
    if (disabled) return notify("Kode Otorisasi Kasir dinonaktifkan oleh Super Admin (Feature Access Control)");
    try { const { data } = await axios.post(`${API}/admin/pin/generate`); setPin(data.pin); setExpires(data.expires_at); notify("Kode otorisasi baru dibuat, berlaku 15 menit"); }
    catch { notify("Gagal generate PIN"); }
  };
  return <section className={`panel product-form-v2 ${disabled ? "panel-disabled" : ""}`} data-testid="pin-generator-panel">
    <div className="form-heading"><div className="form-icon"><Shield size={18} /></div><div><h2>Kode Otorisasi Kasir (15 menit)</h2><span>{disabled ? "🔒 Modul dinonaktifkan — atur di Feature Access Control" : "Untuk approve pembatalan / edit transaksi kasir"}</span></div></div>
    <div className="pin-display" data-testid="pin-display">
      {pin ? <>
        <code className="pin-code" data-testid="pin-code">{pin}</code>
        <div className="pin-meta">
          <span>Berlaku {Math.floor(remaining / 60)}m {String(remaining % 60).padStart(2, "0")}s</span>
          <button className="outline-btn" onClick={generate} disabled={disabled} data-testid="regenerate-pin-button"><RefreshCw size={12}/> Generate ulang</button>
        </div>
      </> : <>
        <div className="hint">{disabled ? "PIN otorisasi kasir dinonaktifkan" : "Belum ada kode aktif"}</div>
        <button className="primary-btn" onClick={generate} disabled={disabled} data-testid="generate-pin-button"><Shield size={14}/> Generate PIN</button>
      </>}
    </div>
  </section>;
}
function UserManagement({ notify }) {
  const [users, setUsers] = useState([]);
  const [outlets, setOutlets] = useState([]);
  const [reveal, setReveal] = useState({});
  const [form, setForm] = useState({ email: "", username: "", password: "", role: "Kasir", name: "", outlet_id: "", active: true });
  const [showReset, setShowReset] = useState(null);
  const [newPass, setNewPass] = useState("");
  const [saving, setSaving] = useState(false);
  const load = () => axios.get(`${API}/admin/users`).then(({ data }) => setUsers(data)).catch(() => {});
  useEffect(() => {
    load();
    axios.get(`${API}/outlets`).then(({ data }) => {
      const active = (data || []).filter((o) => o.active !== false);
      setOutlets(active);
      // Prefill default outlet as first active outlet — so user can't accidentally save empty
      setForm((f) => f.outlet_id ? f : { ...f, outlet_id: active[0]?.id || "" });
    }).catch(() => {});
  }, []);
  const save = async () => {
    if (!form.email || !form.password || !form.name) return notify("Nama, Email, dan Password wajib diisi");
    if (!form.outlet_id) return notify("Outlet tugas wajib dipilih");
    // Validate outlet exists & active
    const selected = outlets.find((o) => o.id === form.outlet_id);
    if (!selected) return notify("Outlet yang dipilih tidak valid / sudah dihapus. Refresh halaman & pilih ulang.");
    setSaving(true);
    try {
      await axios.post(`${API}/admin/users`, form);
      setForm({ ...form, email: "", username: "", password: "", name: "" });
      load();
      notify(`✅ User "${form.name}" tersimpan ke outlet ${selected.name}`);
    } catch (e) {
      notify(`❌ ${e.response?.data?.detail || "Gagal menambah user"}`);
    } finally { setSaving(false); }
  };
  const reset = async () => {
    if (!newPass) return notify("Password baru wajib diisi");
    try { await axios.post(`${API}/admin/users/${showReset}/reset-password`, { new_password: newPass }); setShowReset(null); setNewPass(""); load(); notify("Password direset"); }
    catch { notify("Gagal reset password"); }
  };
  const toggle = async (id) => { await axios.patch(`${API}/admin/users/${id}/toggle`); load(); };
  const remove = async (u) => { if (!window.confirm(`Hapus user ${u.name}?`)) return; try { await axios.delete(`${API}/admin/users/${u.id}`); load(); notify("User dihapus"); } catch (e) { notify(e.response?.data?.detail || "Gagal"); } };
  return <>
    <SectionHeader eyebrow="SECURITY · SUPER ADMIN" title="Manajemen User & Security" description="Kelola akun, reset password, lihat kredensial semua user."
      action={<div className="live-pill"><i /> {users.length} akun aktif</div>} />
    <div className="panel product-form-v2">
      <div className="form-heading"><div className="form-icon"><Shield size={18} /></div><div><h2>Tambah user baru</h2><span>Password akan disimpan agar Super Admin dapat memulihkannya</span></div></div>
      <div className="form-fields" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr 1fr auto" }}>
        <label><span>Nama</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="user-name-input" /></label>
        <label><span>Username</span><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="mis. kasir2" data-testid="user-username-input" /></label>
        <label><span>Email</span><input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} type="email" data-testid="user-email-input" /></label>
        <label><span>Password</span><input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="user-password-input" /></label>
        <label><span>Role</span><select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} data-testid="user-role-select">{["Super Admin", "Admin", "Vendor", "Kasir"].map((r) => <option key={r}>{r}</option>)}</select></label>
        <label><span>Outlet <em style={{ color: "#ef4444" }}>*</em></span><select value={form.outlet_id} onChange={(e) => setForm({ ...form, outlet_id: e.target.value })} data-testid="user-outlet-select"><option value="">— Pilih Outlet —</option>{outlets.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
        <button className="primary-btn" onClick={save} disabled={saving} data-testid="save-user-button"><Plus size={14} /> {saving ? "Menyimpan…" : "Simpan"}</button>
      </div>
    </div>
    <section className="panel table-panel">
      <div className="panel-head"><div><h2>Semua user</h2><span>Klik ikon mata untuk melihat password</span></div></div>
      <div className="data-table">
        <div className="table-row user-row table-label"><span>Nama</span><span>Username / Email</span><span>Role</span><span>Password</span><span>Status</span><span /></div>
        {users.map((u) => <div className="table-row user-row" key={u.id} data-testid={`user-row-${u.id}`}>
          <span className="table-product"><div className="product-dot" style={{ background: "#fff0e6" }}><UserCheck size={14} /></div><b>{u.name}</b></span>
          <span className="mono-inline"><b>{u.username || "-"}</b><small>{u.email}</small></span>
          <span><span className={`role-badge role-${u.role.toLowerCase().replaceAll(" ", "-")}`}>{u.role}</span></span>
          <span className="pass-cell">
            {u.reveal_enabled === false ? <code data-testid={`user-pass-${u.id}`}>disabled</code>
              : reveal[u.id] ? <code data-testid={`user-pass-${u.id}`}>{u.plain_password || "(kosong)"}</code>
              : <code>••••••••</code>}
            {u.reveal_enabled !== false && <button className="icon-btn" onClick={() => setReveal({ ...reveal, [u.id]: !reveal[u.id] })} data-testid={`toggle-pass-${u.id}`}>{reveal[u.id] ? <EyeOff size={13} /> : <Eye size={13} />}</button>}
          </span>
          <span><i className={`status-dot ${u.active ? "good" : "low"}`} />{u.active ? "Aktif" : "Nonaktif"}</span>
          <div className="row-gap">
            <button className="small-action" onClick={() => setShowReset(u.id)} data-testid={`reset-user-${u.id}`}><RefreshCw size={11} /> Reset</button>
            <button className="small-action" onClick={() => toggle(u.id)} data-testid={`toggle-user-${u.id}`}>{u.active ? "Off" : "On"}</button>
            <button className="small-action" onClick={() => remove(u)} data-testid={`delete-user-${u.id}`}><Trash2 size={11} /></button>
          </div>
        </div>)}
      </div>
    </section>
    {showReset && <div className="modal-backdrop"><div className="pay-modal">
      <button className="modal-close" onClick={() => setShowReset(null)}><X size={18} /></button>
      <div className="pay-head"><h2>Reset password</h2><span>Password akan digantikan segera</span></div>
      <div className="pay-body">
        <label>Password baru</label>
        <input value={newPass} onChange={(e) => setNewPass(e.target.value)} data-testid="new-password-input" />
      </div>
      <button className="primary-btn full" onClick={reset} data-testid="confirm-reset-button"><Check size={14} /> Simpan password baru</button>
    </div></div>}
  </>;
}

// -------- Shift modals --------
function ShiftOpenModal({ onClose, onOpened, session, activeOutlet, outlets, notify }) {
  const [cash, setCash] = useState(500000);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const formatIDR = (v) => {
    const num = String(v).replace(/[^0-9]/g, "");
    return num ? `Rp ${Number(num).toLocaleString("id-ID")}` : "";
  };
  const parseIDR = (v) => Number(String(v).replace(/[^0-9]/g, "")) || 0;
  // Dynamic outlet resolution (no hardcoded fallback)
  const userOutletId = session?.outlet_id || null;
  const outlet = outlets?.find((o) => o.id === userOutletId);
  const outletMissing = !userOutletId || !outlet;
  const outletInactive = outlet && outlet.active === false;
  const blocked = outletMissing || outletInactive;
  const outletName = outlet?.name || (userOutletId ? `${userOutletId} (tidak dikenal)` : "Belum ditugaskan");
  const now = new Date();
  const dateLabel = now.toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const timeLabel = now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  const QUICK = [100000, 200000, 500000, 1000000];
  const submit = async () => {
    if (blocked) return;
    const opening = parseIDR(cash);
    if (opening <= 0) { notify?.("Kas awal wajib diisi (minimal Rp 1)"); return; }
    setSubmitting(true);
    try {
      const { data } = await axios.post(`${API}/shifts/open`, { opening_cash: opening, note: note.trim() });
      onOpened(data);
    } catch (e) {
      const detail = e.response?.data?.detail || e.message || "Gagal buka shift. Coba lagi.";
      if (e.response?.status === 400 && /aktif|open/i.test(detail)) {
        try {
          const { data: sh } = await axios.get(`${API}/shifts/current`);
          if (sh && sh.id) { notify?.("Shift kamu masih aktif — melanjutkan sesi"); onOpened(sh); return; }
        } catch {}
      }
      notify?.(`❌ ${detail}`);
    } finally {
      setSubmitting(false);
    }
  };
  return <div className="modal-backdrop"><div className="pay-modal shift-modal" data-testid="shift-open-modal">
    <button className="modal-close" onClick={onClose}><X size={18} /></button>
    <div className="pay-head"><h2>Buka shift kasir</h2><span>Konfirmasi kas awal drawer & mulai sesi</span></div>
    <div className="shift-context" data-testid="shift-context-card">
      <div className="sc-row"><div className="sc-icon"><UserCheck size={14}/></div><div><small>Kasir Aktif</small><b>{session?.name || "Kasir"}</b></div></div>
      <div className="sc-row"><div className="sc-icon"><Building2 size={14}/></div><div><small>Outlet</small><b>{outletName}</b></div></div>
      <div className="sc-row"><div className="sc-icon"><PlayCircle size={14}/></div><div><small>Waktu Mulai</small><b>{dateLabel} · {timeLabel} WIB</b></div></div>
    </div>
    <div className="pay-body">
      <label>Kas awal (Rp)</label>
      <input type="text" inputMode="numeric" value={formatIDR(cash)} onChange={(e) => setCash(parseIDR(e.target.value))} onFocus={(e) => e.target.select()} placeholder="Rp 500.000" data-testid="shift-open-cash-input" />
      <div className="quick-nominal" data-testid="quick-nominal">
        {QUICK.map((n) => (
          <button type="button" key={n} className={parseIDR(cash) === n ? "active" : ""} onClick={() => setCash(n)} data-testid={`quick-nominal-${n}`}>
            Rp {(n / 1000).toLocaleString("id-ID")}{n >= 1000000 ? "" : "rb"}
            {n >= 1000000 && ".000"}
          </button>
        ))}
      </div>
      <label>Catatan (opsional)</label>
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Contoh: shift pagi, uang recehan diambil dulu" data-testid="shift-open-note-input" />
    </div>
    {blocked && <div className="warn-banner" data-testid="shift-outlet-warning" style={{ margin: "8px 0" }}>
      ⚠️ <b>Outlet tidak ditemukan atau telah nonaktif.</b> {outletMissing ? "User belum ditugaskan ke outlet manapun. Hubungi Super Admin untuk assign outlet." : `Outlet "${outletName}" sudah dinonaktifkan. Tidak bisa buka shift baru.`}
    </div>}
    <button className="primary-btn full" disabled={submitting || blocked} onClick={submit} data-testid="shift-open-submit">
      {blocked ? <><Building2 size={14}/> Outlet tidak valid</> : submitting ? <><RefreshCw size={14} className="spin"/> Membuka shift…</> : <><PlayCircle size={14}/> Mulai shift · Rp {parseIDR(cash).toLocaleString("id-ID")}</>}
    </button>
  </div></div>;
}
function ShiftCloseModal({ shift, onClose, onClosed }) {
  const [cash, setCash] = useState(0);
  const [note, setNote] = useState("");
  const submit = async () => {
    await axios.post(`${API}/shifts/close`, { closing_cash: Number(cash), note });
    const { data: report } = await axios.get(`${API}/shifts/${shift.id}/report`);
    onClosed(report);
  };
  return <div className="modal-backdrop"><div className="pay-modal" data-testid="shift-close-modal">
    <button className="modal-close" onClick={onClose}><X size={18} /></button>
    <div className="pay-head"><h2>Tutup shift kasir</h2><span>Kas awal: {money(shift.opening_cash)}</span></div>
    <div className="pay-body">
      <label>Kas fisik dihitung (Rp)</label>
      <input type="number" value={cash} onChange={(e) => setCash(e.target.value)} onFocus={numOnFocus} data-testid="shift-close-cash-input" />
      <label>Catatan</label>
      <input value={note} onChange={(e) => setNote(e.target.value)} data-testid="shift-close-note-input" />
      <div className="hint">Sistem akan otomatis menghitung selisih vs total kas penjualan dan menampilkan rincian shift.</div>
    </div>
    <button className="primary-btn full" onClick={submit} data-testid="shift-close-submit"><StopCircle size={14}/> Tutup shift & lihat rekap</button>
  </div></div>;
}

// -------- Shift Report Modal (Print + WA share) --------
function ShiftReportModal({ report, onClose, notify, outlets }) {
  const s = report.shift || {};
  const [printing, setPrinting] = useState(false);
  const outlet = outlets?.find((o) => o.id === (s.outlet_id || "outlet-sudirman")) || { name: "MJD Kupi", address: "", phone: "" };
  const fmt = (iso) => iso ? new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "-";
  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("id-ID", { year: "numeric", month: "2-digit", day: "2-digit" }).replaceAll("/", "") : "";
  const shiftId = `SHFT${fmtDate(s.opened_at)}_${(s.opened_at || "").slice(11, 16).replace(":", "")}`;
  const lines = [
    "================================",
    "  MJD KUPI  LAPORAN SHIFT KASIR",
    "================================",
    `Shift ID     : ${shiftId}`,
    `Kasir        : ${report.cashier_name || "-"}`,
    `Waktu Mulai  : ${fmt(s.opened_at)}`,
    `Waktu Selesai: ${fmt(s.closed_at)}`,
    `Status Shift : ${(s.status || "").toUpperCase()}`,
    "--------------------------------",
    `Modal Awal    : Rp ${(s.opening_cash || 0).toLocaleString("id-ID")}`,
    `Dibayar       : Rp ${(report.total_omset || 0).toLocaleString("id-ID")}`,
    `Belum Bayar   : Rp ${(report.unpaid_total || 0).toLocaleString("id-ID")}`,
    `Meja Lunas    : ${report.tables_paid}`,
    `Meja Blm Lunas: ${report.tables_pending}`,
    `Pengeluaran   : Rp ${(report.expenses_total || 0).toLocaleString("id-ID")}`,
    `TOTAL CASH    : Rp ${(report.total_cash || 0).toLocaleString("id-ID")}`,
    `TOTAL TRANSFER: Rp ${(report.total_transfer || 0).toLocaleString("id-ID")}`,
    `TOTAL OMSET   : Rp ${(report.total_omset || 0).toLocaleString("id-ID")}`,
    "--------------------------------",
    "BREAKDOWN PER MERCHANT:",
    ...Object.entries(report.per_merchant || {}).map(([k, v]) => `- ${k} : Rp ${Number(v).toLocaleString("id-ID")}`),
    "================================",
  ].join("\n");
  const shareWA = () => window.open(`https://wa.me/?text=${encodeURIComponent(lines)}`, "_blank");
  const printReport = async () => {
    setPrinting(true);
    try {
      const bytes = buildShiftReport({ outlet, report, width: 32 });
      await directPrint(bytes);
      notify("Laporan shift tercetak");
    } catch (e) {
      notify(e.message || "Sambungkan printer di Pengaturan lebih dulu");
    } finally {
      setPrinting(false);
    }
  };
  return <div className="modal-backdrop">
    <div className="shift-report-modal" data-testid="shift-report-modal">
      <button className="modal-close" onClick={onClose}><X size={18} /></button>
      <pre className="shift-slip" data-testid="shift-slip">{lines}</pre>
      <div className="shift-actions">
        <button className="outline-btn" disabled={printing} onClick={printReport} data-testid="shift-print-button"><Printer size={14}/> {printing ? "Mencetak..." : "Printout Struk"}</button>
        <button className="primary-btn" onClick={shareWA} data-testid="shift-wa-button"><MessageCircle size={14}/> Kirim ke WhatsApp</button>
      </div>
      <button className="text-btn" onClick={onClose} data-testid="shift-close-report-button">Tutup</button>
    </div>
  </div>;
}

// -------- Online Orders Modal (POS) --------
function OnlineOrdersModal({ orders, onClose, reload, notify, onAcceptDone }) {
  const [processing, setProcessing] = useState({}); // {orderId: 'accepting' | 'rejecting'}
  const [hidden, setHidden] = useState(new Set());  // optimistic hidden IDs
  const accept = async (id) => {
    if (processing[id] || hidden.has(id)) return; // idempotent guard
    setProcessing((p) => ({ ...p, [id]: "accepting" }));
    setHidden((s) => new Set([...s, id])); // optimistic remove
    try {
      await axios.post(`${API}/self-order/${id}/accept`);
      notify("Pesanan diterima & masuk KDS");
      reload();
      onAcceptDone?.();
    } catch (e) {
      const detail = e.response?.data?.detail || "Gagal menerima pesanan";
      const status = e.response?.status;
      if (status === 409) {
        notify("⚠️ Pesanan sudah diproses (double-click terblokir)");
      } else {
        // rollback optimistic hide on real error (not 409 dupe)
        setHidden((s) => { const n = new Set(s); n.delete(id); return n; });
        notify(detail);
      }
    } finally {
      setProcessing((p) => { const c = { ...p }; delete c[id]; return c; });
    }
  };
  const reject = async (id) => {
    if (processing[id] || hidden.has(id)) return;
    const reason = window.prompt("Alasan penolakan (opsional):", "Stok habis");
    if (reason === null) return;
    setProcessing((p) => ({ ...p, [id]: "rejecting" }));
    setHidden((s) => new Set([...s, id]));
    try {
      await axios.post(`${API}/self-order/${id}/reject`, { reason });
      notify("Pesanan ditolak"); reload();
    } catch (e) {
      const status = e.response?.status;
      if (status === 409) {
        notify("⚠️ Pesanan sudah diproses");
      } else {
        setHidden((s) => { const n = new Set(s); n.delete(id); return n; });
        notify(e.response?.data?.detail || "Gagal menolak");
      }
    } finally {
      setProcessing((p) => { const c = { ...p }; delete c[id]; return c; });
    }
  };
  const visible = orders.filter((o) => !hidden.has(o.id));
  return <div className="modal-backdrop">
    <div className="online-modal" data-testid="online-orders-modal">
      <button className="modal-close" onClick={onClose}><X size={18} /></button>
      <div className="pay-head"><h2>Pesanan masuk (QR Meja)</h2><span>{visible.length} antrean · terima untuk lanjut ke dapur</span></div>
      <div className="online-list">
        {visible.length === 0 && <div className="empty-cart"><QrCode size={30} /><b>Belum ada pesanan online</b><span>Pesanan self-order akan muncul di sini secara realtime (polling 4s)</span></div>}
        {visible.map((o) => {
          const state = processing[o.id];
          const busy = Boolean(state);
          return <div className={`online-item ${busy ? "busy" : ""}`} key={o.id} data-testid={`online-item-${o.id}`}>
            <div className="online-item-head">
              <div>
                <b>{o.table_no}</b>
                <span className="mono">#{String(o.id).slice(0, 8).toUpperCase()}</span>
                {o.customer_name && <em className="cust-badge">👤 {o.customer_name}{o.customer_phone && ` · ${o.customer_phone}`}</em>}
              </div>
              <strong>{money(o.total)}</strong>
            </div>
            <ul className="online-lines">{(o.lines || []).map((ln, i) => <li key={i}>
              <b>{ln.quantity}×</b> {ln.name}{ln.variant_name && <em className="var-chip"> {ln.variant_name}</em>}
              {ln.notes && <small className="line-note"> · 📝 {ln.notes}</small>}
              <em>{money(ln.price * ln.quantity)}</em>
            </li>)}</ul>
            {o.payment_proof && <div className="proof-thumb"><img src={o.payment_proof} alt="proof" /><small>Bukti pembayaran</small></div>}
            <div className="online-actions">
              <button className="danger-btn" onClick={() => reject(o.id)} disabled={busy} data-testid={`reject-online-${o.id}`}>
                {state === "rejecting" ? <><RefreshCw size={13} className="spin"/> Memproses…</> : <><X size={13}/> Tolak Pesanan</>}
              </button>
              <button className="primary-btn" onClick={() => accept(o.id)} disabled={busy} data-testid={`accept-online-${o.id}`}>
                {state === "accepting" ? <><RefreshCw size={14} className="spin"/> Memproses…</> : <><Check size={14}/> Terima & Kirim ke Dapur</>}
              </button>
            </div>
          </div>;
        })}
      </div>
    </div>
  </div>;
}

// -------- Cashier Monitor (Admin) --------
function CashierMonitor({ notify, onView, pinDisabled }) {
  const [shifts, setShifts] = useState([]);
  const load = () => axios.get(`${API}/shifts`).then(({ data }) => setShifts(data)).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  const viewReport = async (id) => { try { const { data } = await axios.get(`${API}/shifts/${id}/report`); onView(data); } catch { notify("Gagal memuat rekap"); } };
  const openCount = shifts.filter((s) => s.status === "open").length;
  const totalOmset = shifts.reduce((a, s) => a + (s.total_cash || 0) + (s.total_transfer || 0), 0);
  return <>
    <SectionHeader eyebrow="AUDIT KASIR" title="Monitoring shift kasir" description="Pantau kasir aktif, riwayat shift, dan generate kode otorisasi untuk approve void/edit."
      action={<button className="outline-btn" onClick={load} data-testid="refresh-cashiers-button"><Bell size={14}/> Refresh</button>} />
    <PinGenerator notify={notify} disabled={pinDisabled} />
    <div className="metric-grid three">
      <Metric label="Shift aktif" value={openCount} change="kasir sedang bekerja" tone="orange" icon={UserCheck} />
      <Metric label="Total shift" value={shifts.length} change="dalam 50 shift terakhir" tone="blue" icon={ClipboardList} />
      <Metric label="Total omset" value={money(totalOmset)} change="akumulasi shift" tone="green" icon={Receipt} />
    </div>
    <section className="panel table-panel">
      <div className="panel-head"><div><h2>Riwayat shift kasir</h2><span>Data real-time dari Supabase</span></div></div>
      <div className="data-table">
        <div className="table-row cashier-row table-label"><span>Kasir</span><span>Waktu</span><span>Modal awal</span><span>Total cash</span><span>Total transfer</span><span>Status</span><span /></div>
        {shifts.map((s) => <div className="table-row cashier-row" key={s.id} data-testid={`cashier-row-${s.id}`}>
          <span className="table-product"><div className="product-dot" style={{ background: "#fff0e6" }}><UserCheck size={14} /></div><b>{s.cashier_name}</b></span>
          <span>{new Date(s.opened_at).toLocaleString("id-ID", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" })}</span>
          <span>{money(s.opening_cash)}</span>
          <span><b>{money(s.total_cash)}</b></span>
          <span>{money(s.total_transfer)}</span>
          <span><i className={`status-dot ${s.status === "open" ? "good" : "low"}`} />{s.status === "open" ? "BUKA" : "TUTUP"}</span>
          <button className="small-action" onClick={() => viewReport(s.id)} data-testid={`view-shift-${s.id}`}><FileText size={12} /> Rekap</button>
        </div>)}
        {shifts.length === 0 && <div className="empty-vendor"><UserCheck size={30} /><b>Belum ada shift</b><span>Kasir akan muncul di sini setelah membuka shift</span></div>}
      </div>
    </section>
  </>;
}

// -------- Customer Self-Order (public /self-order?table=NN) --------
function CustomerSelfOrder() {
  const params = new URLSearchParams(window.location.search);
  const tableParam = params.get("table") || "01";
  const initialOutlet = params.get("outlet_id") || params.get("outlet") || "outlet-sudirman";
  const [outletId, setOutletId] = useState(initialOutlet);
  const [availableOutlets, setAvailableOutlets] = useState([]);
  const [showOutletPicker, setShowOutletPicker] = useState(false);
  const storeSlug = params.get("store_id") || "";
  const [products, setProducts] = useState([]);
  const [merchants, setMerchants] = useState([]);
  const [ssSettings, setSsSettings] = useState({ banners: [], marquee_text: "", logo_url: "", force_closed: false, closed_message: "" });
  const [bannerIdx, setBannerIdx] = useState(0);
  const [cart, setCart] = useState([]);
  const [step, setStep] = useState("menu"); // menu | pay | done | closed
  const [payMethod, setPayMethod] = useState("QRIS Toko");
  const [proof, setProof] = useState("");
  const [qrisImg, setQrisImg] = useState("");
  const [banks, setBanks] = useState([]);
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [orderId, setOrderId] = useState("");
  const [status, setStatus] = useState("Pesanan Diterima");
  const [shopOpen, setShopOpen] = useState(true);
  const [shopMsg, setShopMsg] = useState("");
  const [branding, setBranding] = useState({ name: "MJD Kupi", theme_color: "#f97316", logo_url: "", banner_url: "" });
  const [taxConfig, setTaxConfig] = useState({ enabled: false, percent: 0 });
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Semua");
  const [variantPick, setVariantPick] = useState(null);
  const [showCheckout, setShowCheckout] = useState(false);

  const subtotal = cart.reduce((s, i) => s + i.price * i.qty, 0);
  const tax = taxConfig.enabled && taxConfig.percent > 0 ? Math.round(subtotal * (taxConfig.percent / 100)) : 0;
  const total = subtotal + tax;

  useEffect(() => {
    axios.get(`${API}/public/outlets`).then(({ data }) => setAvailableOutlets(data)).catch(() => {});
  }, []);
  useEffect(() => {
    axios.get(`${API}/outlets/${outletId}/shift-status`).then(({ data }) => {
      setShopOpen(!!data.open);
      if (!data.open) setShopMsg("Mohon Maaf, Toko Sedang Tutup / Belum Menerima Pesanan Online");
    }).catch(() => {});
    axios.get(`${API}/outlets/${outletId}/self-service`).then(({ data }) => {
      setSsSettings(data);
      if (data.force_closed) { setShopOpen(false); setShopMsg(data.closed_message || "Toko sementara tutup"); }
    }).catch(() => {});
    axios.get(`${API}/products?outlet_id=${outletId}`).then(({ data }) => setProducts(data)).catch(() => {});
    axios.get(`${API}/merchants`).then(({ data }) => setMerchants(data)).catch(() => {});
    axios.get(`${API}/settings/qris-image:${outletId}`).then(({ data }) => setQrisImg(data?.image || "")).catch(() => {});
    axios.get(`${API}/settings/bank-accounts?outlet_id=${outletId}`).then(({ data }) => setBanks(data?.accounts || [])).catch(() => {});
    axios.get(`${API}/settings/tax_config`).then(({ data }) => setTaxConfig({ enabled: !!data?.enabled, percent: Number(data?.percent || 0) })).catch(() => {});
    if (storeSlug) axios.get(`${API}/branding/by-slug/${storeSlug}`).then(({ data }) => {
      setBranding(data);
      try { document.documentElement.style.setProperty("--brand-accent", data.theme_color || "#f97316"); } catch {}
    }).catch(() => {});
    setCart([]); // reset cart when switching outlet
  }, [outletId, storeSlug]);
  useEffect(() => {
    // Banner carousel rotation
    if (!ssSettings.banners || ssSettings.banners.length <= 1) return;
    const t = setInterval(() => setBannerIdx((i) => (i + 1) % ssSettings.banners.length), 4500);
    return () => clearInterval(t);
  }, [ssSettings.banners]);
  useEffect(() => {
    if (step !== "done" || !orderId) return;
    const t = setInterval(async () => {
      try { const { data } = await axios.get(`${API}/self-order/${orderId}/status`); setStatus(data.status); } catch {}
    }, 4000);
    return () => clearInterval(t);
  }, [step, orderId]);

  const currentBanner = ssSettings.banners && ssSettings.banners.length > 0 ? ssSettings.banners[bannerIdx] : null;
  const heroBg = currentBanner ? `url(${currentBanner})` : branding.banner_url ? `url(${branding.banner_url})` : "linear-gradient(135deg, var(--brand-accent) 0%, #fb923c 100%)";
  const heroLogo = ssSettings.logo_url || branding.logo_url;

  const handleProductClick = (p) => {
    const active = (p.variants || []).filter((v) => v.active !== false);
    if (active.length > 0) setVariantPick(p);
    else addToCart(p);
  };
  const addToCart = (p, variant = null, notes = "") => setCart((cur) => {
    const key = variant ? `${p.id}__${variant.id}` : p.id;
    const found = cur.find((i) => i.key === key && i.notes === notes);
    if (found) return cur.map((i) => i === found ? { ...i, qty: i.qty + 1 } : i);
    return [...cur, { key, id: p.id, name: p.name, vendor: p.vendor, merchant_id: p.merchant_id, color: p.color, image_url: p.image_url, variant_id: variant?.id || null, variant_name: variant?.name || "", notes: notes || "", price: variant ? Number(variant.price) : Number(p.price), qty: 1 }];
  });
  const adjust = (key, delta) => setCart((cur) => cur.map((i) => i.key === key ? { ...i, qty: i.qty + delta } : i).filter((i) => i.qty > 0));
  const handleFile = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => setProof(r.result); r.readAsDataURL(f); };
  const sendOrder = async () => {
    if (!customerName.trim()) { alert("Nama pelanggan wajib diisi"); return; }
    if (!customerPhone.trim() || customerPhone.length < 8) { alert("Nomor WhatsApp wajib diisi (min 8 digit)"); return; }
    try {
      const { data } = await axios.post(`${API}/self-order`, {
        table: `Meja ${tableParam}`,
        outlet_id: outletId,
        customer_name: customerName.trim(),
        customer_phone: customerPhone.trim(),
        lines: cart.map((i) => ({ product_id: String(i.id), name: i.name, quantity: i.qty, price: i.price, vendor: i.vendor, merchant_id: i.merchant_id, variant_id: i.variant_id || null, variant_name: i.variant_name || "", notes: i.notes || "" })),
        total, notes: "Self-service QR",
        payment_method: payMethod, payment_proof: proof,
      });
      setOrderId(data.id); setStatus(data.status || "Pesanan Diterima"); setStep("done"); setShowCheckout(false);
    } catch (e) {
      if (e.response?.status === 423) setStep("closed");
      else alert(e.response?.data?.detail || "Gagal mengirim pesanan");
    }
  };

  // Categories
  const cats = ["Semua", ...Array.from(new Set(products.map((p) => p.category).filter(Boolean)))];
  const filtered = products.filter((p) => (category === "Semua" || p.category === category) && (!query || p.name.toLowerCase().includes(query.toLowerCase())));
  const pg = usePagination(filtered, [query, category, filtered.length], 12);
  const itemCount = cart.reduce((a, i) => a + i.qty, 0);
  const activeOutletName = availableOutlets.find((o) => o.id === outletId)?.name || outletId;

  if (!shopOpen) return <div className="csa" data-testid="customer-self-order">
    <div className="csa-topbar"><div className="csa-logo">{branding.logo_url ? <img src={branding.logo_url} alt=""/> : <Coffee size={20}/>}</div><b>{branding.name}</b></div>
    <div className="csa-closed" data-testid="customer-closed">
      <StopCircle size={54} color="#ef4444"/>
      <h2>Toko Sedang Tutup</h2>
      <p>{shopMsg}</p>
      <span>Silakan datang kembali saat kasir sudah membuka shift.</span>
    </div>
  </div>;

  if (step === "done") {
    const trackerSteps = [
      { key: "Pesanan Diterima", icon: Check, label: "Pesanan Diterima" },
      { key: "Diproses", icon: Coffee, label: "Sedang Dibuat Dapur" },
      { key: "Siap diambil", icon: Package, label: "Pesanan Siap" },
      { key: "Selesai", icon: Star, label: "Selesai" },
    ];
    const idx = trackerSteps.findIndex((s) => s.key === status);
    return <div className="csa" data-testid="customer-self-order">
      <div className="csa-topbar tracking">
        <div className="csa-logo">{branding.logo_url ? <img src={branding.logo_url} alt=""/> : <Coffee size={20}/>}</div>
        <div><b>{branding.name}</b><span>Meja {tableParam}</span></div>
      </div>
      <div className="csa-track" data-testid="customer-done">
        <div className="csa-track-head">
          <div className="brand-mark big" style={{ background: branding.theme_color }}><Check size={30}/></div>
          <h1>Pesanan terkirim!</h1>
          <p><b>{customerName}</b> · Meja {tableParam}</p>
          <span className="csa-order-id">#{String(orderId).slice(0, 8).toUpperCase()}</span>
        </div>
        <div className="csa-stepper" data-testid="order-tracker">
          {trackerSteps.map((s, i) => {
            const done = idx >= i, current = idx === i;
            return <div key={s.key} className={`csa-step ${done ? "done" : ""} ${current ? "current" : ""}`}>
              <div className="csa-step-icon"><s.icon size={16}/></div>
              <div className="csa-step-body"><b>{s.label}</b>{current && <em data-testid="live-status">Sedang berlangsung…</em>}</div>
              {i < trackerSteps.length - 1 && <div className="csa-step-line"/>}
            </div>;
          })}
        </div>
        <div className="csa-summary">
          <b>Rincian Pesanan</b>
          {cart.map((i) => <div key={i.key} className="csa-summary-row"><span>{i.qty}× {i.name}{i.variant_name && ` (${i.variant_name})`}</span><strong>{money(i.price * i.qty)}</strong></div>)}
          {tax > 0 && <div className="csa-summary-row"><span>PPN ({taxConfig.percent}%)</span><strong>{money(tax)}</strong></div>}
          <div className="csa-summary-row total"><span>Total dibayar</span><strong>{money(total)}</strong></div>
        </div>
      </div>
    </div>;
  }

  return <div className="csa" data-testid="customer-self-order">
    {ssSettings.marquee_text && <div className="csa-marquee" data-testid="csa-marquee"><div className="marquee-text">{ssSettings.marquee_text} · {ssSettings.marquee_text}</div></div>}
    {/* Hero header with banner */}
    <div className="csa-hero" style={{ backgroundImage: heroBg }}>
      <div className="csa-hero-overlay">
        <div className="csa-hero-badge">
          <div className="csa-logo big">{heroLogo ? <img src={heroLogo} alt=""/> : <Coffee size={26}/>}</div>
          <div>
            <h1>{branding.name}</h1>
            <button className="csa-outlet-btn" onClick={() => setShowOutletPicker(true)} data-testid="csa-outlet-picker-button">
              <MapPin size={11}/> <b>{activeOutletName}</b> · Meja {tableParam}
              <ChevronDown size={11}/>
            </button>
            <span><i className="live-dot"/> Buka - Menerima Pesanan</span>
          </div>
        </div>
      </div>
      {ssSettings.banners && ssSettings.banners.length > 1 && <div className="csa-hero-dots">
        {ssSettings.banners.map((_, i) => <i key={i} className={i === bannerIdx ? "on" : ""}/>)}
      </div>}
    </div>
    {/* Sticky search + categories */}
    <div className="csa-sticky">
      <div className="csa-search">
        <Search size={16}/>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari menu favoritmu…" data-testid="csa-search-input"/>
      </div>
      <div className="csa-cats">
        {cats.map((c) => <button key={c} className={category === c ? "active" : ""} onClick={() => setCategory(c)} data-testid={`csa-cat-${c.toLowerCase()}`}>{c}</button>)}
      </div>
    </div>
    {/* Product list */}
    <div className="csa-scroll" data-testid="csa-product-scroll">
      <div className="csa-list">
        {pg.pageItems.map((p) => {
          const priceLabel = (p.variants||[]).filter(v=>v.active!==false).length > 0 ? `Mulai ${money(Math.min(...p.variants.filter(v=>v.active!==false).map(v=>v.price)))}` : money(p.price);
          return <div key={p.id} className="csa-item" data-testid={`csa-item-${p.id}`}>
            <div className="csa-item-img" style={{ background: p.color }}>{p.image_url ? <img src={p.image_url} alt={p.name}/> : <Coffee size={30}/>}</div>
            <div className="csa-item-info">
              <b>{p.name}</b>
              <span className="csa-vendor">by {p.vendor}</span>
              <div className="csa-item-foot">
                <strong>{priceLabel}</strong>
                <button className="csa-add-btn" onClick={() => handleProductClick(p)} data-testid={`csa-add-${p.id}`}><Plus size={14}/> Tambah</button>
              </div>
            </div>
          </div>;
        })}
        {filtered.length === 0 && <div className="csa-empty">Tidak ada menu yang cocok.</div>}
      </div>
      <PaginationBar {...pg} label="menu" testid="csa-pagination" />
    </div>
    {/* Floating bottom cart */}
    {itemCount > 0 && <div className="csa-float" data-testid="customer-cart-bar">
      <div><b>{itemCount} Item</b><span>{money(total)}</span></div>
      <button onClick={() => setShowCheckout(true)} data-testid="customer-checkout-button">Lanjut ke Pembayaran <ChevronRight size={14}/></button>
    </div>}
    {/* Variant modal */}
    {variantPick && <CsaVariantModal product={variantPick} onClose={() => setVariantPick(null)} onAdd={(v, n) => { addToCart(variantPick, v, n); setVariantPick(null); }} />}
    {/* Outlet picker modal */}
    {showOutletPicker && <div className="csa-drawer-back" onClick={() => setShowOutletPicker(false)}>
      <div className="csa-drawer" onClick={(e) => e.stopPropagation()} data-testid="csa-outlet-picker-modal">
        <div className="csa-drawer-grabber"/>
        <button className="csa-drawer-close" onClick={() => setShowOutletPicker(false)}><X size={20}/></button>
        <h2>Pilih Outlet</h2>
        <div className="csa-outlet-list">
          {availableOutlets.map((o) => <button key={o.id} className={`csa-outlet-item ${o.id === outletId ? "active" : ""}`} onClick={() => { setOutletId(o.id); setShowOutletPicker(false); }} data-testid={`csa-outlet-${o.id}`}>
            <MapPin size={16}/>
            <div><b>{o.name}</b><span>{o.address || "—"}</span></div>
            {o.id === outletId && <Check size={16} color="#059669"/>}
          </button>)}
          {availableOutlets.length === 0 && <div className="empty-hint">Belum ada outlet aktif</div>}
        </div>
      </div>
    </div>}
    {/* Checkout drawer */}
    {showCheckout && <div className="csa-drawer-back" onClick={() => setShowCheckout(false)}>
      <div className="csa-drawer" onClick={(e) => e.stopPropagation()} data-testid="customer-checkout-drawer">
        <div className="csa-drawer-grabber"/>
        <button className="csa-drawer-close" onClick={() => setShowCheckout(false)}><X size={20}/></button>
        <h2>Checkout Pesanan</h2>
        <label className="csa-label">Nama Lengkap <em>*</em></label>
        <input className="csa-input" value={customerName} onChange={(e) => setCustomerName(e.target.value)} placeholder="Contoh: Budi Santoso" data-testid="customer-name-input"/>
        <label className="csa-label">Nomor WhatsApp <em>*</em></label>
        <input className="csa-input" value={customerPhone} onChange={(e) => setCustomerPhone(e.target.value.replace(/[^0-9]/g, ""))} placeholder="628xx" data-testid="customer-phone-input" type="tel"/>
        <b className="csa-section-title">Rincian Pesanan</b>
        <div className="csa-drawer-lines">
          {cart.map((i) => <div key={i.key} className="csa-drawer-line">
            <div className="csa-drawer-info">
              <b>{i.name}{i.variant_name && <em className="var-chip"> {i.variant_name}</em>}</b>
              {i.notes && <span className="csa-note">📝 {i.notes}</span>}
              <span>{money(i.price)} × {i.qty}</span>
            </div>
            <div className="csa-drawer-qty">
              <button onClick={() => adjust(i.key, -1)} data-testid={`csa-dec-${i.key}`}>−</button>
              <strong>{i.qty}</strong>
              <button onClick={() => adjust(i.key, 1)} data-testid={`csa-inc-${i.key}`}>+</button>
            </div>
            <strong className="csa-drawer-sub">{money(i.price * i.qty)}</strong>
          </div>)}
        </div>
        <div className="csa-drawer-totals">
          <div><span>Subtotal</span><b>{money(subtotal)}</b></div>
          {tax > 0 && <div><span>PPN ({taxConfig.percent}%)</span><b>{money(tax)}</b></div>}
          <div className="grand"><span>Total</span><strong>{money(total)}</strong></div>
        </div>
        <b className="csa-section-title">Metode Pembayaran</b>
        <div className="csa-methods">
          {[["QRIS Toko", QrCode], ["Transfer Bank", CreditCard], ["Bayar di Kasir", DollarSign]].map(([m, Ic]) => (
            <button key={m} className={payMethod === m ? "active" : ""} onClick={() => setPayMethod(m)} data-testid={`customer-method-${m.toLowerCase().replaceAll(" ", "-")}`}><Ic size={15}/><span>{m}</span></button>
          ))}
        </div>
        {payMethod === "QRIS Toko" && <div className="csa-qris" data-testid="customer-qris-image">
          {qrisImg ? <img src={qrisImg} alt="QRIS Toko"/> : <QRCodeSVG value={`MJDKUPI|OUTLET:${outletId}|AMOUNT:${total}`} size={200} level="M" includeMargin={true}/>}
          <span>Scan QRIS di atas untuk membayar Rp {total.toLocaleString("id-ID")}</span>
        </div>}
        {payMethod === "Transfer Bank" && <div className="csa-banks" data-testid="customer-banks">
          {banks.length ? banks.map((b) => <div className="bank-line" key={b.id}><b>{b.bank_name}</b><span className="mono">{b.account_number}</span><small>a.n. {b.holder_name}</small></div>) : <div className="hint">Belum ada rekening bank terdaftar</div>}
        </div>}
        {payMethod !== "Bayar di Kasir" && <>
          <label className="csa-label">Upload Bukti Pembayaran</label>
          <input type="file" accept="image/*" onChange={handleFile} data-testid="customer-proof-input" className="csa-input"/>
          {proof && <div className="proof-thumb"><img src={proof} alt="bukti"/><Check size={16} color="#059669"/></div>}
        </>}
        <button className="csa-submit" onClick={sendOrder} data-testid="customer-send-order">Kirim Pesanan · {money(total)}</button>
      </div>
    </div>}
  </div>;
}

function CsaVariantModal({ product, onClose, onAdd }) {
  const active = (product.variants || []).filter((v) => v.active !== false);
  const [pick, setPick] = useState(active[0]);
  const [notes, setNotes] = useState("");
  return <div className="csa-drawer-back" onClick={onClose}>
    <div className="csa-drawer variant" onClick={(e) => e.stopPropagation()} data-testid="csa-variant-modal">
      <div className="csa-drawer-grabber"/>
      <button className="csa-drawer-close" onClick={onClose}><X size={20}/></button>
      <div className="csa-var-head">
        <div className="csa-var-img" style={{ background: product.color }}>{product.image_url ? <img src={product.image_url} alt=""/> : <Coffee size={30}/>}</div>
        <div><h2>{product.name}</h2><span>by {product.vendor}</span></div>
      </div>
      <b className="csa-section-title">Pilih Varian</b>
      <div className="csa-var-picks">
        {active.map((v) => <button key={v.id} className={pick?.id === v.id ? "active" : ""} onClick={() => setPick(v)} data-testid={`csa-pick-${v.id}`}>
          <span><b>{v.name}</b></span><strong>{money(v.price)}</strong>
        </button>)}
      </div>
      <label className="csa-label">Catatan (opsional)</label>
      <input className="csa-input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Less sugar / Tanpa es / Extra hot" data-testid="csa-notes-input"/>
      <button className="csa-submit" disabled={!pick} onClick={() => onAdd(pick, notes)} data-testid="csa-add-to-cart">Tambahkan · {money(pick?.price || 0)}</button>
    </div>
  </div>;
}


// -------- History Kasir + Void with PIN --------
function HistoryModal({ onClose, notify }) {
  const [sales, setSales] = useState([]);
  const [voiding, setVoiding] = useState(null);
  const [pin, setPin] = useState("");
  const [reason, setReason] = useState("");
  const load = () => axios.get(`${API}/pos/history`).then(({ data }) => setSales(data)).catch(() => setSales([]));
  useEffect(() => { load(); }, []);
  const submitVoid = async () => {
    if (!pin || pin.length < 6) return notify("Masukkan kode 6 huruf dari admin");
    try { await axios.post(`${API}/sales/${voiding.id}/void`, { pin, reason }); setVoiding(null); setPin(""); setReason(""); load(); notify("Transaksi dibatalkan"); }
    catch (e) { notify(e.response?.data?.detail || "Gagal membatalkan"); }
  };
  return <div className="modal-backdrop">
    <div className="online-modal" data-testid="history-modal">
      <button className="modal-close" onClick={onClose}><X size={18} /></button>
      <div className="pay-head"><h2>History Transaksi Shift Aktif</h2><span>{sales.length} transaksi · hanya shift Anda</span></div>
      <div className="online-list">
        {sales.length === 0 && <div className="empty-cart"><Receipt size={30} /><b>Belum ada transaksi</b><span>History akan muncul begitu ada penjualan</span></div>}
        {sales.map((s) => <div className={`online-item ${s.status === "voided" ? "voided" : ""}`} key={s.id} data-testid={`history-item-${s.id}`}>
          <div className="online-item-head">
            <div><b>#{String(s.id).slice(-6).toUpperCase()}</b><span className="mono">{new Date(s.created_at).toLocaleTimeString("id-ID")}</span></div>
            <strong>{money(s.total)}</strong>
          </div>
          <ul className="online-lines">{(s.lines || []).slice(0, 3).map((ln, i) => <li key={i}><b>{ln.quantity}×</b> {ln.name}</li>)}{(s.lines || []).length > 3 && <li>+{s.lines.length - 3} item</li>}</ul>
          <div className="history-foot">
            <span className={`status-badge ${s.status}`}>{s.status === "voided" ? "DIBATALKAN" : s.payment_method}</span>
            {s.status !== "voided" && <button className="small-action danger" onClick={() => setVoiding(s)} data-testid={`void-${s.id}`}><X size={11}/> Batalkan</button>}
          </div>
        </div>)}
      </div>
      {voiding && <div className="modal-backdrop" style={{ zIndex: 60 }}>
        <div className="pay-modal" data-testid="void-pin-modal">
          <button className="modal-close" onClick={() => setVoiding(null)}><X size={18} /></button>
          <div className="pay-head"><h2>Batalkan Transaksi</h2><span>#{String(voiding.id).slice(-6).toUpperCase()} · {money(voiding.total)}</span></div>
          <div className="pay-body">
            <div className="hint">Minta Admin generate PIN 6 huruf (berlaku 15 menit) dari menu Pengaturan.</div>
            <label>Kode Otorisasi (6 huruf)</label>
            <input value={pin} onChange={(e) => setPin(e.target.value.toUpperCase())} maxLength={6} placeholder="X7K9LP" style={{ letterSpacing: 6, fontFamily: "monospace", fontSize: 18 }} data-testid="void-pin-input" />
            <label>Alasan (opsional)</label>
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Alasan pembatalan" data-testid="void-reason-input" />
          </div>
          <button className="primary-btn full" onClick={submitVoid} data-testid="void-submit-button"><Check size={14}/> Konfirmasi pembatalan</button>
        </div>
      </div>}
    </div>
  </div>;
}

// -------- Login --------
function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [brand, setBrand] = useState({ name: "MJD Kupi", subtitle: "Retail Command Center" });
  useEffect(() => {
    axios.get(`${API}/settings/branding_text`).then(({ data }) => {
      if (data && (data.name || data.subtitle)) setBrand({ name: data.name || "MJD Kupi", subtitle: data.subtitle || "Retail Command Center" });
    }).catch(() => {});
  }, []);
  const submit = async (event) => {
    event.preventDefault();
    if (!email.trim() || !password) { setError("Username / Email dan Password wajib diisi."); return; }
    setBusy(true); setError("");
    try { const { data } = await axios.post(`${API}/auth/login`, { email: email.trim(), password }); onLogin(data); }
    catch (e) { setError(e.response?.data?.detail || "Login gagal. Periksa kembali kredensial Anda."); }
    finally { setBusy(false); }
  };
  return <div className="login-screen" data-testid="login-screen">
    <div className="login-art">
      <div className="login-brand"><div className="brand-mark"><Coffee size={19} /></div><strong data-testid="login-brand-name">{brand.name}</strong></div>
      <div><div className="eyebrow" data-testid="login-brand-subtitle">{brand.subtitle.toUpperCase()}</div><h1>Satu ruang untuk<br /><em>operasi yang lancar.</em></h1><p>POS, inventori, KDS, dan payout vendor dalam satu workspace.</p></div>
      <div className="login-orbit"><Coffee size={64} /></div>
    </div>
    <form className="login-form" onSubmit={submit} autoComplete="on">
      <div className="eyebrow">WELCOME BACK</div>
      <h2>Masuk ke workspace</h2>
      <p>Masukkan username atau email dan password yang telah terdaftar.</p>
      <label>Username / Email<input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="username atau email" autoComplete="username" data-testid="login-email-input" /></label>
      <label>Password<input value={password} onChange={(e) => setPassword(e.target.value)} type="password" placeholder="Masukkan password" autoComplete="current-password" data-testid="login-password-input" /></label>
      {error && <div className="login-error" data-testid="login-error">{error}</div>}
      <button className="primary-btn full" disabled={busy} data-testid="login-submit-button">{busy ? "Memeriksa…" : `Masuk ke ${brand.name}`}<span>→</span></button>
      <div className="demo-accounts" data-testid="demo-accounts">
        <b>Akses demo cepat:</b>
        <button type="button" onClick={() => { setEmail("superadmin"); setPassword(".Superadmin1_"); setError(""); }} data-testid="demo-superadmin-button">Super Admin</button>
        <button type="button" onClick={() => { setEmail("admin"); setPassword("MjdKupi#2026"); setError(""); }} data-testid="demo-admin-button">Admin</button>
        <button type="button" onClick={() => { setEmail("kasir"); setPassword("MjdKupi#2026"); setError(""); }} data-testid="demo-kasir-button">Kasir</button>
        <button type="button" onClick={() => { setEmail("vendor"); setPassword("MjdKupi#2026"); setError(""); }} data-testid="demo-vendor-button">Vendor</button>
      </div>
    </form>
  </div>;
}

// -------- Notification Drawer (Batch B #3) --------
function NotificationDrawer({ notif, onClose, setPage, onOrderClick, onMarkAll }) {
  const items = notif?.items || [];
  const iconFor = (t) => t === "stock" ? Package : t === "shift" ? UserCheck : t === "order" ? ShoppingCart : Info;
  const colorFor = (s) => s === "critical" ? "#ef4444" : s === "warning" ? "#f59e0b" : "#3b82f6";
  const timeAgo = (iso) => {
    const d = new Date(iso); const m = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
    if (m < 1) return "baru saja"; if (m < 60) return `${m}m lalu`; const h = Math.floor(m/60); if (h < 24) return `${h}j lalu`; return `${Math.floor(h/24)}h lalu`;
  };
  const handleClick = (n) => {
    if (n.type === "order" && onOrderClick) onOrderClick(n);
    else setPage(n.action || "overview");
  };
  return <div className="notif-back" onClick={onClose}>
    <aside className="notif-drawer" onClick={(e) => e.stopPropagation()} data-testid="notif-drawer">
      <div className="notif-head">
        <div><b>Notification Center</b><span>{items.length} alert aktif</span></div>
        <button className="modal-close" onClick={onClose}><X size={18}/></button>
      </div>
      <div className="notif-body">
        {items.length === 0 ? <div className="empty-hint" style={{padding: 40}}>Tidak ada notifikasi</div>
          : items.map((n) => {
            const Icon = iconFor(n.type);
            return <button key={n.id} className={`notif-row ${n.severity}`} onClick={() => handleClick(n)} data-testid={`notif-${n.id}`}>
              <div className="notif-icon" style={{ background: `${colorFor(n.severity)}22`, color: colorFor(n.severity) }}><Icon size={16}/></div>
              <div className="notif-info">
                <b>{n.title}</b>
                <span>{n.detail}</span>
                <em>{timeAgo(n.created_at)}</em>
              </div>
              <ChevronRight size={14} color="#a0a9b5"/>
            </button>;
          })}
      </div>
      <div className="notif-foot">
        <button onClick={onMarkAll} data-testid="notif-mark-all"><Check size={14}/> Tandai Semua Dibaca</button>
      </div>
    </aside>
  </div>;
}

// -------- Printer Settings (Batch B #7.2) --------
function PrinterSettings({ notify }) {
  const [connected, setConnected] = useState(isPrinterConnected());
  const [name, setName] = useState(pairedPrinterName() || "");
  const [paper, setPaper] = useState(() => { try { return localStorage.getItem("mjd_paper_size") || "80mm"; } catch { return "80mm"; } });
  const [alloc, setAlloc] = useState(() => { try { return localStorage.getItem("mjd_printer_role") || "cashier"; } catch { return "cashier"; } });
  const [cfg, setCfg] = useState({ logo_url: "", header: "", footer: "" });
  const [savingCfg, setSavingCfg] = useState(false);
  const supported = isPrinterSupported();
  useEffect(() => { try { localStorage.setItem("mjd_paper_size", paper); } catch {} }, [paper]);
  useEffect(() => { try { localStorage.setItem("mjd_printer_role", alloc); } catch {} }, [alloc]);
  useEffect(() => {
    axios.get(`${API}/settings/printer_config`).then(({ data }) => {
      if (data && typeof data === "object") setCfg((c) => ({ ...c, ...data }));
    }).catch(() => {});
  }, []);
  const pair = async () => {
    try {
      const dev = await pairPrinter();
      setConnected(true); setName(dev?.name || pairedPrinterName() || "Printer terhubung");
      notify(`Printer ${dev?.name || ""} tersambung`);
    } catch (e) { notify(`Gagal pair: ${e.message || e}`); }
  };
  const test = async () => {
    try {
      await directPrint(buildSaleReceipt({
        merchant: "MJD Kupi", outlet: "Test Print", cashier: "System",
        lines: [{ name: "Test Print", quantity: 1, price: 0 }],
        subtotal: 0, tax: 0, total: 0, method: "TEST", change: 0, cash: 0,
        header: cfg.header, footer: cfg.footer,
      }, paper));
      notify("Test print terkirim ke printer");
    } catch (e) { notify(`Gagal test print: ${e.message || e}`); }
  };
  // Convert uploaded image to monochrome dataURL bounded to paper width
  const handleLogoUpload = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    const targetWidth = paper === "58mm" ? 384 : 576;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const ratio = Math.min(1, targetWidth / img.width);
        const w = Math.round(img.width * ratio);
        const h = Math.round(img.height * ratio);
        const canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext("2d");
        // white background then draw
        ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        const data = ctx.getImageData(0, 0, w, h);
        // Simple threshold @128 → monochrome
        for (let i = 0; i < data.data.length; i += 4) {
          const r = data.data[i], g = data.data[i + 1], b = data.data[i + 2];
          const gray = 0.299 * r + 0.587 * g + 0.114 * b;
          const v = gray < 128 ? 0 : 255;
          data.data[i] = v; data.data[i + 1] = v; data.data[i + 2] = v; data.data[i + 3] = 255;
        }
        ctx.putImageData(data, 0, 0);
        const url = canvas.toDataURL("image/png");
        setCfg((c) => ({ ...c, logo_url: url, logo_w: w, logo_h: h }));
        notify(`Logo diresize ${w}×${h}px & di-konversi monokrom`);
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  };
  const saveCfg = async () => {
    setSavingCfg(true);
    try {
      await axios.post(`${API}/settings`, { key: "printer_config", value: cfg });
      notify("Konfigurasi struk tersimpan (header · footer · logo)");
    } catch (e) { notify("Gagal simpan konfigurasi"); }
    setSavingCfg(false);
  };
  const maxLogoWidth = paper === "58mm" ? 384 : 576;
  return <>
    <SectionHeader eyebrow="HARDWARE" title="Pengaturan Printer" description="Konfigurasi printer thermal ESC/POS + kustomisasi header, footer, dan logo struk."
      action={<button className="primary-btn" onClick={pair} data-testid="printer-pair-button" disabled={!supported}><Bluetooth size={14}/> Pair Printer</button>} />
    {!supported && <div className="warn-banner">⚠️ Web Bluetooth tidak didukung di browser ini. Gunakan Chrome/Edge di HTTPS.</div>}
    <div className="panel product-form-v2" data-testid="printer-settings">
      <div className="form-heading"><div className="form-icon"><Printer size={18}/></div>
        <div><h2>Status Koneksi</h2><span>Kelola printer thermal aktif</span></div>
      </div>
      <div className="printer-status-row">
        <div className={`printer-status-card ${connected ? "on" : "off"}`} data-testid="printer-status">
          <div className="ps-dot"/>
          <div><b>{connected ? "Terhubung" : "Terputus"}</b><span>{connected ? name || "Printer thermal" : "Klik Pair Printer untuk menyambung"}</span></div>
        </div>
        <div className="printer-fields">
          <label>Ukuran Kertas
            <select value={paper} onChange={(e) => setPaper(e.target.value)} data-testid="printer-paper-select">
              <option value="58mm">58mm (Mini)</option>
              <option value="80mm">80mm (Standar)</option>
            </select>
          </label>
          <label>Alokasi Role Printer
            <select value={alloc} onChange={(e) => setAlloc(e.target.value)} data-testid="printer-role-select">
              <option value="cashier">🧾 Printer Kasir (Struk pelanggan)</option>
              <option value="kitchen">🍳 Printer Dapur / KDS (Tiket dapur)</option>
              <option value="barista">☕ Printer Barista (Tiket minuman)</option>
            </select>
          </label>
        </div>
      </div>
      <div className="modal-actions">
        <button className="outline-btn" onClick={test} disabled={!connected} data-testid="printer-test-button"><Printer size={14}/> Test Print</button>
        <button className="primary-btn" onClick={pair} data-testid="printer-repair-button"><RefreshCw size={14}/> {connected ? "Ganti Printer" : "Pair Sekarang"}</button>
      </div>
    </div>

    {/* Receipt Customization */}
    <div className="panel product-form-v2" data-testid="printer-receipt-panel">
      <div className="form-heading"><div className="form-icon"><FileText size={18}/></div>
        <div><h2>Kustomisasi Struk</h2><span>Logo, header, dan footer akan tercetak di setiap struk pelanggan</span></div>
      </div>
      <div className="printer-cust-grid" style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 20 }}>
        <div>
          <label className="image-drop" data-testid="receipt-logo-label" style={{ minHeight: 160 }}>
            {cfg.logo_url ? <img src={cfg.logo_url} alt="logo" style={{ maxWidth: "100%", maxHeight: 140, background: "#fff", padding: 8 }}/>
                          : <><ImageIcon size={30}/><span>Klik untuk unggah logo struk</span></>}
            <input type="file" accept="image/png,image/jpeg" onChange={handleLogoUpload} style={{ display: "none" }} data-testid="receipt-logo-input"/>
          </label>
          <div className="empty-hint" style={{ marginTop: 8, background: "#fff7ed", color: "#9a3412" }}>
            <b>Rekomendasi:</b> Gambar Hitam-Putih / Monokrom.<br/>
            Maks lebar: <b>{maxLogoWidth}px</b> untuk {paper}.<br/>
            Sistem auto-resize & konversi monokrom.
          </div>
          {cfg.logo_url && <button className="outline-btn" style={{ width: "100%", marginTop: 8 }} onClick={() => setCfg({ ...cfg, logo_url: "" })} data-testid="remove-logo-btn"><Trash2 size={13}/> Hapus Logo</button>}
        </div>
        <div>
          <label className="field-lg" style={{ marginBottom: 12, display: "block" }}>
            <span>Header Struk</span>
            <textarea rows={3} value={cfg.header} onChange={(e) => setCfg({ ...cfg, header: e.target.value })}
              placeholder="Jl. Sudirman No. 1&#10;Telp: 0812-3456-7890&#10;WiFi: kopi123" data-testid="receipt-header-input"
              style={{ width: "100%", padding: 10, border: "1px solid var(--line)", borderRadius: 6, fontFamily: "monospace", fontSize: 13 }} />
          </label>
          <label className="field-lg" style={{ marginBottom: 12, display: "block" }}>
            <span>Footer Struk</span>
            <textarea rows={3} value={cfg.footer} onChange={(e) => setCfg({ ...cfg, footer: e.target.value })}
              placeholder="Terima kasih atas kunjungan Anda!&#10;IG: @mjdkupi&#10;#SegelasKopiSetiapHari" data-testid="receipt-footer-input"
              style={{ width: "100%", padding: 10, border: "1px solid var(--line)", borderRadius: 6, fontFamily: "monospace", fontSize: 13 }} />
          </label>
          <div className="modal-actions">
            <button className="primary-btn" onClick={saveCfg} disabled={savingCfg} data-testid="save-printer-config-btn"><Check size={14}/> {savingCfg ? "Menyimpan…" : "Simpan Konfigurasi Struk"}</button>
          </div>
        </div>
      </div>
    </div>

    <div className="panel product-form-v2">
      <div className="form-heading"><div className="form-icon"><Info size={18}/></div>
        <div><h2>Panduan Konfigurasi</h2><span>Tips agar cetakan struk & tiket dapur berjalan mulus</span></div>
      </div>
      <ul className="printer-tips">
        <li>Nyalakan printer Bluetooth, pastikan mode pairing (biasanya lampu berkedip).</li>
        <li>Klik <b>Pair Printer</b> — browser akan menampilkan daftar perangkat terdekat.</li>
        <li>Pilih printer thermal Anda, lalu klik <b>Test Print</b>.</li>
        <li>Alokasi role menentukan template cetakan otomatis: Kasir mencetak struk lengkap, Dapur mencetak tiket dapur singkat.</li>
        <li>Untuk multi-printer, konfigurasi 1 device per browser/perangkat.</li>
      </ul>
    </div>
  </>;
}
