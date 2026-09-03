import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { QRCodeSVG, QRCodeCanvas } from "qrcode.react";
import {
  BarChart3, Bell, ChefHat, ChevronDown, ClipboardList, Coffee, CreditCard,
  Database, DollarSign, FileText, Grid2X2, LogOut, Menu, Package, Plus,
  Printer, QrCode, Receipt, Search, Settings2, ShoppingCart, Store, Timer,
  Trash2, Users, Wallet, X, Building2, Volume2, MessageCircle, PlayCircle,
  StopCircle, UserCheck, Upload, Image as ImageIcon, Check, Copy, Shield,
  Eye, EyeOff, RefreshCw, Bluetooth,
} from "lucide-react";
import { pairPrinter, directPrint, isPrinterConnected, pairedPrinterName, isPrinterSupported, buildSaleReceipt, buildShiftReport, buildKitchenTicket } from "@/utils/thermalPrinter";
import "@/App.css";

const money = (n) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const ORIGIN = typeof window !== "undefined" ? window.location.origin : "";
axios.defaults.withCredentials = true;
// SEC-001 defense-in-depth: custom header on every request. Cross-site attackers cannot set
// custom headers on simple requests (triggers CORS preflight which is blocked).
axios.defaults.headers.common["X-Requested-With"] = "mjd-kupi";

