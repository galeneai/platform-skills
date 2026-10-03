"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

type AuthConfig = {
  credential_login_enabled: boolean;
  sso_connectors: { alias: string; display_name: string }[];
  sso_supported: boolean;
  recovery: { mode: "console"; url: string } | null;
};

class AuthError extends Error {
  constructor(public challenge?: string) {
    super("Accesso non riuscito. Riprova o gestisci l'accesso nella console.");
  }
}

async function post(path: string, body: object): Promise<Response> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new AuthError(response.status === 401 ? data.detail?.challenge : undefined);
  }
  return response;
}

export default function LoginPage() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(true);
  const [needsTotp, setNeedsTotp] = useState(false);
  const callbackHandled = useRef(false);

  useEffect(() => {
    if (callbackHandled.current) return;
    callbackHandled.current = true;
    async function initialize() {
      try {
        const url = new URL(window.location.href);
        const transaction = url.searchParams.get("sso_transaction");
        if (transaction) {
          // Core uses this one-time value, not an IdP authorization code.
          url.searchParams.delete("sso_transaction");
          window.history.replaceState(null, "", url.pathname + url.search + url.hash);
          await post("/auth/sso/exchange", { transaction_id: transaction });
          window.location.replace("/"); // Adapt to the app's protected landing route.
          return;
        }
        const response = await fetch("/auth/config", {
          cache: "no-store", credentials: "same-origin", redirect: "error",
        });
        if (!response.ok) throw new AuthError();
        setConfig(await response.json());
      } catch {
        setMessage("Accesso non disponibile. Ricarica la pagina per riprovare.");
      } finally {
        setBusy(false);
      }
    }
    void initialize();
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy(true);
    setMessage("");
    try {
      await post("/auth/login", {
        username: values.get("username"),
        password: values.get("password"),
        ...(needsTotp ? { totp: values.get("totp") } : {}),
      });
      form.reset();
      window.location.replace("/");
    } catch (error) {
      if (error instanceof AuthError && error.challenge === "totp_required") {
        setNeedsTotp(true);
        setMessage("Inserisci il codice monouso per completare l'accesso.");
      } else if (error instanceof AuthError && error.challenge === "password_update_required") {
        setNeedsTotp(false);
        setMessage("Devi aggiornare la password temporanea. Gestisci l'accesso nella console.");
      } else {
        setNeedsTotp(false); // A generic 401 must not initiate MFA.
        setMessage(error instanceof AuthError ? error.message : "Servizio non disponibile.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function sso(alias: string) {
    setBusy(true);
    setMessage("");
    try {
      const response = await post("/auth/sso/start", { alias });
      const data = await response.json();
      window.location.assign(data.authorization_url);
    } catch {
      setMessage("Accesso SSO non disponibile. Riprova o continua nella console.");
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Accedi</h1>
      <p role="status" aria-live="polite">{message || (busy ? "Attendi…" : "")}</p>
      {config?.credential_login_enabled && (
        <form onSubmit={login}>
          <fieldset disabled={busy}>
            <label>Nome utente <input name="username" autoComplete="username" required /></label>
            <label>Password <input name="password" type="password" autoComplete="current-password" required /></label>
            {needsTotp && (
              <label>Codice monouso <input name="totp" autoComplete="one-time-code" inputMode="numeric" required minLength={4} maxLength={12} /></label>
            )}
            <button type="submit">Accedi</button>
          </fieldset>
        </form>
      )}
      {config?.sso_connectors.map((connector) => (
        <button key={connector.alias} disabled={busy || !config.sso_supported}
          onClick={() => void sso(connector.alias)}>
          Accedi con {connector.display_name}
        </button>
      ))}
      {config && config.sso_connectors.length > 0 && !config.sso_supported && (
        <p>Questo ambiente offre SSO nella console; il ritorno a questa app non è disponibile.</p>
      )}
      {config?.recovery && (
        <p><a href={config.recovery.url}>Gestisci l'accesso nella console del tenant</a></p>
      )}
    </main>
  );
}
