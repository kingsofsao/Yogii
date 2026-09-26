import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useMe } from "../api/hooks";
import { UNAUTHORIZED_EVENT } from "../api/client";
import { LoadingState } from "./ui";

export default function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();

  // Any 401 from the API (for example an expired session) sends the user back to sign in.
  useEffect(() => {
    const onUnauthorized = () => {
      qc.clear();
      navigate("/sign-in", { replace: true, state: { expired: true } });
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [qc, navigate]);

  if (me.isPending) return <LoadingState label="Checking your session…" />;
  if (me.isError || !me.data) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}
