# Platform log format

Galene services write one JSON object per line to their container's stdout/stderr. An app component runs next to them in the tenant, so emit the same format by default: operators then read app and platform logs with the same tools and fields. This is guidance for the app's own code and images; there is no Galene logging package to import.

## Schema

```json
{"timestamp":"2026-10-03T12:49:12.948Z","level":"INFO","target":"team-notes.api","message":"note_saved","request_id":"9f1c2e0a","correlation_id":"0b6f3c1e-5d2a-4c8e-9a71-2f4e6d8b1c3a","duration_ms":42}
```

| Field | Required | Meaning |
|---|---|---|
| `timestamp` | yes | RFC 3339 in UTC with a `Z` suffix and at least millisecond precision. |
| `level` | yes | Upper case: `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, plus the runtime's top level (`CRITICAL` in Python, `FATAL` in pino). Never `WARNING`. |
| `target` | yes | Where the line comes from: the logger or module name, or the component name for console and proxy output. |
| `message` | yes | Human-readable message without ANSI escape codes. A stable event name such as `note_saved` is easier to search than a sentence. |
| `filename`, `line_number` | when known | Source location. |
| `exception`, `stack` | when present | Formatted traceback or stack as one string. |
| anything else | optional | Structured context at the top level (`request_id`, `tenant_id`, `session_id`, `job_id`, `duration_ms`, ...). Context never overrides the fields above. |

| Variable | Default | Effect |
|---|---|---|
| `LOG_FORMAT` | `json` | `json` writes the schema. `text` may write a readable line for local development (`2026-10-03T12:49:12.948Z [INFO] target - message key=value`), still in UTC. |
| `LOG_LEVEL` | `INFO` | Minimum level where the runtime supports it. Accept `WARN` as well as the runtime's own spelling. |
| `LOG_TARGET` | component name | `target` for console, framework, and proxy output that has no logger name. |

Bake `LOG_FORMAT=json` and `LOG_TARGET` into each image so a release logs correctly without tenant configuration. If operators need to change verbosity, declare `LOG_LEVEL` in the component `env_schema` as a non-sensitive optional value with a default.

## Rules

- Write to stdout (errors may go to stderr) as one line per event. Do not write log files, rotate logs, or ship them to a separate collector from the app; the Compose and Kubernetes runtimes collect container output.
- Route framework, server, and access logs through the same format; one plain-text banner or access line breaks line-by-line parsing.
- Never log passwords, TOTP values, bearer or refresh tokens, cookies, API keys, presigned URLs, request or response bodies, prompts, model output, or document content. Log ids, counts, sizes, statuses, and durations instead. Redact authorization and cookie headers in request loggers, and log a path without its query string.
- Put context in fields, not in the message text: `request_id`, `tenant_id`, `session_id`, `job_id`, `trace_id`, `correlation_id`, `status`, `duration_ms`. Use the authenticated tenant context for `tenant_id`, never a value from app input. Do not log user names or email addresses unless the approved blueprint requires them; prefer the user id.
- Give each incoming request a `request_id` and add it to every line for that request. When the BFF calls Core, send a UUID `X-Galene-Correlation-Id`; Core returns `X-Galene-Correlation-Id` on its responses and uses it in its audit ledger. Inference endpoints also accept a UUID `X-Galene-Trace-Id` and return the trace id they used. Log both returned values as `correlation_id` and `trace_id` so an operator can follow one user action from the app into Core. Include them, not the response body, in a sanitized diagnosis.
- Use levels consistently: `INFO` for lifecycle events and completed user actions, `WARN` for recoverable problems, `ERROR` for failures needing attention, and `DEBUG` for detail that is off by default. Log health-probe requests at `DEBUG` or skip them.

## Python

A stdlib formatter is enough; structured fields come from `extra=`.

```python
import json, logging, os, sys
from datetime import datetime, timezone

_RECORD_KEYS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}

class GaleneJsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": "WARN" if record.levelno == logging.WARNING else record.levelname,
            "target": record.name,
            "message": record.getMessage(),
            "filename": record.filename,
            "line_number": record.lineno,
        }
        for key, value in vars(record).items():
            if key not in _RECORD_KEYS and not key.startswith("_"):
                entry.setdefault(key, value)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False, separators=(",", ":"))