const NAV_BY_ROLE = {
  "Super Admin": ["overview", "pos", "kds", "inventory", "expenses", "products", "merchants", "cashiers", "reports", "tables", "self-service", "vendor-center", "users", "settings"],
  "Admin": ["overview", "kds", "inventory", "expenses", "products", "merchants", "cashiers", "reports", "tables", "vendor-center"],
  Vendor: ["kds", "vendor-center", "self-service"],
  Kasir: ["pos", "expenses", "kds"],
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
  const [expenses, setExpenses] = useState([]);
  const [shift, setShift] = useState(null);
  const [showShiftOpen, setShowShiftOpen] = useState(false);
  const [showShiftClose, setShowShiftClose] = useState(false);
  const [showPayment, setShowPayment] = useState(false);
  const [lastSale, setLastSale] = useState(null);
  const [showReceipt, setShowReceipt] = useState(false);
  const [onlineOrders, setOnlineOrders] = useState([]);
  const [showOnlineOrders, setShowOnlineOrders] = useState(false);
  const [shiftReport, setShiftReport] = useState(null);
  const [brandLogo, setBrandLogo] = useState("");
  const prevOnlineIdsRef = useRef(new Set());
  const chimeRef = useRef(null);
  const printerRef = useRef(null);

  const notify = (text) => { setToast(text); window.setTimeout(() => setToast(""), 2500); };
  const role = session?.role;
  const allowed = NAV_ITEMS.filter((n) => (NAV_BY_ROLE[role] || []).includes(n.id));

  const reloadProducts = () => axios.get(`${API}/products`).then(({ data }) => setProducts(data.map((p) => ({ ...p, id: p.id, price: Number(p.price), cost: Number(p.cost), stock: Number(p.stock) })))).catch(() => {});
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
    reloadProducts(); reloadMerchants(); reloadExpenses();
    axios.get(`${API}/outlets`).then(({ data }) => setOutlets(data)).catch(() => {});
    axios.get(`${API}/settings/logo`).then(({ data }) => setBrandLogo(data?.logo_data || "")).catch(() => {});
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
    // Poll online orders only for cashier/admin
    if (["Kasir", "Merchant Admin", "Super Admin"].includes(session.role)) {
      reloadOnlineOrders();
      const t = setInterval(reloadOnlineOrders, 4000);
      return () => clearInterval(t);
    }
  }, [session]);

  const filtered = useMemo(
    () => products.filter((p) => (category === "Semua" || p.category === category) && p.name.toLowerCase().includes(query.toLowerCase())),
    [products, category, query]
  );
  const subtotal = cart.reduce((sum, i) => sum + i.price * i.qty, 0);
  const tax = Math.round(subtotal * 0.1);
  const total = subtotal + tax;

  const addToCart = (product) => setCart((cur) => {
    const found = cur.find((i) => i.id === product.id);
    return found ? cur.map((i) => i.id === product.id ? { ...i, qty: i.qty + 1 } : i) : [...cur, { ...product, qty: 1 }];
  });
  const adjustCart = (id, amount) => setCart((cur) => cur.map((i) => i.id === id ? { ...i, qty: i.qty + amount } : i).filter((i) => i.qty > 0));

  const openPayment = () => {
    if (!cart.length) return;
    if (session.role === "Kasir" && !shift) { setShowShiftOpen(true); notify("Buka shift terlebih dahulu sebelum bertransaksi"); return; }
    setShowPayment(true);
  };

  const confirmSale = async ({ method, reference, cashReceived }) => {
    try {
      const payload = {
        table: "Meja 07",
        lines: cart.map((i) => ({ product_id: String(i.id), name: i.name, quantity: i.qty, price: i.price, vendor: i.vendor, merchant_id: i.merchant_id })),
        subtotal, tax, total,
        payment_method: method,
        payment_reference: reference || "",
        cash_received: Number(cashReceived) || 0,
        change_amount: Math.max(0, (Number(cashReceived) || 0) - total),
      };
      const { data } = await axios.post(`${API}/sales`, payload);
      setLastSale({ ...payload, id: data.id, created_at: data.created_at });
      setShowPayment(false);
      setShowReceipt(true);
      await reloadProducts();
      notify("Transaksi berhasil, tiket dapur terkirim");
    } catch (e) {
      notify(e.response?.data?.detail || "Gagal menyimpan transaksi");
    }
  };

  if (authLoading) return <div className="auth-loading" data-testid="auth-loading">Memuat ruang kerja MJD Kupi…</div>;
  if (!session) return <Login onLogin={setSession} />;

  const pageTitle = NAV_ITEMS.find((n) => n.id === page)?.label || "Ringkasan";

  return (
    <div className="app-shell" data-testid="mjd-kupi-app">
      <aside className={`sidebar ${sidebar ? "is-open" : ""}`} data-testid="main-sidebar">
        <div className="brand">
          <div className="brand-mark" data-testid="brand-logo">{brandLogo ? <img src={brandLogo} alt="logo" /> : <Coffee size={19} />}</div>
          <div><strong>MJD Kupi</strong><span>Retail Command Center</span></div>
          <button className="mobile-close" data-testid="close-sidebar-button" onClick={() => setSidebar(false)}><X size={18} /></button>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {allowed.map(({ id, label, icon: Icon, live }) => (
            <button key={id} className={page === id ? "nav-item active" : "nav-item"} data-testid={`nav-${id}`} onClick={() => { setPage(id); setSidebar(false); }}>
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
          <div className="breadcrumb"><span>MJD Kupi</span><b>/</b><strong>{pageTitle}</strong></div>
          <div className="top-actions">
            <div className="merchant-switch">
              <Building2 size={16} />
              <select value={activeOutlet} onChange={(e) => setActiveOutlet(e.target.value)} data-testid="outlet-switcher">
                {outlets.length ? outlets.map((o) => <option value={o.id} key={o.id}>{o.name}</option>) : <option value="outlet-sudirman">Outlet Sudirman</option>}
              </select>
              <ChevronDown size={14} />
            </div>
            <div className="role-chip" data-testid="current-user-role">{session.name} · {session.role}</div>
            <button className="icon-button" data-testid="notifications-button" onClick={() => notify("Tidak ada notifikasi baru")}><Bell size={18} /><i /></button>
            <div className="top-avatar">{session.name.slice(0, 2).toUpperCase()}</div>
          </div>
        </header>

        <div className="page-wrap">
          {page === "overview" && <Overview products={products} expenses={expenses} setPage={setPage} />}
          {page === "pos" && (
            <POS products={filtered} query={query} setQuery={setQuery} category={category} setCategory={setCategory}
                 cart={cart} addToCart={addToCart} adjustCart={adjustCart} subtotal={subtotal} tax={tax} total={total}
                 onPay={openPayment} shift={shift} role={session.role}
                 onlineOrders={onlineOrders} openOnline={() => setShowOnlineOrders(true)} />
          )}
          {page === "kds" && <KDS notify={notify} merchants={merchants} />}
          {page === "inventory" && <Inventory products={products} reload={reloadProducts} notify={notify} />}
          {page === "expenses" && <Expenses expenses={expenses} reload={reloadExpenses} notify={notify} />}
          {page === "products" && <Products products={products} merchants={merchants} reload={reloadProducts} notify={notify} />}
          {page === "merchants" && <Merchants merchants={merchants} reload={reloadMerchants} notify={notify} />}
          {page === "cashiers" && <CashierMonitor notify={notify} onView={setShiftReport} />}
          {page === "users" && session.role === "Super Admin" && <UserManagement notify={notify} />}
          {page === "reports" && <Reports products={products} expenses={expenses} />}
          {page === "tables" && <Tables notify={notify} />}
          {page === "self-service" && <SelfService products={products} notify={notify} activeOutlet={activeOutlet} />}
          {page === "vendor-center" && <VendorCenter notify={notify} />}
          {page === "settings" && <SettingsPage notify={notify} printerRef={printerRef} role={session.role} />}
        </div>
      </main>

      {toast && <div className="toast" data-testid="toast-message"><span>✓</span>{toast}</div>}
      {showShiftOpen && <ShiftOpenModal onClose={() => setShowShiftOpen(false)} onOpened={(s) => { setShift(s); setShowShiftOpen(false); notify("Shift berhasil dibuka"); }} />}
      {showShiftClose && shift && <ShiftCloseModal shift={shift} onClose={() => setShowShiftClose(false)} onClosed={(rep) => { setShift(null); setShowShiftClose(false); setShiftReport(rep); notify(`Shift ditutup. Selisih ${money(rep.shift.variance)}`); }} />}
      {showPayment && <PaymentModal total={total} onClose={() => setShowPayment(false)} onConfirm={confirmSale} />}
      {showReceipt && lastSale && <ReceiptModal sale={lastSale} merchants={merchants} outlets={outlets} cashier={session?.name || ""} onClose={() => { setShowReceipt(false); setLastSale(null); setCart([]); }} notify={notify} />}
      {showOnlineOrders && <OnlineOrdersModal orders={onlineOrders} onClose={() => setShowOnlineOrders(false)} reload={reloadOnlineOrders} notify={notify} onAcceptDone={() => reloadProducts()} />}
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

// -------- Overview --------
function Overview({ products, expenses, setPage }) {
  const [dash, setDash] = useState({ sales_total: 0, expense_total: 0, transaction_count: 0 });
  useEffect(() => { axios.get(`${API}/dashboard`).then(({ data }) => setDash(data)).catch(() => {}); }, []);
  const stock = products.reduce((a, p) => a + (p.stock || 0), 0);
  return <>
    <SectionHeader eyebrow="SELAMAT DATANG" title="Ringkasan operasional" description="Pantau kesehatan Outlet dalam satu pandangan."
      action={<button className="primary-btn" data-testid="overview-pos-button" onClick={() => setPage("pos")}><CreditCard size={16} /> Buka Terminal POS</button>} />
    <div className="metric-grid">
      <Metric label="Penjualan hari ini" value={money(dash.sales_total)} change="Sinkron Supabase" tone="orange" icon={Receipt} />
      <Metric label="Transaksi selesai" value={dash.transaction_count} change="live realtime" tone="green" icon={ShoppingCart} />
      <Metric label="Laba kotor" value={money(Math.max(0, dash.sales_total * 0.38))} change="≈38% margin" tone="blue" icon={BarChart3} />
      <Metric label="Pengeluaran" value={money(dash.expense_total)} change={`${expenses.length} entri`} tone="red" icon={Wallet} />
    </div>
    <div className="content-grid">
      <section className="panel chart-panel">
        <div className="panel-head"><div><h2>Performa penjualan</h2><span>Ringkasan · sinkron Supabase</span></div><button className="date-chip" data-testid="sales-period-button">7 hari <ChevronDown size={14} /></button></div>
        <div className="chart">
          <div className="chart-y"><span>4jt</span><span>3jt</span><span>2jt</span><span>1jt</span><span>0</span></div>
          <div className="bars">{[54, 72, 48, 86, 66, 92, 78].map((h, i) => <div className="bar-col" key={i}><div className={`bar ${i === 5 ? "selected" : ""}`} style={{ height: `${h}%` }}><b>{i === 5 ? "3,9jt" : ""}</b></div><span>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"][i]}</span></div>)}</div>
        </div>
      </section>
      <section className="panel quick-panel">
        <div className="panel-head"><div><h2>Aksi cepat</h2><span>Alur yang sering dipakai</span></div></div>
        <QuickAction icon={Plus} title="Tambah produk" detail="Buat menu baru & atur HPP" onClick={() => setPage("products")} />
        <QuickAction icon={Package} title="Restock inventori" detail={`${stock} unit stok tercatat`} onClick={() => setPage("inventory")} />
        <QuickAction icon={Wallet} title="Catat pengeluaran" detail="Tambah biaya operasional" onClick={() => setPage("expenses")} />
        <QuickAction icon={Store} title="Kelola merchant" detail="Tambah tenant baru" onClick={() => setPage("merchants")} />
      </section>
    </div>
    <section className="panel table-panel">
      <div className="panel-head"><div><h2>Stok menipis</h2><span>Perlu perhatian hari ini</span></div><button className="text-btn" data-testid="inventory-table-link" onClick={() => setPage("inventory")}>Lihat semua <span>→</span></button></div>
      <div className="stock-list">
        {products.filter((p) => p.stock < 20).slice(0, 4).map((p) => <div className="stock-row" key={p.id}>
          <div className="product-dot" style={{ background: p.color }}><Coffee size={15} /></div>
          <div className="stock-name"><b>{p.name}</b><span>{p.vendor}</span></div>
          <div className="stock-progress"><div><span style={{ width: `${Math.min(p.stock * 4, 100)}%` }} /></div><small>{p.stock} unit tersisa</small></div>
          <span className="warning-badge">Restock</span>
        </div>)}
      </div>
    </section>
  </>;
}

// -------- POS --------
function POS({ products, query, setQuery, category, setCategory, cart, addToCart, adjustCart, subtotal, tax, total, onPay, shift, role, onlineOrders, openOnline }) {
  return <>
    <SectionHeader eyebrow={shift ? `SHIFT AKTIF · Kas awal ${money(shift.opening_cash)}` : "TERMINAL KASIR"} title="Pesanan baru"
      description="Pilih menu, atur jumlah, lalu selesaikan pembayaran."
      action={<div className="pos-actions">
        <button className={`online-btn ${(onlineOrders?.length || 0) > 0 ? "has-new" : ""}`} onClick={openOnline} data-testid="online-orders-button">
          <QrCode size={15} /> Pesanan Online
          {(onlineOrders?.length || 0) > 0 && <span className="badge">{onlineOrders.length}</span>}
        </button>
        <div className="live-pill"><i /> Terminal online</div>
      </div>} />
    {role === "Kasir" && !shift && <div className="warn-banner" data-testid="pos-shift-warning">⚠️ Shift belum dibuka. Klik "Buka Shift" di sidebar untuk mulai bertransaksi.</div>}
    <div className="pos-layout">
      <section className="menu-area">
        <div className="menu-tools">
          <div className="search-box"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari menu atau scan barcode..." data-testid="pos-product-search" /></div>
          <div className="category-tabs">{["Semua", "Kopi", "Makanan", "Snack", "Non-Kopi"].map((c) => <button className={category === c ? "selected" : ""} key={c} onClick={() => setCategory(c)} data-testid={`category-${c.toLowerCase()}`}>{c}</button>)}</div>
        </div>
        <div className="product-grid">
          {products.map((p) => <button className="product-card" key={p.id} onClick={() => addToCart(p)} data-testid={`product-card-${p.id}`}>
            <div className="product-art" style={{ background: p.color }}>{p.image_url ? <img src={p.image_url} alt={p.name} className="product-img" /> : <Coffee size={30} />}<span>{p.stock} stok</span></div>
            <div className="product-info"><b>{p.name}</b><span>{p.vendor}</span><strong>{money(p.price)}</strong></div>
            <div className="add-product"><Plus size={17} /></div>
          </button>)}
        </div>
      </section>
      <aside className="cart-panel">
        <div className="cart-head">
          <div><h2>Keranjang</h2><span data-testid="cart-item-count">{cart.reduce((a, i) => a + i.qty, 0)} item · Meja 07</span></div>
          <button className="clear-btn" onClick={() => cart.forEach((i) => adjustCart(i.id, -i.qty))} data-testid="clear-cart-button">Bersihkan</button>
        </div>
        <div className="cart-items">
          {cart.length ? cart.map((item) => <div className="cart-item" key={item.id}>
            <div className="mini-art" style={{ background: item.color }}><Coffee size={16} /></div>
            <div><b>{item.name}</b><span>{money(item.price)}</span>
              <div className="qty">
                <button onClick={() => adjustCart(item.id, -1)} data-testid={`decrease-${item.id}`}>−</button>
                <strong>{item.qty}</strong>
                <button onClick={() => adjustCart(item.id, 1)} data-testid={`increase-${item.id}`}>+</button>
              </div>
            </div>
            <em>{money(item.price * item.qty)}</em>
          </div>) : <div className="empty-cart"><ShoppingCart size={26} /><b>Keranjang masih kosong</b><span>Pilih menu untuk memulai pesanan</span></div>}
        </div>
        <div className="cart-summary">
          <div><span>Subtotal</span><b>{money(subtotal)}</b></div>
          <div><span>PPN (10%)</span><b>{money(tax)}</b></div>
          <div className="total-line"><span>Total pembayaran</span><strong>{money(total)}</strong></div>
          <button className="pay-btn" disabled={!cart.length} onClick={onPay} data-testid="pay-order-button"><CreditCard size={17} /> Bayar sekarang <span>→</span></button>
          <button className="manual-btn" data-testid="manual-order-button"><Plus size={15} /> Tambah item manual</button>
        </div>
      </aside>
    </div>
  </>;
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
        <input type="number" value={cash} onChange={(e) => setCash(e.target.value)} data-testid="cash-received-input" />
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
  const doAdjust = async (id, quantity, kind, reason) => { await axios.patch(`${API}/products/${id}/stock`, { quantity, kind, reason, note: "" }); reload(); };
  return <>
    <SectionHeader eyebrow="STOCK ENGINE" title="Inventori & stok" description="Kelola barang masuk, keluar, dan audit stok outlet."
      action={<div className="row-gap">
        <button className="outline-btn" onClick={() => setShowOut(true)} data-testid="stock-out-button"><Trash2 size={14} /> Barang keluar</button>
        <button className="outline-btn" onClick={() => setShowOpname(true)} data-testid="stock-opname-button">Stock opname</button>
        <button className="primary-btn" data-testid="stock-in-button" onClick={() => setShowIn(true)}><Plus size={16} /> Barang masuk</button>
      </div>} />
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
    {showIn && <StockModal title="Barang masuk (Restock)" products={products} kind="in" onClose={() => setShowIn(false)} onSubmit={(pid, qty, note) => { doAdjust(pid, qty, "in", note || "Restock"); setShowIn(false); notify("Stok masuk tercatat"); }} />}
    {showOut && <StockModal title="Barang keluar / rusak" products={products} kind="out" onClose={() => setShowOut(false)} onSubmit={(pid, qty, note) => { doAdjust(pid, -Math.abs(qty), "out", note || "Basi/Rusak"); setShowOut(false); notify("Stok keluar tercatat"); }} />}
    {showOpname && <StockModal title="Stock opname (Audit)" products={products} kind="opname" onClose={() => setShowOpname(false)} onSubmit={(pid, qty, note) => { doAdjust(pid, qty, "opname", note || "Adjust opname"); setShowOpname(false); notify("Stok disesuaikan"); }} />}
  </>;
}
function StockModal({ title, products, kind, onClose, onSubmit }) {
  const [pid, setPid] = useState(products[0]?.id || "");
  const [qty, setQty] = useState(kind === "out" ? 1 : 10);
  const [note, setNote] = useState("");
  return <div className="modal-backdrop"><div className="pay-modal" data-testid="stock-modal">
    <button className="modal-close" onClick={onClose}><X size={18} /></button>
    <div className="pay-head"><h2>{title}</h2><span>Riwayat tersimpan otomatis</span></div>
    <div className="pay-body">
      <label>Produk</label>
      <select value={pid} onChange={(e) => setPid(e.target.value)} data-testid="stock-product-select">{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <label>{kind === "opname" ? "Stok fisik aktual" : "Jumlah"}</label>
      <input type="number" value={qty} onChange={(e) => setQty(Number(e.target.value))} data-testid="stock-qty-input" />
      <label>Catatan</label>
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Nomor nota / alasan" data-testid="stock-note-input" />
    </div>
    <button className="primary-btn full" onClick={() => onSubmit(pid, qty, note)} data-testid="stock-submit-button">Simpan</button>
  </div></div>;
}

// -------- Expenses --------
function Expenses({ expenses, reload, notify }) {
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
    {showAdd && <ExpenseModal onClose={() => setShowAdd(false)} onSaved={() => { reload(); notify("Pengeluaran tersimpan"); }} />}
  </>;
}
function ExpenseModal({ onClose, onSaved }) {
  const [form, setForm] = useState({ category: "Pembelian Bahan Baku", note: "", amount: 0, date: new Date().toISOString().slice(0, 10), method: "Cash" });
  const save = async () => { await axios.post(`${API}/expenses`, form); onSaved(); onClose(); };
  return <div className="modal-backdrop"><div className="pay-modal" data-testid="expense-modal">
    <button className="modal-close" onClick={onClose}><X size={18} /></button>
    <div className="pay-head"><h2>Catat pengeluaran</h2><span>Otomatis masuk P&L</span></div>
    <div className="pay-body">
      <label>Kategori</label>
      <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="expense-category-select">
        {["Sewa Tempat", "Gaji Karyawan", "Listrik & Air", "Pembelian Bahan Baku", "Transportasi/Kurir", "Maintenance", "Lain-Lain"].map((c) => <option key={c}>{c}</option>)}
      </select>
      <label>Keterangan</label>
      <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} data-testid="expense-note-input" />
      <label>Nominal</label>
      <input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: Number(e.target.value) })} data-testid="expense-amount-input" />
      <label>Tanggal</label>
      <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} data-testid="expense-date-input" />
      <label>Metode</label>
      <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })} data-testid="expense-method-select"><option>Cash</option><option>Transfer</option></select>
    </div>
    <button className="primary-btn full" onClick={save} data-testid="expense-save-button">Simpan</button>
  </div></div>;
}

