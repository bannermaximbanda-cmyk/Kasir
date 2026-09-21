import React from "react";

/**
 * Global error boundary. Catches any render-phase throw inside the app tree
 * and replaces the crashed subtree with a friendly recovery panel — instead
 * of blanking the entire SPA (as happened when a single unguarded
 * `p.outlet_id.replace(...)` in Overview crashed the whole app on prod).
 *
 * NOTE: only catches render errors. Async errors (Promise rejections, event
 * handlers) still surface via the existing toast/notify system.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // Console log so devs / support agents can grab stack from browser inspector.
    // eslint-disable-next-line no-console
    console.error("[MJD Kupi] Render crash caught by ErrorBoundary:", error, info);
  }

  reset = () => {
    this.setState({ error: null, info: null });
  };

  reload = () => {
    try { window.location.reload(); } catch { /* ignore */ }
  };

  render() {
    if (!this.state.error) return this.props.children;
    const msg = String(this.state.error?.message || this.state.error || "Unknown error");
    return (
      <div style={styles.wrap} data-testid="error-boundary-panel">
        <div style={styles.card}>
          <div style={styles.badge}>⚠️ Terjadi kesalahan render</div>
          <h1 style={styles.title}>Ada bagian aplikasi yang gagal dimuat</h1>
          <p style={styles.body}>
            Kami sudah mencegah seluruh aplikasi ikut blank. Coba <b>Muat ulang</b> halaman
            ini. Jika masalah berulang, silakan hubungi Super Admin.
          </p>
          <details style={styles.details}>
            <summary style={styles.summary}>Detail teknis (untuk developer)</summary>
            <pre style={styles.pre}>{msg}</pre>
            {this.state.info?.componentStack && (
              <pre style={styles.pre}>{this.state.info.componentStack.slice(0, 1200)}</pre>
            )}
          </details>
          <div style={styles.actions}>
            <button type="button" onClick={this.reload} style={styles.primary} data-testid="error-boundary-reload">
              Muat ulang halaman
            </button>
            <button type="button" onClick={this.reset} style={styles.secondary} data-testid="error-boundary-reset">
              Coba render ulang
            </button>
          </div>
        </div>
      </div>
    );
  }
}

const styles = {
  wrap: {
    minHeight: "100vh",
    display: "grid",
    placeItems: "center",
    padding: 24,
    background: "linear-gradient(135deg,#fff7ed 0%,#ffffff 60%)",
    fontFamily: "'Inter', system-ui, sans-serif",
    color: "#1c1917",
  },
  card: {
    maxWidth: 560,
    width: "100%",
    background: "#ffffff",
    border: "1px solid #fed7aa",
    borderRadius: 16,
    padding: "32px 28px",
    boxShadow: "0 12px 40px -12px rgba(249,115,22,0.35)",
  },
  badge: {
    display: "inline-block",
    padding: "4px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: "#9a3412",
    background: "#fef3c7",
    borderRadius: 999,
    marginBottom: 12,
  },
  title: { fontSize: 22, fontWeight: 700, margin: "6px 0 8px" },
  body: { fontSize: 14, lineHeight: 1.6, color: "#57534e", margin: "0 0 16px" },
  details: {
    background: "#fafaf9",
    border: "1px solid #e7e5e4",
    borderRadius: 10,
    padding: "10px 12px",
    marginBottom: 20,
  },
  summary: { cursor: "pointer", fontSize: 12, fontWeight: 600, color: "#57534e" },
  pre: {
    fontSize: 11,
    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
    overflowX: "auto",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    color: "#78716c",
    margin: "8px 0 0",
  },
  actions: { display: "flex", gap: 10, flexWrap: "wrap" },
  primary: {
    padding: "10px 18px",
    background: "#f97316",
    color: "#ffffff",
    border: 0,
    borderRadius: 10,
    fontWeight: 700,
    cursor: "pointer",
  },
  secondary: {
    padding: "10px 18px",
    background: "transparent",
    color: "#9a3412",
    border: "1px solid #fed7aa",
    borderRadius: 10,
    fontWeight: 600,
    cursor: "pointer",
  },
};
