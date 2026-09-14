import GlassCard from "./GlassCard";

interface LoadStateProps {
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
}

export default function LoadState({ loading, error, onRetry }: LoadStateProps) {
  if (loading) {
    return <p className="page-subtitle">Загрузка…</p>;
  }

  if (error) {
    return (
      <GlassCard className="stat-card">
        <p className="page-subtitle" style={{ color: "var(--danger, #ff6b6b)", marginBottom: 12 }}>
          {error}
        </p>
        {onRetry && (
          <button type="button" className="btn btn-primary" onClick={onRetry}>
            Повторить
          </button>
        )}
      </GlassCard>
    );
  }

  return null;
}