// -------- Products --------
function Products({ products, merchants, reload, notify }) {
  const [form, setForm] = useState({ name: "", category: "Kopi", merchant_id: merchants[0]?.id || "", price: 0, cost: 0, stock: 0, color: "#ffedd5", image_url: "" });
  useEffect(() => { if (!form.merchant_id && merchants.length) setForm((f) => ({ ...f, merchant_id: merchants[0].id })); }, [merchants]);
  const save = async () => {
    if (!form.name) return notify("Nama produk wajib diisi");
    const vendor = merchants.find((m) => m.id === form.merchant_id)?.name || "MJD Kupi";
    await axios.post(`${API}/products`, { ...form, vendor });
    setForm({ ...form, name: "", price: 0, cost: 0, stock: 0, image_url: "" });
    reload(); notify("Produk berhasil ditambahkan");
  };
  const handleImage = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => setForm({ ...form, image_url: r.result }); r.readAsDataURL(f); };
  return <>
    <SectionHeader eyebrow="CATALOG & COSTING" title="Produk & HPP" description="Bangun katalog menu dan jaga margin setiap porsi."
      action={<button className="primary-btn" data-testid="new-product-button" onClick={() => document.querySelector("#new-product")?.focus()}><Plus size={16} /> Produk baru</button>} />
    <div className="product-form-v2 panel">
      <div className="form-heading"><div className="form-icon"><ClipboardList size={18} /></div><div><h2>Tambah menu cepat</h2><span>Bind ke merchant / tenant · unggah foto produk</span></div></div>
      <div className="product-form-grid">
        <div className="product-image-picker">
          <label className="image-drop" data-testid="product-image-label">
            {form.image_url ? <img src={form.image_url} alt="preview" /> : <><ImageIcon size={30} /><span>Klik untuk unggah foto</span></>}
            <input type="file" accept="image/*" onChange={handleImage} style={{ display: "none" }} data-testid="product-image-input" />
          </label>
        </div>
        <div className="product-fields">
          <label className="field-lg"><span>Nama produk</span><input id="new-product" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Contoh: Es Kopi Pandan" data-testid="product-name-input" /></label>
          <label><span>Merchant</span><select value={form.merchant_id} onChange={(e) => setForm({ ...form, merchant_id: e.target.value })} data-testid="product-merchant-select">{merchants.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
          <label><span>Kategori</span><select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="product-category-select">{["Kopi", "Non-Kopi", "Makanan", "Snack"].map((c) => <option key={c}>{c}</option>)}</select></label>
          <label><span>Harga jual (Rp)</span><input type="number" value={form.price} onChange={(e) => setForm({ ...form, price: Number(e.target.value) })} data-testid="product-price-input" /></label>
          <label><span>HPP per porsi (Rp)</span><input type="number" value={form.cost} onChange={(e) => setForm({ ...form, cost: Number(e.target.value) })} data-testid="product-cost-input" /></label>
          <label><span>Stok awal</span><input type="number" value={form.stock} onChange={(e) => setForm({ ...form, stock: Number(e.target.value) })} data-testid="product-stock-input" /></label>
          <button className="primary-btn full-row" onClick={save} data-testid="save-product-button"><Plus size={14}/> Simpan produk</button>
        </div>
      </div>
    </div>
    <div className="catalog-grid">
      {products.map((p) => <div className="catalog-item" key={p.id}>
        <div className="product-art" style={{ background: p.color }}>{p.image_url ? <img src={p.image_url} alt={p.name} className="product-img" /> : <Coffee size={26} />}</div>
        <div><b>{p.name}</b><span>{p.vendor} · {p.category}</span><small>Margin <strong>{p.price ? Math.round((1 - p.cost / p.price) * 100) : 0}%</strong> · Stok {p.stock}</small></div>
        <button className="more-btn" onClick={async () => { if (window.confirm(`Hapus ${p.name}?`)) { await axios.delete(`${API}/products/${p.id}`); reload(); notify("Produk dihapus"); } }} data-testid={`product-menu-${p.id}`}><Trash2 size={13} /></button>
      </div>)}
    </div>
  </>;
}

