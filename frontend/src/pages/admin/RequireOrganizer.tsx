import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { api } from "../../api";
import { adminContainer } from "../../components/styles";
import { ErrorBox, Loading } from "../../components/ui";
import { errorCode, messageFor } from "../../errors";

/** Gate for /admin/*: asks the API who we are; 401 -> login page (and back afterwards). */
export function RequireOrganizer() {
  const location = useLocation();
  const [state, setState] = useState<"checking" | "ok" | "login" | unknown>("checking");

  useEffect(() => {
    api.me().then(
      () => setState("ok"),
      (err) => setState(errorCode(err) === "unauthorized" ? "login" : err),
    );
  }, [location.pathname]);

  if (state === "checking") return <div className={adminContainer}><Loading what="Checking login" /></div>;
  if (state === "login") {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/admin/login?next=${next}`} replace />;
  }
  if (state !== "ok") return <div className={adminContainer}><ErrorBox>{messageFor(state)}</ErrorBox></div>;
  return <Outlet />;
}
