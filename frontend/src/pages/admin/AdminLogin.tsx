import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api } from "../../api";
import { Icon } from "../../components/Icon";
import { btnPrimary, card, input, label, pageX } from "../../components/styles";
import { ErrorBox } from "../../components/ui";
import { messageFor } from "../../errors";

export function AdminLogin() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(password);
      const next = params.get("next");
      navigate(next && next.startsWith("/admin") ? next : "/admin", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`w-full ${pageX} py-space-xl`}>
      <div className={`${card} shadow-xl max-w-md mx-auto p-space-lg flex flex-col gap-space-md`}>
        <div className="flex items-center gap-space-sm">
          <div className="w-10 h-10 rounded-lg bg-primary-fixed text-primary flex items-center justify-center">
            <Icon name="admin_panel_settings" className="text-[24px]" />
          </div>
          <div>
            <h1 className="font-headline-md text-headline-md text-on-surface">Organizer login</h1>
            <p className="font-body-sm text-body-sm text-on-surface-variant">Sign in to manage events and check tickets in.</p>
          </div>
        </div>
        <form className="space-y-3" onSubmit={onSubmit}>
          <div>
            <label htmlFor="password" className={label}>Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={input}
            />
          </div>
          <button type="submit" disabled={busy} className={`${btnPrimary} w-full`}>
            <Icon name="lock" className="text-[18px]" />
            {busy ? "Logging in…" : "Log in"}
          </button>
        </form>
        {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
      </div>
    </section>
  );
}