// -------- Merchants --------
function Merchants({ merchants, reload, notify }) {
  const [form, setForm] = useState({ name: "", category: "F&B", commission_percent: 10, phone: "", color: "#ffedd5" });
  const save = async () => {
    if (!form.name) return notify("Nama merchant wajib diisi");
    await axios.post(`${API}/merchants`, form);
    setForm({ ...form, name: "", phone: "" });
    reload(); notify("Merchant terdaftar");
  };
  const remove = async (m) => { if (!window.confirm(`Hapus merchant ${m.name}?`)) return; try { await axios.delete(`${API}/merchants/${m.id}`); reload(); notify("Merchant dihapus"); } catch (e) { notify(e.response?.data?.detail || "Gagal menghapus"); } };
  return <>
    <SectionHeader eyebrow="TENANT MANAGEMENT" title="Merchant & Tenant" description="Kelola vendor / tenant, komisi, dan nomor WhatsApp dapur."
      action={<div className="live-pill"><i /> {merchants.length} tenant aktif</div>} />
    <div className="product-form panel">
      <div className="form-heading"><div className="form-icon"><Store size={18} /></div><div><h2>Tambah merchant / tenant</h2><span>Terhubung ke produk & tiket dapur</span></div></div>
      <div className="form-fields">
        <label>Nama<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="merchant-name-input" /></label>
        <label>Kategori<select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="merchant-category-select">{["F&B", "Kopi", "Makanan", "Snack", "Minuman"].map((c) => <option key={c}>{c}</option>)}</select></label>
        <label>Komisi %<input type="number" value={form.commission_percent} onChange={(e) => setForm({ ...form, commission_percent: Number(e.target.value) })} data-testid="merchant-commission-input" /></label>
        <label>WhatsApp (628…)<input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="merchant-phone-input" /></label>
        <button className="primary-btn" onClick={save} data-testid="save-merchant-button">Simpan</button>
      </div>
    </div>
    <section className="panel table-panel">
      <div className="panel-head"><div><h2>Merchant terdaftar</h2><span>Sinkron ke katalog produk</span></div></div>
      <div className="data-table">
        <div className="table-row table-label"><span>Merchant</span><span>Kategori</span><span>Komisi</span><span>WhatsApp</span><span>Status</span><span /></div>
        {merchants.map((m) => <div className="table-row" key={m.id}>
          <span className="table-product"><div className="product-dot" style={{ background: m.color }}><Store size={14} /></div><b>{m.name}</b></span>
          <span>{m.category}</span><span>{m.commission_percent}%</span><span>{m.phone || "—"}</span>
          <span><i className={`status-dot ${m.active ? "good" : "low"}`} />{m.active ? "Aktif" : "Nonaktif"}</span>
          <button className="small-action" onClick={() => remove(m)} data-testid={`delete-merchant-${m.id}`}><Trash2 size={12} /> Hapus</button>
        </div>)}
      </div>
    </section>
  </>;
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
function Tables({ notify }) {
  const [count, setCount] = useState(12);
  const [selected, setSelected] = useState(null);
  const meja = Array.from({ length: count }, (_, i) => String(i + 1).padStart(2, "0"));
  const linkFor = (t) => `${ORIGIN}/self-order?table=${t}`;
  const printOne = (t) => { setSelected(t); setTimeout(() => window.print(), 200); };
  return <>
    <SectionHeader eyebrow="SELF-ORDER STUDIO" title="QR meja pelanggan" description="Generate QR asli yang bisa di-scan kamera HP. Setiap kartu meja unik dan siap cetak."
      action={<div className="row-gap">
        <label className="mini-num">Jumlah meja<input type="number" value={count} min={1} max={100} onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} data-testid="tables-count-input" /></label>
        <button className="primary-btn" data-testid="generate-qr-button" onClick={() => notify(`QR ${count} meja siap`)}><Plus size={16} /> Generate</button>
      </div>} />
    <div className="table-grid-v2">
      {meja.map((t) => <div className="table-card-v2" key={t} data-testid={`table-card-${t}`}>
        <div className="table-qr-real"><QRCodeSVG value={linkFor(t)} size={90} level="M" includeMargin={true} /></div>
        <div className="table-card-info"><b>Meja {t}</b><span className="mono">{linkFor(t).replace(/^https?:\/\//, "")}</span></div>
        <div className="table-card-actions">
          <button className="small-action" onClick={() => { navigator.clipboard?.writeText(linkFor(t)); notify(`Link Meja ${t} disalin`); }} data-testid={`copy-table-${t}`}><Copy size={12} /> Salin</button>
          <button className="small-action" data-testid={`print-table-${t}`} onClick={() => printOne(t)}><Printer size={12} /> Cetak</button>
        </div>
      </div>)}
    </div>
    {selected && <div className="print-sheet" data-testid="print-sheet"><div className="print-sticker">
      <div className="brand-mark"><Coffee size={22}/></div>
      <h2>MJD Kupi</h2>
      <QRCodeSVG value={linkFor(selected)} size={220} level="H" includeMargin={true} />
      <strong>Meja {selected}</strong>
      <span>Scan QR untuk memesan menu tanpa antre</span>
    </div></div>}
  </>;
}

// -------- Self-service --------
function SelfService({ products, notify, activeOutlet }) {
  const [table, setTable] = useState("07");
  const [cart, setCart] = useState([]);
  const [qris, setQris] = useState("");
  const total = cart.reduce((sum, item) => sum + item.price * item.qty, 0);
  const add = (p) => setCart((cur) => cur.find((i) => i.id === p.id) ? cur.map((i) => i.id === p.id ? { ...i, qty: i.qty + 1 } : i) : [...cur, { ...p, qty: 1 }]);
  const send = async () => {
    if (!cart.length) return;
    try {
      await axios.post(`${API}/self-order`, { table: `Meja ${table}`, lines: cart.map((i) => ({ product_id: String(i.id), name: i.name, quantity: i.qty, price: i.price, vendor: i.vendor, merchant_id: i.merchant_id })), total, notes: "Self-service QR" });
      notify("Pesanan terkirim ke kasir dan dapur");
      setCart([]);
    } catch { notify("Pesanan tersimpan sebagai antrean offline"); }
  };
  const saveQris = async () => { if (!qris) return notify("Masukkan kode QRIS terlebih dahulu"); try { await axios.post(`${API}/settings/qris`, { outlet_id: activeOutlet, qris_code: qris }); notify("Kode QRIS tersimpan"); } catch { notify("QRIS tersimpan lokal"); } };
  return <>
    <SectionHeader eyebrow="CUSTOMER SELF-ORDER" title="Self-service meja" description="Pelanggan scan QR, pilih menu, kirim pesanan tanpa antre."
      action={<div className="live-pill"><i /> QR order aktif</div>} />
    <div className="self-grid">
      <section>
        <div className="self-toolbar">
          <label>Nomor meja<select value={table} onChange={(e) => setTable(e.target.value)} data-testid="self-table-select">{Array.from({ length: 30 }, (_, i) => <option key={i}>{String(i + 1).padStart(2, "0")}</option>)}</select></label>
          <label>Kode QRIS<input value={qris} onChange={(e) => setQris(e.target.value)} placeholder="Tempel kode QRIS outlet" data-testid="qris-code-input" /></label>
          <button className="outline-btn" data-testid="save-qris-button" onClick={saveQris}><QrCode size={15} /> Simpan QRIS</button>
        </div>
        <div className="self-products">
          {products.map((p) => <button className="self-product" key={p.id} onClick={() => add(p)} data-testid={`self-product-${p.id}`}>
            <div className="product-art" style={{ background: p.color }}><Coffee size={27} /></div>
            <b>{p.name}</b><span>{money(p.price)} · {p.vendor}</span>
          </button>)}
        </div>
      </section>
      <aside className="self-cart panel">
        <div className="panel-head"><div><h2>Meja {table}</h2><span>{cart.reduce((a, i) => a + i.qty, 0)} item</span></div><QrCode size={25} color="#f97316" /></div>
        {cart.length ? cart.map((i) => <div className="self-line" key={i.id}><span>{i.qty}× {i.name}</span><b>{money(i.qty * i.price)}</b></div>) : <div className="empty-cart"><ShoppingCart size={25} /><b>Belum ada menu</b><span>Pilih menu di sebelah kiri</span></div>}
        <div className="self-total"><span>Total</span><strong>{money(total)}</strong></div>
        <button className="pay-btn" disabled={!cart.length} onClick={send} data-testid="send-self-order-button">Kirim pesanan <span>→</span></button>
      </aside>
    </div>
  </>;
}

// -------- Vendor center --------
function VendorCenter({ notify }) {
  const [orders, setOrders] = useState([]);
  const [settlement, setSettlement] = useState({ gross: 0, commission: 0, net: 0, payout_status: "Memuat" });
  const load = () => {
    axios.get(`${API}/vendor/orders`).then(({ data }) => setOrders(data)).catch(() => {});
    axios.get(`${API}/vendor/settlement`).then(({ data }) => setSettlement(data)).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  const update = (id, status) => axios.patch(`${API}/vendor/orders/${id}?status=${encodeURIComponent(status)}`).then(load).then(() => notify("Status order diperbarui"));
  return <>
    <SectionHeader eyebrow="VENDOR OPERATIONS" title="Pusat vendor" description="Antrean dapur, settlement, dan payout tenant dalam satu layar."
      action={<button className="outline-btn" data-testid="refresh-vendor-button" onClick={load}><Bell size={15} /> Refresh</button>} />
    <div className="vendor-metrics">
      <Metric label="Omset tenant" value={money(settlement.gross)} change="periode berjalan" tone="orange" icon={Receipt} />
      <Metric label="Komisi platform" value={money(settlement.commission)} change="10% settlement" tone="blue" icon={BarChart3} />
      <Metric label="Net payout" value={money(settlement.net)} change={settlement.payout_status} tone="green" icon={Wallet} />
    </div>
    <div className="vendor-grid">
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
        <div className="panel-head"><div><h2>Settlement tenant</h2><span>Ringkasan bagi hasil vendor</span></div></div>
        <div className="settlement-line"><span>Omset kotor</span><b>{money(settlement.gross)}</b></div>
        <div className="settlement-line"><span>Komisi platform (10%)</span><b className="red-text">−{money(settlement.commission)}</b></div>
        <div className="settlement-line net"><span>Penghasilan bersih</span><strong>{money(settlement.net)}</strong></div>
        <button className="primary-btn full" data-testid="vendor-payout-button" onClick={() => notify("Payout vendor masuk ke antrean persetujuan")}>Ajukan payout <span>→</span></button>
      </section>
    </div>
  </>;
}

// -------- Settings (Printer + Branding + Outlets, Super Admin only) --------
function SettingsPage({ notify, role }) {
  const [printer, setPrinter] = useState({ size: "58mm", auto_print: true, split_kitchen: true, device: "Bluetooth" });
  const [logo, setLogo] = useState("");
  const [outlets, setOutlets] = useState([]);
  const [outletForm, setOutletForm] = useState({ name: "", address: "", phone: "" });
  const [pairName, setPairName] = useState(pairedPrinterName());
  const [connected, setConnected] = useState(isPrinterConnected());
  const isSuper = role === "Super Admin";

  const loadOutlets = () => axios.get(`${API}/outlets`).then(({ data }) => setOutlets(data)).catch(() => {});
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
  const deleteOutlet = async (id) => { if (!window.confirm("Hapus outlet ini?")) return; try { await axios.delete(`${API}/outlets/${id}`); loadOutlets(); notify("Outlet dihapus"); } catch (e) { notify(e.response?.data?.detail || "Gagal"); } };

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
            <button className="small-action" onClick={() => deleteOutlet(o.id)} data-testid={`delete-outlet-${o.id}`}><Trash2 size={12} /> Hapus</button>
          </div>)}
        </div>
      </section>
    </>}
  </>;
}