def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(GaleneJsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root.setLevel({"WARN": "WARNING", "TRACE": "DEBUG"}.get(level, level))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
```

Call `configure_logging()` once at process start, before other loggers emit, and remove `logging.basicConfig()` calls. Uvicorn installs its own text handlers: the loop above routes them through the root handler when the app is started with the `uvicorn` CLI, and a programmatic `uvicorn.run(app, ..., log_config=None)` must pass `log_config=None` so Uvicorn does not install them again. Uvicorn's access line includes the query string: keep secrets out of URLs, or disable it (`--no-access-log`) and log requests in middleware. Then log with `logger.info("note_saved", extra={"request_id": rid, "duration_ms": ms})`.

## Node with pino

Set the options so pino emits the schema keys:

```js
import pino from "pino";

export const logger = pino({
  level: (process.env.LOG_LEVEL ?? "info").toLowerCase(),
  base: { target: process.env.LOG_TARGET ?? "api" },
  messageKey: "message",
  errorKey: "exception",
  timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
  formatters: { level: (label) => ({ level: label.toUpperCase() }) },
  serializers: { exception: (err) => err?.stack ?? String(err) },
  redact: ["req.headers.authorization", "req.headers.cookie", 'res.headers["set-cookie"]'],
});
```

Log with `logger.info({ request_id, duration_ms }, "note_saved")` and errors with `logger.error(err, "export_failed")`, which writes the stack as `exception`. For request logging (`pino-http`), pass this logger. Use `pino-pretty` only locally with `LOG_FORMAT=text`, never as a transport in the image.

## Node console preload

When an app or framework logs through `console`, rewrite `console` before anything else loads. Keep this file in the app source:

```js
// logging-preload.mjs: NODE_OPTIONS=--import=/app/logging-preload.mjs
import { format } from "node:util";

const target = process.env.LOG_TARGET || "node";
const text = (process.env.LOG_FORMAT ?? "json").toLowerCase() === "text";
const ansi = /\u001b\[[0-9;]*[A-Za-z]/g;
const levels = { trace: "DEBUG", debug: "DEBUG", log: "INFO", info: "INFO", warn: "WARN", error: "ERROR" };
const rank = { DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3 };
const min = rank[(process.env.LOG_LEVEL ?? "INFO").toUpperCase()] ?? 1;

for (const [method, level] of Object.entries(levels)) {
  const stream = rank[level] >= 2 ? process.stderr : process.stdout;
  console[method] = (...args) => {
    if (rank[level] < min) return;
    const errors = args.filter((arg) => arg instanceof Error);
    const message = format(...args.map((arg) => (arg instanceof Error ? `${arg.name}: ${arg.message}` : arg))).replace(ansi, "");
    const entry = { timestamp: new Date().toISOString(), level, target, message };
    if (errors.length) entry.exception = errors.map((error) => error.stack ?? String(error)).join("\n");
    const line = text ? `${entry.timestamp} [${level}] ${target} - ${message}${entry.exception ? `\n${entry.exception}` : ""}` : JSON.stringify(entry);
    stream.write(`${line}\n`);
  };
}
```

`--import` needs Node 18.18, 20.6, or later. Child Node processes inherit `NODE_OPTIONS`, so workers and npm scripts follow the format too.

## Next.js

Next.js prints its startup banner (`▲ Next.js ...`, `- Local: ...`, `✓ Ready in ...`) and server errors through `console`, so the preload above covers them; without it the banner breaks the format. With `output: "standalone"`:

```dockerfile
COPY logging-preload.mjs /app/logging-preload.mjs
ENV NODE_OPTIONS="--import=/app/logging-preload.mjs" LOG_FORMAT=json LOG_TARGET=web
CMD ["node", "server.js"]
```

The preload applies to the Node server only. Edge-runtime code and browser `console` output do not reach container logs; keep server-side diagnostics in Node route handlers or the BFF.

## nginx

nginx access logs can follow the schema; the error log stays plain text. Run the container in UTC (the default for official images).

```nginx
map $time_iso8601 $galene_time { "~^(?<t>.{19})" $t; }
map $msec $galene_ms { "~\.(?<ms>\d{3})" $ms; }
map $status $galene_level { ~^5 ERROR; ~^4 WARN; default INFO; }

log_format galene escape=json
  '{"timestamp":"$galene_time.${galene_ms}Z","level":"$galene_level","target":"web",'
  '"message":"$request_method $uri $status","status":$status,"request_time":$request_time,'
  '"request_id":"$request_id","correlation_id":"$http_x_galene_correlation_id"}';

access_log /dev/stdout galene;
error_log /dev/stderr warn;
```

`$uri` excludes the query string, and `request_time` is in seconds. With the official image, set `NGINX_ENTRYPOINT_QUIET_LOGS=1` to silence its plain-text entrypoint lines. Forward `proxy_set_header X-Request-Id $request_id;` to the app so both components log the same `request_id`. Use `access_log off;` in the health-probe location.

## Other runtimes

Emit the schema with the runtime's JSON logger: rename its time, level, and message keys; format the time as UTC RFC 3339 with milliseconds; map level names to the list above; add `target`; keep context fields at the top level. If a component cannot be configured exactly (a database or a third-party server), use its JSON output as close to the schema as it allows. For example, Go `log/slog`:

```go
handler := slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
	ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
		switch {
		case len(groups) > 0:
		case a.Key == slog.TimeKey:
			return slog.String("timestamp", a.Value.Time().UTC().Format("2006-01-02T15:04:05.000Z07:00"))
		case a.Key == slog.MessageKey:
			a.Key = "message"
		}
		return a
	},
})
slog.SetDefault(slog.New(handler).With("target", "worker"))
```

## Verify

Start each component image with its release configuration and check that every line it prints, including the startup banner, the first request, and a handled error, parses as JSON with the four required fields: for example `docker logs <container> 2>&1 | jq -c '{timestamp, level, target, message}'`. Confirm that a request to the BFF produces lines with the same `request_id`, and that no token, cookie, or document text appears.
