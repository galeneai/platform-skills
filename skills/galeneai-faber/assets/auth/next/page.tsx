"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

type AuthConfig = {
  credential_login_enabled: boolean;
  password_reset_enabled: boolean;
  password_reset_completion_modes: ("keycloak" | "application")[];
  sso_connectors: { alias: string; display_name: string }[];
  recovery: { mode: "console"; url: string } | null;
};

class AuthError extends Error {
  constructor(
    public status?: number,
    public challenge?: string,
    public passwordUpdated = false,
  ) {
    super("Accesso non riuscito. Riprova.");
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
    const passwordUpdated = data.detail?.password_updated === true;
    throw new AuthError(
      response.status,
      response.status === 401 || passwordUpdated ? data.detail?.challenge : undefined,
      passwordUpdated,
    );
  }
  return response;
}

export default function LoginPage() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(true);
  const [loginStep, setLoginStep] = useState<"credentials" | "totp" | "first-sign-in">("credentials");
  const [firstSignInNeedsTotp, setFirstSignInNeedsTotp] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [recoverySent, setRecoverySent] = useState(false);
  const [resetToken, setResetToken] = useState<string | null>(null);
  const callbackHandled = useRef(false);

  useEffect(() => {
    if (callbackHandled.current) return;
    callbackHandled.current = true;
    async function initialize() {
      try {
        const url = new URL(window.location.href);
        const fragment = new URLSearchParams(url.hash.slice(1));
        const passwordResetToken = fragment.get("password_reset_token");
        if (passwordResetToken) {
          // Remove the secret before any request, render or navigation can retain it.
          url.hash = "";
          window.history.replaceState(null, "", url.pathname + url.search);
          setResetToken(passwordResetToken);
        }
        const transaction = url.searchParams.get("sso_transaction");
        if (transaction && !passwordResetToken) {
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
    const submittedUsername = String(values.get("username") || username);
    const submittedPassword = String(values.get("password") || password);
    setBusy(true);
    setMessage("");
    try {
      await post("/auth/login", {
        username: submittedUsername,
        password: submittedPassword,
        ...(loginStep === "totp" ? { totp: values.get("totp") } : {}),
      });
      form.reset();
      window.location.replace("/");
    } catch (error) {
      if (error instanceof AuthError && error.challenge === "totp_required") {
        setUsername(submittedUsername);
        setPassword(submittedPassword);
        setLoginStep("totp");
        setMessage("Inserisci il codice monouso per completare l'accesso.");
      } else if (error instanceof AuthError && error.challenge === "password_update_required") {
        setUsername(submittedUsername);
        setPassword(submittedPassword);
        setLoginStep("first-sign-in");
        setFirstSignInNeedsTotp(false);
        setMessage("Scegli una nuova password per completare il primo accesso.");
      } else {
        setLoginStep("credentials"); // A generic 401 must not initiate a challenge.
        setUsername("");
        setPassword("");
        setMessage(error instanceof AuthError ? error.message : "Servizio non disponibile.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function completeFirstSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const newPassword = String(values.get("new_password") || "");
    const confirmation = String(values.get("confirm_new_password") || "");
    if (newPassword !== confirmation) {
      setMessage("Le nuove password non coincidono.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await post("/auth/temporary-password", {
        username,
        temporary_password: password,
        new_password: newPassword,
        confirm_new_password: confirmation,
        ...(firstSignInNeedsTotp ? { totp: values.get("totp") } : {}),
      });
      setUsername("");
      setPassword("");
      window.location.replace("/");
    } catch (error) {
      if (error instanceof AuthError && error.passwordUpdated) {
        // The Core challenge was consumed and the temporary password was replaced.
        setPassword(newPassword);
        setFirstSignInNeedsTotp(false);
        if (error.challenge === "totp_required") {
          setLoginStep("totp");
          setMessage("Password aggiornata. Inserisci un nuovo codice monouso per accedere.");
        } else {
          setLoginStep("credentials");
          setMessage("Password aggiornata. Accedi con la nuova password.");
        }
      } else if (error instanceof AuthError && error.challenge === "totp_required") {
        setFirstSignInNeedsTotp(true);
        setMessage("Inserisci il codice monouso per cambiare la password.");
      } else {
        setMessage(
          error instanceof AuthError && error.status === 422
            ? "La nuova password non rispetta i requisiti. Scegline un'altra."
            : "Aggiornamento non completato. Se la password è stata accettata, torna all'accesso e usala per entrare.",
        );
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

  async function requestRecovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setMessage("");
    try {
      await post("/auth/password-reset", { identifier: values.get("identifier") });
      setRecoverySent(true);
      setMessage("Se idoneo, riceverai a breve le istruzioni di recupero.");
    } catch {
      setMessage("Recupero password non disponibile. Riprova più tardi.");
    } finally {
      setBusy(false);
    }
  }

  async function completeRecovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resetToken) return;
    const values = new FormData(event.currentTarget);
    const newPassword = String(values.get("new_password") || "");
    const confirmation = String(values.get("confirm_new_password") || "");
    if (newPassword !== confirmation) {
      setMessage("Le nuove password non coincidono.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await post("/auth/password-reset/complete", {
        reset_token: resetToken,
        new_password: newPassword,
        confirm_new_password: confirmation,
      });
      setResetToken(null);
      setMessage("Password aggiornata. Ora puoi accedere.");
    } catch (error) {
      if (error instanceof AuthError && error.status === 401) {
        setResetToken(null);
        setMessage("Il link non è valido, è scaduto o è già stato usato. Richiedine uno nuovo.");
      } else if (error instanceof AuthError && error.status === 422) {
        setMessage("La nuova password non è stata accettata. Verifica i requisiti e riprova; se il link non è valido per questa app, richiedine uno nuovo.");
      } else if (error instanceof AuthError && error.status === 429) {
        setMessage("Troppi tentativi. Attendi prima di riprovare.");
      } else {
        setMessage("Recupero temporaneamente non disponibile. Riprova più tardi.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Accedi</h1>
      <p role="status" aria-live="polite">{message || (busy ? "Attendi…" : "")}</p>
      {resetToken ? (
        <form onSubmit={completeRecovery}>
          <fieldset disabled={busy}>
            <label>Nuova password <input name="new_password" type="password" autoComplete="new-password" required /></label>
            <label>Conferma nuova password <input name="confirm_new_password" type="password" autoComplete="new-password" required /></label>
            <button type="submit">Aggiorna password</button>
          </fieldset>
          <button type="button" onClick={() => { setResetToken(null); setRecovery(true); setMessage(""); }}>
            Richiedi un nuovo link
          </button>
        </form>
      ) : recovery ? (
        <form onSubmit={requestRecovery}>
          {!recoverySent && <fieldset disabled={busy}>
            <label>Email o nome utente <input name="identifier" autoComplete="username" required /></label>
            <button type="submit">Invia le istruzioni di recupero</button>
          </fieldset>}
          <button type="button" onClick={() => { setRecovery(false); setRecoverySent(false); setMessage(""); }}>
            Torna all'accesso
          </button>
        </form>
      ) : config?.credential_login_enabled && loginStep === "first-sign-in" ? (
        <form onSubmit={completeFirstSignIn}>
          <fieldset disabled={busy}>
            <label>Nuova password <input name="new_password" type="password" autoComplete="new-password" required /></label>
            <label>Conferma nuova password <input name="confirm_new_password" type="password" autoComplete="new-password" required /></label>
            {firstSignInNeedsTotp && (
              <label>Codice monouso <input name="totp" autoComplete="one-time-code" inputMode="numeric" required minLength={4} maxLength={12} /></label>
            )}
            <button type="submit">Cambia password e accedi</button>
          </fieldset>
          <button type="button" onClick={() => { setLoginStep("credentials"); setUsername(""); setPassword(""); setMessage(""); }}>
            Torna all'accesso
          </button>
        </form>
      ) : config?.credential_login_enabled && (
        <form onSubmit={login}>
          <fieldset disabled={busy}>
            <label>Nome utente <input name="username" autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /></label>
            <label>Password <input name="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
            {loginStep === "totp" && (
              <label>Codice monouso <input name="totp" autoComplete="one-time-code" inputMode="numeric" required minLength={4} maxLength={12} /></label>
            )}
            <button type="submit">Accedi</button>
          </fieldset>
        </form>
      )}
      {!resetToken && !recovery && loginStep === "credentials" && config?.sso_connectors.map((connector) => (
        <button key={connector.alias} disabled={busy}
          onClick={() => void sso(connector.alias)}>
          Accedi con {connector.display_name}
        </button>
      ))}
      {!resetToken && !recovery && loginStep === "credentials" && config?.password_reset_enabled && (
        <button type="button" disabled={busy} onClick={() => { setRecovery(true); setMessage(""); }}>
          Password dimenticata?
        </button>
      )}
      {!resetToken && !recovery && loginStep === "credentials" && config?.recovery && (
        <p><a href={config.recovery.url}>Gestisci l'accesso nella console del tenant</a></p>
      )}
    </main>
  );
}