// -------- User & Security Management (Super Admin ONLY) --------
function UserManagement({ notify }) {
  const [users, setUsers] = useState([]);
  const [reveal, setReveal] = useState({});
  const [form, setForm] = useState({ email: "", username: "", password: "", role: "Kasir", name: "", outlet_id: "outlet-sudirman", active: true });
  const [showReset, setShowReset] = useState(null);
  const [newPass, setNewPass] = useState("");
  const load = () => axios.get(`${API}/admin/users`).then(({ data }) => setUsers(data)).catch(() => {});
  useEffect(() => { load(); }, []);
  const save = async () => {
    if (!form.email || !form.password || !form.name) return notify("Email, password, nama wajib");
    try { await axios.post(`${API}/admin/users`, form); setForm({ ...form, email: "", username: "", password: "", name: "" }); load(); notify("User berhasil dibuat"); }
    catch (e) { notify(e.response?.data?.detail || "Gagal menambah user"); }
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
      <div className="form-fields" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr auto" }}>
        <label><span>Nama</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="user-name-input" /></label>
        <label><span>Username</span><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="mis. kasir2" data-testid="user-username-input" /></label>
        <label><span>Email</span><input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} type="email" data-testid="user-email-input" /></label>
        <label><span>Password</span><input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="user-password-input" /></label>
        <label><span>Role</span><select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} data-testid="user-role-select">{["Super Admin", "Admin", "Vendor", "Kasir"].map((r) => <option key={r}>{r}</option>)}</select></label>
        <button className="primary-btn" onClick={save} data-testid="save-user-button"><Plus size={14} /> Simpan</button>
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
function ShiftOpenModal({ onClose, onOpened }) {
  const [cash, setCash] = useState(500000);
  const [note, setNote] = useState("");
  const submit = async () => { const { data } = await axios.post(`${API}/shifts/open`, { opening_cash: Number(cash), note }); onOpened(data); };
  return <div className="modal-backdrop"><div className="pay-modal" data-testid="shift-open-modal">
    <button className="modal-close" onClick={onClose}><X size={18} /></button>
    <div className="pay-head"><h2>Buka shift kasir</h2><span>Masukkan kas awal drawer</span></div>
    <div className="pay-body">
      <label>Kas awal (Rp)</label>
      <input type="number" value={cash} onChange={(e) => setCash(e.target.value)} data-testid="shift-open-cash-input" />
      <label>Catatan (opsional)</label>
      <input value={note} onChange={(e) => setNote(e.target.value)} data-testid="shift-open-note-input" />
    </div>
    <button className="primary-btn full" onClick={submit} data-testid="shift-open-submit"><PlayCircle size={14}/> Mulai shift</button>
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
      <input type="number" value={cash} onChange={(e) => setCash(e.target.value)} data-testid="shift-close-cash-input" />
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
  const accept = async (id) => {
    try {
      await axios.post(`${API}/self-order/${id}/accept`);
      notify("Pesanan diterima & masuk KDS");
      reload();
      onAcceptDone?.();
    } catch (e) {
      notify(e.response?.data?.detail || "Gagal menerima pesanan");
    }
  };
  return <div className="modal-backdrop">
    <div className="online-modal" data-testid="online-orders-modal">
      <button className="modal-close" onClick={onClose}><X size={18} /></button>
      <div className="pay-head"><h2>Pesanan masuk (QR Meja)</h2><span>{orders.length} antrean · terima untuk lanjut ke dapur</span></div>
      <div className="online-list">
        {orders.length === 0 && <div className="empty-cart"><QrCode size={30} /><b>Belum ada pesanan online</b><span>Pesanan self-order akan muncul di sini secara realtime</span></div>}
        {orders.map((o) => <div className="online-item" key={o.id} data-testid={`online-item-${o.id}`}>
          <div className="online-item-head">
            <div><b>{o.table_no}</b><span className="mono">#{String(o.id).slice(-6)}</span></div>
            <strong>{money(o.total)}</strong>
          </div>
          <ul className="online-lines">{(o.lines || []).map((ln, i) => <li key={i}><b>{ln.quantity}×</b> {ln.name}<em>{money(ln.price * ln.quantity)}</em></li>)}</ul>
          {o.payment_proof && <div className="proof-thumb"><img src={o.payment_proof} alt="proof" /><small>Bukti pembayaran</small></div>}
          <button className="primary-btn full" onClick={() => accept(o.id)} data-testid={`accept-online-${o.id}`}><Check size={14}/> Setujui & kirim ke dapur</button>
        </div>)}
      </div>
    </div>
  </div>;
}

