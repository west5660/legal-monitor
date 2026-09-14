import { useEffect, useState } from "react";
import { api, Profile } from "../api/client";
import GlassCard from "../components/GlassCard";

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<Profile[]>([]);

  const load = () => api.profiles().then((r) => setProfiles(r.items)).catch(console.error);

  useEffect(() => {
    load();
  }, []);

  const toggle = async (p: Profile) => {
    await api.toggleProfile(p.id, !p.enabled);
    load();
  };

  return (
    <>
      <h1 className="page-title">Зоны интереса</h1>
      <p className="page-subtitle">Профили для shortlist и LLM-анализа</p>

      {profiles.map((p, i) => (
        <GlassCard key={p.id} className="profile-card" delay={i * 0.03}>
          <div className="profile-header">
            <div>
              <strong>{p.name}</strong>
              <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>{p.id}</div>
            </div>
            <button
              type="button"
              className={`toggle${p.enabled ? " on" : ""}`}
              onClick={() => toggle(p)}
              aria-label={p.enabled ? "Выключить" : "Включить"}
            />
          </div>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", margin: "0 0 8px" }}>
            {p.description}
          </p>
          <div style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>
            {p.keywords_any.slice(0, 12).join(" · ")}
            {p.keywords_any.length > 12 ? " …" : ""}
          </div>
        </GlassCard>
      ))}
    </>
  );
}
