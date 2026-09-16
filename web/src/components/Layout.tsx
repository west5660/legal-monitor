import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";

const links = [
  { to: "/", label: "Обзор", end: true },
  { to: "/documents", label: "Документы" },
  { to: "/exports", label: "Выгрузки" },
  { to: "/pipeline", label: "Конвейер" },
  { to: "/profiles", label: "Профили" },
  { to: "/activity", label: "Журнал" },
];

export default function Layout() {
  const [apiDown, setApiDown] = useState(false);

  useEffect(() => {
    const check = () => {
      api
        .health()
        .then((h) => setApiDown(h.db_ok === false))
        .catch(() => setApiDown(true));
    };
    check();
    const t = setInterval(check, 20_000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="app-shell layout">
      <aside className="sidebar">
        <div className="sidebar-logo">Legal Monitor</div>
        <div className="sidebar-sub">Мониторинг законодательства</div>
        <nav>
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        {apiDown && (
          <div
            className="glass-strong"
            style={{
              marginBottom: 16,
              padding: "12px 16px",
              borderColor: "var(--danger, #ff6b6b)",
              color: "var(--danger, #ff6b6b)",
              fontSize: "0.9rem",
            }}
          >
            API не отвечает. Запустите <strong>start_web.bat</strong> в папке legal-monitor (нужны API
            :8000 и UI :5173). Не запускайте только <code>npm run dev</code>.
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