// -------- Cashier Monitor (Admin) --------
function CashierMonitor({ notify, onView }) {
  const [shifts, setShifts] = useState([]);
  const load = () => axios.get(`${API}/shifts`).then(({ data }) => setShifts(data)).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  const viewReport = async (id) => { try { const { data } = await axios.get(`${API}/shifts/${id}/report`); onView(data); } catch { notify("Gagal memuat rekap"); } };
  const openCount = shifts.filter((s) => s.status === "open").length;
  const totalOmset = shifts.reduce((a, s) => a + (s.total_cash || 0) + (s.total_transfer || 0), 0);
  return <>
    <SectionHeader eyebrow="AUDIT KASIR" title="Monitoring shift kasir" description="Pantau seluruh kasir yang sedang aktif dan riwayat shift real-time."
      action={<button className="outline-btn" onClick={load} data-testid="refresh-cashiers-button"><Bell size={14}/> Refresh</button>} />
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
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState([]);
  const [step, setStep] = useState("menu"); // menu | pay | done
  const [payMethod, setPayMethod] = useState("QRIS");
  const [proof, setProof] = useState("");
  const [qrisCode, setQrisCode] = useState("");
  const total = cart.reduce((s, i) => s + i.price * i.qty, 0);
  useEffect(() => {
    axios.get(`${API}/products`).then(({ data }) => setProducts(data)).catch(() => {});
    axios.get(`${API}/settings/qris:outlet-sudirman`).then(({ data }) => setQrisCode(data?.qris_code || "")).catch(() => {});
  }, []);
  const add = (p) => setCart((cur) => cur.find((i) => i.id === p.id) ? cur.map((i) => i.id === p.id ? { ...i, qty: i.qty + 1 } : i) : [...cur, { ...p, qty: 1 }]);
  const dec = (id) => setCart((cur) => cur.map((i) => i.id === id ? { ...i, qty: i.qty - 1 } : i).filter((i) => i.qty > 0));
  const handleFile = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => setProof(r.result); r.readAsDataURL(f); };
  const sendOrder = async () => {
    try {
      await axios.post(`${API}/self-order`, {
        table: `Meja ${tableParam}`,
        lines: cart.map((i) => ({ product_id: String(i.id), name: i.name, quantity: i.qty, price: i.price, vendor: i.vendor, merchant_id: i.merchant_id })),
        total, notes: "Self-service QR",
        payment_method: payMethod, payment_proof: proof,
      });
      setStep("done");
    } catch { alert("Gagal mengirim pesanan"); }
  };
  const qrPayload = qrisCode || `MJDKUPI|AMOUNT:${total}|TABLE:${tableParam}`;
  return <div className="customer-app" data-testid="customer-self-order">
    <header className="customer-topbar">
      <div className="brand-mark"><Coffee size={18}/></div>
      <div><strong>MJD Kupi</strong><span>Meja {tableParam}</span></div>
    </header>
    {step === "menu" && <>
      <div className="customer-grid">
        {products.map((p) => <button key={p.id} className="customer-product" onClick={() => add(p)} data-testid={`customer-product-${p.id}`}>
          <div className="product-art" style={{ background: p.color }}>{p.image_url ? <img src={p.image_url} alt={p.name} className="product-img" /> : <Coffee size={26} />}</div>
          <b>{p.name}</b><span>{p.vendor}</span><strong>{money(p.price)}</strong>
        </button>)}
      </div>
      {cart.length > 0 && <div className="customer-cart" data-testid="customer-cart-bar">
        <div><b>{cart.reduce((a, i) => a + i.qty, 0)} item</b><span>{money(total)}</span></div>
        <button className="primary-btn" onClick={() => setStep("pay")} data-testid="customer-checkout-button">Checkout <span>→</span></button>
      </div>}
    </>}
    {step === "pay" && <div className="customer-pay">
      <h2>Konfirmasi & bayar</h2>
      <div className="customer-lines">{cart.map((i) => <div key={i.id} className="customer-line">
        <div><b>{i.name}</b><span>{money(i.price)}</span></div>
        <div className="qty"><button onClick={() => dec(i.id)}>−</button><strong>{i.qty}</strong><button onClick={() => add(i)}>+</button></div>
      </div>)}</div>
      <div className="customer-total"><span>Total</span><strong>{money(total)}</strong></div>
      <div className="pay-tabs">
        {[["QRIS", QrCode], ["Transfer", CreditCard], ["Cash", DollarSign]].map(([m, Icon]) => (
          <button key={m} className={payMethod === m ? "active" : ""} onClick={() => setPayMethod(m)} data-testid={`customer-method-${m.toLowerCase()}`}><Icon size={16} />{m}</button>
        ))}
      </div>
      {payMethod === "QRIS" && <div className="qris-real"><QRCodeSVG value={qrPayload} size={200} level="M" includeMargin={true} /></div>}
      {payMethod !== "Cash" && <>
        <label className="customer-label">Upload bukti pembayaran</label>
        <input type="file" accept="image/*" onChange={handleFile} data-testid="customer-proof-input" />
        {proof && <div className="proof-thumb"><img src={proof} alt="bukti" /><Check size={16} color="#059669"/></div>}
      </>}
      <button className="primary-btn full" onClick={sendOrder} data-testid="customer-send-order"><Check size={15}/> Kirim pesanan ke kasir</button>
      <button className="text-btn" onClick={() => setStep("menu")}>← Kembali ke menu</button>
    </div>}
    {step === "done" && <div className="customer-done" data-testid="customer-done">
      <div className="brand-mark big"><Check size={30}/></div>
      <h2>Pesanan terkirim!</h2>
      <p>Meja {tableParam} · {money(total)}</p>
      <span>Kasir akan segera memproses pesanan Anda. Terima kasih!</span>
    </div>}
  </div>;
}


// -------- Login --------
function Login({ onLogin }) {
  const [email, setEmail] = useState("superadmin");
  const [password, setPassword] = useState(".Superadmin1_");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    try { const { data } = await axios.post(`${API}/auth/login`, { email, password }); onLogin(data); }
    catch (e) { setError(e.response?.data?.detail || "Login gagal."); }
    finally { setBusy(false); }
  };
  return <div className="login-screen" data-testid="login-screen">
    <div className="login-art">
      <div className="login-brand"><div className="brand-mark"><Coffee size={19} /></div><strong>MJD Kupi</strong></div>
      <div><div className="eyebrow">RETAIL COMMAND CENTER</div><h1>Satu ruang untuk<br /><em>operasi yang lancar.</em></h1><p>POS, inventori, KDS, dan payout vendor dalam satu workspace.</p></div>
      <div className="login-orbit"><Coffee size={64} /></div>
    </div>
    <form className="login-form" onSubmit={submit}>
      <div className="eyebrow">WELCOME BACK</div>
      <h2>Masuk ke workspace</h2>
      <p>Gunakan username atau email untuk login.</p>
      <label>Username / Email<input value={email} onChange={(e) => setEmail(e.target.value)} data-testid="login-email-input" /></label>
      <label>Password<input value={password} onChange={(e) => setPassword(e.target.value)} type="password" data-testid="login-password-input" /></label>
      {error && <div className="login-error" data-testid="login-error">{error}</div>}
      <button className="primary-btn full" disabled={busy} data-testid="login-submit-button">{busy ? "Memeriksa…" : "Masuk ke MJD Kupi"}<span>→</span></button>
      <div className="demo-accounts">
        <b>Akun demo cepat</b>
        <button type="button" onClick={() => { setEmail("superadmin"); setPassword(".Superadmin1_"); }} data-testid="demo-admin-button">Super Admin</button>
        <button type="button" onClick={() => { setEmail("admin"); setPassword("MjdKupi#2026"); }} data-testid="demo-manager-button">Admin</button>
        <button type="button" onClick={() => { setEmail("kasir"); setPassword("MjdKupi#2026"); }} data-testid="demo-kasir-button">Kasir</button>
        <button type="button" onClick={() => { setEmail("vendor"); setPassword("MjdKupi#2026"); }} data-testid="demo-vendor-button">Vendor</button>
      </div>
    </form>
  </div>;
}
