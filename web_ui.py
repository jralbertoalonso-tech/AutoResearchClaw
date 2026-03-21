"""ResearchClaw Web UI — Laboratorio de IA para Investigación Autónoma.

Funcionalidades:
  - Selector de modelo Ollama (detectado en tiempo de arranque)
  - 10 protocolos metodológicos (.md desde protocols/)
  - Subida múltiple de archivos (CSV/XLSX → datos, PDF/DOCX → contexto)
  - Prompt compuesto: [Guardarraíles] + [Protocolo] + [Idea] + [Archivos]
  - Logs en tiempo real del pipeline de 23 etapas
  - Panel de Recomendaciones Clave extraído del paper final
  - Generación automática de presentación .pptx con python-pptx
  - Descarga de PDF y PPTX generados
  - Botón "Abrir en Finder" (macOS)
  - Motor de recomendación proactiva de modelos
  - 🛡️ Modo Guardarraíles Médicos (Verificación Estricta)
  - 🏛️ Modo Auditoría CEIm (análisis offline de protocolos de ética, sin búsqueda externa)

Fuentes de búsqueda: PubMed · OpenAlex · ClinicalTrials.gov · Semantic Scholar · arXiv
"""

from __future__ import annotations

import email as _email_lib
import email.mime.application
import email.mime.multipart
import email.mime.text
import os
import re
import shutil
import smtplib
import subprocess
import tempfile
import webbrowser
from pathlib import Path

import gradio as gr

# Cargar variables del archivo .env antes de cualquier llamada a APIs.
# override=True para que el .env sobreescriba exports vacíos del shell
# (p. ej. si el usuario tiene SCITE_API_KEY="" en su perfil de shell).
try:
    from researchclaw.utils.env_bootstrap import bootstrap_env as _bootstrap_env
    _bootstrap_env(override=True)
except Exception:  # noqa: BLE001  # fallback si el paquete no está instalado aún
    try:
        from dotenv import load_dotenv  # type: ignore[import]
        load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------------------------

PROJECT_DIR     = Path(__file__).resolve().parent
ARTIFACTS_DIR   = PROJECT_DIR / "artifacts"
DATA_INPUTS_DIR = PROJECT_DIR / "data_inputs"
PROTOCOLS_DIR   = PROJECT_DIR / "protocols"
CONFIG_YAML     = PROJECT_DIR / "config.yaml"
RESEARCHCLAW_CMD = PROJECT_DIR / ".venv" / "bin" / "researchclaw"

from researchclaw.protocol_registry import (
    REGISTRY as _PROTOCOL_REGISTRY,
    ProtocolFamily as _PFamily,
    get_by_filename as _get_proto_by_filename,
)

# Legacy constants — kept for backward compat in run_pipeline() where the
# pipeline still receives raw filenames.  New UI helpers use the registry.
_PPTX_PROTOCOL    = "Presentacion_PowerPoint.md"
_CEIM_PROTOCOL    = "Auditoria_Protocolo_CEIm.md"
_POSTER_PROTOCOL  = "Poster_Congreso.md"

# ---------------------------------------------------------------------------
# Instrucciones especiales de sistema
# ---------------------------------------------------------------------------

_CONFIDENTIALITY_PROMPT = """\
[INSTRUCCIÓN DE SISTEMA — CONFIDENCIALIDAD ESTRICTA]

Los documentos subidos por el usuario son estrictamente confidenciales.
Queda expresamente prohibido: compartirlos, citarlos fuera de este análisis,
almacenarlos en sistemas externos o utilizarlos para entrenamiento de modelos.
Tratar con la máxima discreción toda la información contenida en los archivos.

"""

_CEIM_OFFLINE_PROMPT = """\
[MODO AUDITORÍA CEIm ACTIVO — ANÁLISIS EXCLUSIVAMENTE OFFLINE]

INSTRUCCIÓN CRÍTICA: NO realices búsquedas bibliográficas externas. NO consultes
PubMed, OpenAlex, ClinicalTrials.gov ni ninguna otra fuente externa.

Tu tarea es ÚNICAMENTE auditar los documentos subidos por el usuario comparándolos
con los estándares CEIm (RD 1090/2015, EU CTR 536/2014, Declaración de Helsinki,
ICH E6 GCP, RGPD/LOPDGDD), usando como referencia interna las estructuras del
Protocolo EOm, la Plantilla IA y los Modelos HIP-CI.

Si no se han subido documentos, indica explícitamente: "No se han detectado documentos
adjuntos. Por favor, sube el protocolo, la HIP y/o el CI en formato PDF o Word."

"""

# ---------------------------------------------------------------------------
# Guardarraíles anti-alucinación
# ---------------------------------------------------------------------------

_GUARDRAILS_PROMPT = """\
[MODO GUARDARRAÍLES MÉDICOS ACTIVO — VERIFICACIÓN ESTRICTA]

REGLA DE ORO: Solo puedes afirmar datos que estén presentes en los artículos \
recuperados por el pipeline de búsqueda bibliográfica. Queda prohibido inventar \
cifras, porcentajes, HR, OR, valores p o nombres de estudios.

CADENA DE VERIFICACIÓN (Chain of Verification):
Para cada dato numérico o afirmación factual debes:
  1. Escribir PRIMERO la cita bibliográfica completa: (Autor et al., Año, Revista).
  2. DESPUÉS escribir el hallazgo que respalda esa cita.
  NUNCA al revés.

Si no encuentras soporte bibliográfico para un dato específico, márcalo \
explícitamente como: [DATO NO VERIFICADO EN FUENTES]

Esta regla se aplica a TODOS los documentos generados, incluyendo resúmenes, \
presentaciones y materiales para pacientes.

"""

# ---------------------------------------------------------------------------
# Helpers de Ollama
# ---------------------------------------------------------------------------

_OLLAMA_API_URL  = "http://localhost:11434/api/tags"
_OLLAMA_FALLBACK = ["gemma2:latest", "qwen2.5-coder:14b", "qwen2.5-coder:7b"]


def _ollama_models() -> list[str]:
    """Obtiene la lista de modelos instalados en Ollama.

    Estrategia (en orden):
      1. requests  → GET http://localhost:11434/api/tags  (limpio, sin warnings)
      2. urllib    → misma URL con stdlib  (sin dependencias extra)
      3. CLI       → subprocess "ollama list"
      4. Fallback  → lista fija con gemma2:latest, qwen2.5-coder 7b/14b
    """
    # ── Intento 1: requests ──────────────────────────────────────────────
    try:
        import warnings as _w
        import requests as _req
        with _w.catch_warnings():
            _w.simplefilter("ignore")        # silenciar RequestsDependencyWarning
            _resp = _req.get(_OLLAMA_API_URL, timeout=5)
        _resp.raise_for_status()
        _data = _resp.json()
        _names = [
            str(m["name"]).strip()
            for m in _data.get("models", [])
            if isinstance(m, dict) and m.get("name")
        ]
        if _names:
            print(f"[Ollama/requests] {len(_names)} modelo(s) detectado(s)")
            return sorted(_names)
    except Exception as _e:
        print(f"[Ollama/requests] no disponible: {_e}")

    # ── Intento 2: urllib (stdlib, sin dependencias) ─────────────────────
    try:
        import urllib.request as _ur
        import json as _json
        with _ur.urlopen(_OLLAMA_API_URL, timeout=5) as _r:
            _data = _json.loads(_r.read().decode("utf-8"))
        _names = [
            str(m["name"]).strip()
            for m in _data.get("models", [])
            if isinstance(m, dict) and m.get("name")
        ]
        if _names:
            print(f"[Ollama/urllib] {len(_names)} modelo(s) detectado(s)")
            return sorted(_names)
    except Exception as _e:
        print(f"[Ollama/urllib] no disponible: {_e}")

    # ── Intento 3: CLI ───────────────────────────────────────────────────
    try:
        _proc = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=8,
        )
        _names = []
        for _line in _proc.stdout.splitlines()[1:]:   # saltar cabecera
            _parts = _line.split()
            if _parts and _parts[0].strip():
                _names.append(_parts[0].strip())
        if _names:
            print(f"[Ollama/CLI] {len(_names)} modelo(s) detectado(s)")
            return sorted(_names)
    except Exception as _e:
        print(f"[Ollama/CLI] no disponible: {_e}")

    # ── Fallback ─────────────────────────────────────────────────────────
    print(f"[Ollama] usando lista de fallback: {_OLLAMA_FALLBACK}")
    return _OLLAMA_FALLBACK[:]


def _write_temp_config(model: str) -> Path:
    """Copia config.yaml a fichero temporal con primary_model sustituido."""
    source = CONFIG_YAML.read_text(encoding="utf-8")
    patched = re.sub(
        r'(primary_model\s*:\s*)["\']?[^"\'\n]+["\']?',
        rf'\g<1>"{model}"',
        source,
    )
    patched = re.sub(
        r'(fallback_models\s*:\s*\n)((?:\s+-[^\n]+\n)*)',
        r'\1',
        patched,
    )
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False,
        dir=PROJECT_DIR, prefix=".rc_tmp_",
    )
    tmp.write(patched)
    tmp.close()
    return Path(tmp.name)


def _write_cloud_config(model: str, api_key: str) -> Path:
    """Create a temporary config.yaml wired to a cloud provider.

    Patches provider, base_url, api_key, and primary_model so that the
    pipeline subprocess uses the selected cloud model instead of Ollama.
    """
    source = CONFIG_YAML.read_text(encoding="utf-8")
    provider, base_url = _cloud_provider_cfg(model)

    # Patch provider
    patched = re.sub(
        r'(provider\s*:\s*)["\']?[^"\'\n]+["\']?',
        rf'\g<1>"{provider}"',
        source,
    )
    # Patch base_url (under llm: section only — match indented line)
    patched = re.sub(
        r'(base_url\s*:\s*)["\']?[^"\'\n]+["\']?',
        rf'\g<1>"{base_url}"',
        patched,
    )
    # Patch api_key
    patched = re.sub(
        r'(api_key\s*:\s*)["\']?[^"\'\n]+["\']?',
        rf'\g<1>"{api_key.strip()}"',
        patched,
    )
    # Patch primary_model
    patched = re.sub(
        r'(primary_model\s*:\s*)["\']?[^"\'\n]+["\']?',
        rf'\g<1>"{model}"',
        patched,
    )
    # Remove fallback_models list so it doesn't interfere
    patched = re.sub(
        r'(fallback_models\s*:\s*\n)((?:\s+-[^\n]+\n)*)',
        r'\1',
        patched,
    )

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False,
        dir=PROJECT_DIR, prefix=".rc_cloud_",
    )
    tmp.write(patched)
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Helpers de protocolos
# ---------------------------------------------------------------------------

def _protocol_choices() -> list[tuple[str, str]]:
    """Build protocol dropdown choices from the registry.

    Returns a list of (display_label, filename) tuples for Gradio Dropdown.
    Protocols in the registry get their human-readable name; any .md files
    not in the registry are included with their filename as fallback label.
    """
    # Collect registered protocols that have a file on disk
    registered: list[tuple[str, str]] = []
    registered_files: set[str] = set()
    for desc in _PROTOCOL_REGISTRY:
        if desc.filename and (PROTOCOLS_DIR / desc.filename).exists():
            # Family emoji prefix for visual grouping
            _family_icon = {
                _PFamily.RESEARCH: "🔬",
                _PFamily.CLINICAL: "🏥",
                _PFamily.DISSEMINATION: "📢",
                _PFamily.ETHICS: "🏛️",
            }
            icon = _family_icon.get(desc.family, "📋")
            label = f"{icon} {desc.name}"
            registered.append((label, desc.filename))
            registered_files.add(desc.filename)

    # Include any .md files NOT in registry (fallback for new/unknown files)
    if PROTOCOLS_DIR.is_dir():
        for p in sorted(PROTOCOLS_DIR.glob("*.md")):
            if p.name not in registered_files:
                registered.append((f"📋 {p.stem.replace('_', ' ')}", p.name))

    return registered


def _load_protocol(filename: str | None) -> str:
    if not filename:
        return ""
    path = PROTOCOLS_DIR / filename
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


# ---------------------------------------------------------------------------
# Procesamiento de ficheros adjuntos
# ---------------------------------------------------------------------------

def _extract_pdf(path: Path) -> str:
    try:
        import fitz  # type: ignore[import]
        parts: list[str] = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                parts.append(page.get_text())
        return "\n".join(parts).strip()
    except Exception as exc:
        return f"[Error extrayendo PDF {path.name}: {exc}]"


def _extract_docx(path: Path) -> str:
    try:
        import docx as _docx  # type: ignore[import]
        doc = _docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
    except Exception as exc:
        return f"[Error extrayendo DOCX {path.name}: {exc}]"


def _process_files(files: list[str] | None) -> tuple[str, str]:
    if not files:
        return "", ""
    protocol_parts: list[str] = []
    data_notes: list[str] = []
    for fpath in files:
        src = Path(fpath)
        suffix = src.suffix.lower()
        if suffix in (".xlsx", ".csv"):
            DATA_INPUTS_DIR.mkdir(parents=True, exist_ok=True)
            dest = DATA_INPUTS_DIR / src.name
            if dest.exists():
                dest = DATA_INPUTS_DIR / f"{src.stem}_{src.stat().st_ino}{src.suffix}"
            shutil.copy2(str(src), str(dest))
            data_notes.append(
                f"Nota para el agente de código: Los datos crudos para el análisis "
                f"estadístico están en la ruta absoluta: {dest}. "
                f"Escribe scripts en Python usando pandas/scipy para analizarlos "
                f"según mis instrucciones."
            )
        elif suffix == ".pdf":
            text = _extract_pdf(src)
            if text:
                protocol_parts.append(f"[Fuente: {src.name}]\n{text}")
        elif suffix in (".docx", ".doc"):
            text = _extract_docx(src)
            if text:
                protocol_parts.append(f"[Fuente: {src.name}]\n{text}")

    protocol_block = ""
    if protocol_parts:
        protocol_block = (
            "\n\n--- PROTOCOLO DE ESTUDIO DE REFERENCIA ---\n"
            + "\n\n".join(protocol_parts)
            + "\nDebe seguirse estrictamente esta metodología."
        )
    return protocol_block, " ".join(data_notes)


# ---------------------------------------------------------------------------
# Helpers de resultados
# ---------------------------------------------------------------------------

def _find_latest_run() -> Path | None:
    """Return the most-recently modified ResearchClaw run directory.

    Accepts both the legacy format (``rc-YYYYMMDD-HHMMSS-<hash>``) and the
    new semantic format (``rc-YYYYMMDD-HHMMSS_Kw1_Kw2_Kw3``).  Both share
    the ``rc-`` prefix so a single ``startswith`` check covers everything.
    """
    if not ARTIFACTS_DIR.is_dir():
        return None
    runs = sorted(
        (d for d in ARTIFACTS_DIR.iterdir()
         if d.is_dir() and d.name.startswith("rc-")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return runs[0] if runs else None


def _find_paper_md(run_dir: Path) -> Path | None:
    candidates = [
        run_dir / "deliverables" / "paper_final_verified.md",
        run_dir / "deliverables" / "paper_final.md",
        run_dir / "stage-23" / "paper_final_verified.md",
        run_dir / "stage-22" / "paper_final.md",
        run_dir / "stage-17" / "paper_draft.md",
    ]
    return next((p for p in candidates if p.exists()), None)


def _find_pdf(run_dir: Path) -> Path | None:
    candidates = [
        run_dir / "deliverables" / "paper.pdf",
        run_dir / "stage-22" / "paper.pdf",
    ]
    return next((p for p in candidates if p.exists()), None)


def _extract_summary(run_dir: Path) -> str:
    paper_path = _find_paper_md(run_dir)
    if not paper_path:
        return "_No se encontró el paper generado aún._"
    text = paper_path.read_text(encoding="utf-8", errors="replace").strip()
    section_patterns = [
        r"#{1,3}\s*(?:Executive\s+Summary|Resumen\s+Ejecutivo)[^\n]*\n(.*?)(?=\n#{1,3}\s|\Z)",
        r"#{1,3}\s*(?:Conclusions?|Conclusiones?)[^\n]*\n(.*?)(?=\n#{1,3}\s|\Z)",
        r"#{1,3}\s*(?:Recommendations?|Recomendaciones?)[^\n]*\n(.*?)(?=\n#{1,3}\s|\Z)",
        r"#{1,3}\s*(?:Key\s+Findings?|Hallazgos\s+Clave)[^\n]*\n(.*?)(?=\n#{1,3}\s|\Z)",
        r"#{1,3}\s*Abstract[^\n]*\n(.*?)(?=\n#{1,3}\s|\Z)",
    ]
    extracted: list[str] = []
    for pattern in section_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            section_text = m.group(1).strip()
            if section_text:
                extracted.append(section_text)
    if extracted:
        return "\n\n---\n\n".join(extracted)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return "\n\n".join(paragraphs[:2])


def _optimize_prompt(idea: str, model: str | None) -> str:
    """Expand a short user idea into a formal clinical research prompt.

    Calls the active Ollama model via its OpenAI-compatible /v1/chat/completions
    endpoint so no extra dependency is needed.  Falls back to the original text
    if the LLM is unreachable or returns an empty response.

    Parameters
    ----------
    idea:   Raw user text to optimise.
    model:  Selected model name from the dropdown (may be '(Predeterminado)').
    """
    if not idea.strip():
        return idea

    # Resolve effective model name
    effective_model = (
        model
        if model and model not in ("(Predeterminado)", "(Ninguno)", "")
        else (_ollama_detected[0] if _ollama_detected else "gemma2:latest")
    )

    system_prompt = (
        "Eres un asistente experto en investigación clínica y biomédica. "
        "Tu única tarea es transformar preguntas o ideas breves en preguntas "
        "de investigación clínica formales y completas. "
        "Usa el formato PICO cuando sea aplicable (Población, Intervención, "
        "Comparación, Outcome/Resultado). Añade el tipo de estudio más adecuado "
        "(ECA, revisión sistemática, cohorte, etc.), el horizonte temporal, y "
        "las variables de resultado principales y secundarias. "
        "Responde ÚNICAMENTE con el prompt mejorado, sin explicaciones adicionales, "
        "sin preámbulos y sin comillas."
    )
    user_msg = (
        f"Transforma esta idea en un prompt de investigación clínica formal:\n\n{idea.strip()}"
    )

    try:
        import json as _json
        import urllib.request as _ur

        payload = _json.dumps({
            "model": effective_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            "stream": False,
            "temperature": 0.4,
        }).encode("utf-8")

        req = _ur.Request(
            "http://localhost:11434/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=60) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        optimised = (
            data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
        )
        return optimised if optimised else idea

    except Exception as exc:  # noqa: BLE001
        print(f"[OptimizarPrompt] error llamando a Ollama: {exc}")
        return idea


def open_results_folder() -> None:
    run_dir = _find_latest_run()
    if run_dir is None:
        return
    target = run_dir / "deliverables"
    if not target.exists():
        target = run_dir
    subprocess.run(["open", str(target)], check=False)


# ---------------------------------------------------------------------------
# Notificación nativa macOS
# ---------------------------------------------------------------------------

def _notify_macos(title: str, message: str, subtitle: str = "") -> None:
    """Lanza una notificación nativa de macOS usando osascript."""
    subtitle_part = f'subtitle "{subtitle}" ' if subtitle else ""
    script = (
        f'display notification "{message}" '
        f'with title "{title}" '
        f'{subtitle_part}'
        f'sound name "Glass"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False, capture_output=True, timeout=5,
        )
    except Exception:
        pass  # Notificación es best-effort


# ---------------------------------------------------------------------------
# Envío de email con resultados (SMTP — stdlib solamente)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Modelos Cloud — proveedores y endpoints
# ---------------------------------------------------------------------------

_CLOUD_MODELS_LIST: list[str] = [
    # OpenAI
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "o3-mini",
    # Anthropic
    "claude-opus-4-5",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    # Google
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
]

_CLOUD_PROVIDER_LABELS: dict[str, str] = {
    "gpt-4o":                       "OpenAI",
    "gpt-4o-mini":                  "OpenAI",
    "gpt-4-turbo":                  "OpenAI",
    "o3-mini":                      "OpenAI",
    "claude-opus-4-5":              "Anthropic",
    "claude-3-5-sonnet-20241022":   "Anthropic",
    "claude-3-5-haiku-20241022":    "Anthropic",
    "gemini-1.5-pro":               "Google",
    "gemini-1.5-flash":             "Google",
    "gemini-2.0-flash":             "Google",
}


def _cloud_provider_cfg(model: str) -> tuple[str, str]:
    """Return (provider_key, base_url) for a cloud model name.

    These values are written into the temp config.yaml that the pipeline reads.
    - OpenAI models  → provider="openai",             base_url=https://api.openai.com/v1
    - Anthropic      → provider="anthropic",           base_url=https://api.anthropic.com
      (triggers the existing AnthropicAdapter in researchclaw/llm/anthropic_adapter.py)
    - Gemini         → provider="openai-compatible",   base_url=Google's OpenAI-compat endpoint
    """
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai", "https://api.openai.com/v1"
    if model.startswith("claude-"):
        return "anthropic", "https://api.anthropic.com"
    if model.startswith("gemini-"):
        return "openai-compatible", "https://generativelanguage.googleapis.com/v1beta/openai"
    # Unknown cloud model → assume OpenAI-compatible
    return "openai", "https://api.openai.com/v1"


_SMTP_PRESETS: dict[str, tuple[str, int]] = {
    "Gmail":   ("smtp.gmail.com", 587),
    "Outlook": ("smtp-mail.outlook.com", 587),
}

# Valores pre-cargados desde .env (cadenas vacías si no están definidos)
_ENV_EMAIL_USER    = os.environ.get("EMAIL_USER", "").strip()
_ENV_EMAIL_PASS    = os.environ.get("EMAIL_PASS", "").strip()
_ENV_EMAIL_DESTINO = os.environ.get("EMAIL_DESTINO", "").strip()


def _email_configured() -> bool:
    """True si USER y PASS de email están definidos (DESTINO se introduce en la UI)."""
    return bool(_ENV_EMAIL_USER and _ENV_EMAIL_PASS)


def _email_status_html(dest: str = "") -> str:
    """Devuelve el HTML del aviso de estado del correo para la UI."""
    if _email_configured():
        dest_display = f"<strong>{dest.strip()}</strong>" if dest.strip() else "<em>(introduce un email de destino abajo)</em>"
        return (
            "<small style='color:#16a34a'>"
            f"✅ Servidor SMTP configurado — se enviará a {dest_display} al finalizar."
            "</small>"
        )
    return (
        # Explicit color:#1f2937 (dark gray) forces legible text in both
        # Gradio light mode and dark mode, overriding any inherited foreground.
        # background + border are warm-orange to signal "action needed".
        "<div style='"
        "background:#fff7ed;"
        "border-left:3px solid #f97316;"
        "padding:8px 12px;"
        "border-radius:4px;"
        "margin:4px 0;"
        "color:#1f2937;"
        "'>"
        "<span style='color:#92400e;font-weight:700'>⚠️ Configura tu archivo .env "
        "para recibir correos automáticos.</span><br>"
        "<small style='color:#44403c'>"
        "Abre <code style='background:#fde68a;color:#1c1917;padding:1px 4px;"
        "border-radius:3px'>.env</code> en la raíz del proyecto y rellena:<br>"
        "<code style='background:#fde68a;color:#1c1917;padding:1px 4px;"
        "border-radius:3px'>EMAIL_USER=tu@gmail.com</code><br>"
        "<code style='background:#fde68a;color:#1c1917;padding:1px 4px;"
        "border-radius:3px'>EMAIL_PASS=contraseña_de_aplicación</code><br>"
        "<code style='background:#fde68a;color:#1c1917;padding:1px 4px;"
        "border-radius:3px'>EMAIL_DESTINO=destino@gmail.com</code><br>"
        "<span style='color:#44403c'>Reinicia la app tras guardar.</span>"
        "</small>"
        "</div>"
    )


def _send_email_results(
    dest_email: str,
    smtp_preset: str,
    smtp_host_custom: str,
    smtp_user: str,
    smtp_pass: str,
    attachments: list[Path],
    run_id: str = "",
) -> tuple[bool, str]:
    """Envía el correo con los archivos de resultados adjuntos.

    Devuelve (éxito, mensaje_log).
    NOTA DE SEGURIDAD:
      - Solo se adjuntan archivos de SALIDA generados por el pipeline.
      - Los documentos médicos subidos por el usuario NO se adjuntan.
      - Las credenciales nunca se escriben en logs ni en disco.
    """
    if not dest_email.strip() or not smtp_user.strip() or not smtp_pass.strip():
        return False, (
            "⚠️ Configura tu archivo .env para recibir correos automáticos. "
            "(EMAIL_USER, EMAIL_PASS y EMAIL_DESTINO deben estar rellenos)"
        )

    # Resolver host/puerto SMTP
    if smtp_preset in _SMTP_PRESETS:
        smtp_host, smtp_port = _SMTP_PRESETS[smtp_preset]
    else:
        # Formato "host:puerto" o solo host (puerto 587 por defecto)
        parts = smtp_host_custom.strip().split(":")
        smtp_host = parts[0].strip()
        smtp_port = int(parts[1]) if len(parts) > 1 else 587

    if not smtp_host:
        return False, "⚠️ Email: host SMTP no configurado — correo no enviado."

    # Construir mensaje
    msg = email.mime.multipart.MIMEMultipart()
    msg["From"]    = smtp_user.strip()
    msg["To"]      = dest_email.strip()
    msg["Subject"] = f"ResearchClaw — Investigación finalizada{' · ' + run_id if run_id else ''}"

    body = (
        "Tu investigación con ResearchClaw ha finalizado.\n\n"
        "Adjunto encontrarás los archivos generados:\n"
        + "\n".join(f"  • {p.name}" for p in attachments if p.exists())
        + "\n\n"
        "——\n"
        "AVISO DE CONFIDENCIALIDAD: Este correo y sus adjuntos pueden contener\n"
        "información médica o científica sensible. Si lo has recibido por error,\n"
        "elimínalo de inmediato sin reenviar su contenido.\n\n"
        "Generado por ResearchClaw — IA Médica Autónoma\n"
    )
    msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

    # Adjuntar solo archivos de salida que existan
    attached: list[str] = []
    for path in attachments:
        if not path.exists():
            continue
        with open(path, "rb") as f:
            part = email.mime.application.MIMEApplication(
                f.read(), Name=path.name
            )
        part["Content-Disposition"] = f'attachment; filename="{path.name}"'
        msg.attach(part)
        attached.append(path.name)

    if not attached:
        return False, "⚠️ Email: ningún archivo de resultado encontrado para adjuntar."

    # Enviar con STARTTLS
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user.strip(), smtp_pass)
            server.sendmail(smtp_user.strip(), dest_email.strip(), msg.as_string())
        return True, f"📧 Correo enviado a {dest_email} con: {', '.join(attached)}"
    except smtplib.SMTPAuthenticationError:
        return False, (
            "❌ Email: error de autenticación. Para Gmail usa una "
            "Contraseña de Aplicación (no tu contraseña habitual)."
        )
    except Exception as exc:
        return False, f"❌ Email: error al enviar — {exc}"


# ---------------------------------------------------------------------------
# Generación de PowerPoint (post-processing tras el pipeline)
# ---------------------------------------------------------------------------

def _read_bib_for_run(run_dir: Path) -> str:
    """Busca el BibTeX más reciente del pipeline para formatear referencias APA."""
    # Prefer verified → export → stage-04 bib
    for candidate in (
        run_dir / "stage-23" / "references_verified.bib",
        run_dir / "stage-22" / "references.bib",
        run_dir / "stage-04" / "references.bib",
    ):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return ""


def _build_docx(run_dir: Path, guardrails_on: bool) -> Path | None:
    """Genera el .docx del informe final en deliverables/."""
    paper_path = _find_paper_md(run_dir)
    if not paper_path:
        return None
    paper_md = paper_path.read_text(encoding="utf-8", errors="replace")
    bib_text = _read_bib_for_run(run_dir)
    output_path = run_dir / "deliverables" / "informe.docx"
    try:
        from researchclaw.docx_generator import generate_docx  # type: ignore[import]
        return generate_docx(paper_md, output_path, version="Versión 1.0", bib_text=bib_text)
    except Exception as exc:
        print(f"[docx] Error generando Word: {exc}")
        return None


def _build_pdf_from_md(run_dir: Path) -> Path | None:
    """Genera un PDF elegante desde el Markdown cuando no hay PDF de LaTeX."""
    paper_path = _find_paper_md(run_dir)
    if not paper_path:
        return None
    paper_md = paper_path.read_text(encoding="utf-8", errors="replace")
    bib_text = _read_bib_for_run(run_dir)
    output_path = run_dir / "deliverables" / "informe.pdf"
    try:
        from researchclaw.pdf_generator import generate_pdf  # type: ignore[import]
        return generate_pdf(paper_md, output_path, version="Versión 1.0", bib_text=bib_text)
    except Exception as exc:
        print(f"[pdf] Error generando PDF: {exc}")
        return None


def _build_pptx(
    run_dir: Path,
    n_slides: int,
    audience: str,
    guardrails_on: bool,
) -> Path | None:
    """Lee el paper final y genera el .pptx en deliverables/."""
    paper_path = _find_paper_md(run_dir)
    if not paper_path:
        return None
    paper_md = paper_path.read_text(encoding="utf-8", errors="replace")

    sources_note = (
        "Fuentes verificadas — ResearchClaw pipeline (PubMed · OpenAlex · ClinicalTrials.gov)"
        if guardrails_on else
        "ResearchClaw — IA Médica autónoma"
    )

    output_path = run_dir / "deliverables" / "presentacion.pptx"
    try:
        from researchclaw.pptx_generator import generate_pptx  # type: ignore[import]
        generate_pptx(
            paper_md=paper_md,
            output_path=output_path,
            n_slides=n_slides,
            audience=audience,
            sources_note=sources_note,
        )
        return output_path
    except Exception as exc:
        print(f"[pptx] Error generando presentación: {exc}")
        return None


def _build_poster(
    run_dir: Path,
    logo_hospital: str | None = None,
    logo_university: str | None = None,
    logo_congress: str | None = None,
) -> Path | None:
    """Lee el paper final y genera el póster A0 en deliverables/.

    Parameters
    ----------
    run_dir:         Directorio del run actual del pipeline.
    logo_hospital:   Ruta temporal del logo del hospital subido en la UI (puede ser None).
    logo_university: Ruta temporal del logo de la universidad.
    logo_congress:   Ruta temporal del logo del congreso.
    """
    paper_path = _find_paper_md(run_dir)
    if not paper_path:
        return None
    paper_md = paper_path.read_text(encoding="utf-8", errors="replace")
    output_path = run_dir / "deliverables" / "poster_congreso.pptx"
    logos_dir = PROJECT_DIR / "assets" / "logos"
    try:
        from researchclaw.poster_generator import generate_poster  # type: ignore[import]
        generate_poster(
            paper_md=paper_md,
            output_path=output_path,
            logos_dir=logos_dir,
            logo_hospital=logo_hospital,
            logo_university=logo_university,
            logo_congress=logo_congress,
        )
        return output_path
    except Exception as exc:
        print(f"[poster] Error generando póster: {exc}")
        return None


# ---------------------------------------------------------------------------
# CEIm tools — review and dossier generation (LLM-free, standalone)
# ---------------------------------------------------------------------------

def _extract_text_for_review(
    text_input: str,
    files: list[str] | None,
) -> str:
    """Combine free text and uploaded file contents for CEIm review."""
    parts: list[str] = []
    if text_input and text_input.strip():
        parts.append(text_input.strip())
    if files:
        for fpath in files:
            src = Path(fpath)
            suffix = src.suffix.lower()
            if suffix == ".pdf":
                extracted = _extract_pdf(src)
                if extracted and not extracted.startswith("[Error"):
                    parts.append(extracted)
            elif suffix in (".docx", ".doc"):
                extracted = _extract_docx(src)
                if extracted and not extracted.startswith("[Error"):
                    parts.append(extracted)
            elif suffix in (".md", ".txt"):
                try:
                    parts.append(src.read_text(encoding="utf-8", errors="replace").strip())
                except Exception:
                    pass
    return "\n\n".join(parts)


def _run_ceim_review(
    text_input: str,
    files: list[str] | None,
    study_type_choice: str,
) -> tuple[str, dict]:
    """Run CEIm review on provided text. Returns (markdown, file_update)."""
    protocol_text = _extract_text_for_review(text_input, files)
    if not protocol_text.strip():
        return (
            "⚠️ **No hay texto para analizar.** Pega el protocolo en el cuadro "
            "de texto o sube un archivo PDF/DOCX/MD.",
            gr.update(visible=False, value=None),
        )

    try:
        from researchclaw.ceim_reviewer import (
            StudyType,
            generate_ceim_review,
            render_ceim_review_md,
        )
    except ImportError as exc:
        return f"❌ Error importando módulo CEIm: {exc}", gr.update(visible=False, value=None)

    # Map dropdown to StudyType or None (auto-detect)
    _type_map = {
        "Auto-detectar": None,
        "Observacional": StudyType.OBSERVATIONAL,
        "Cualitativo": StudyType.QUALITATIVE,
        "Mixto": StudyType.MIXED,
    }
    force_type = _type_map.get(study_type_choice)

    try:
        review = generate_ceim_review(protocol_text, force_study_type=force_type)
        md = render_ceim_review_md(review)
    except Exception as exc:
        return (
            f"❌ Error generando la review CEIm: {exc}",
            gr.update(visible=False, value=None),
        )

    # Save to temp file for download
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
            prefix="ceim_review_", encoding="utf-8",
        )
        tmp.write(md)
        tmp.close()
        return md, gr.update(visible=True, value=tmp.name)
    except Exception:
        return md, gr.update(visible=False, value=None)


def _run_ceim_dossier(
    title: str,
    study_type_choice: str,
    pi_name: str,
    institution: str,
    primary_objective: str,
    target_population: str,
    sample_size: int,
    has_minors: bool,
    has_samples: bool,
    has_sensitive: bool,
    has_transfer: bool,
    has_ai: bool,
    has_vulnerable: bool,
    known_risks: str,
    expected_benefits: str,
) -> tuple[str, dict]:
    """Generate CEIm dossier from form inputs. Returns (preview_md, file_update)."""
    if not title.strip():
        return (
            "⚠️ **Introduce al menos el título del estudio.**",
            gr.update(visible=False, value=None),
        )

    try:
        from researchclaw.ceim_reviewer import StudyType
        from researchclaw.ceim_dossier import (
            StudyProfile,
            generate_dossier,
            write_dossier,
        )
    except ImportError as exc:
        return f"❌ Error importando módulo CEIm dossier: {exc}", gr.update(visible=False, value=None)

    _type_map = {
        "Observacional": StudyType.OBSERVATIONAL,
        "Cualitativo": StudyType.QUALITATIVE,
        "Mixto": StudyType.MIXED,
    }
    stype = _type_map.get(study_type_choice, StudyType.OBSERVATIONAL)

    # Parse comma-separated lists
    risks_list = [r.strip() for r in known_risks.split(",") if r.strip()] if known_risks.strip() else []
    benefits_list = [b.strip() for b in expected_benefits.split(",") if b.strip()] if expected_benefits.strip() else []

    try:
        profile = StudyProfile(
            title=title.strip(),
            study_type=stype,
            pi_name=pi_name.strip(),
            institution=institution.strip(),
            primary_objective=primary_objective.strip(),
            target_population=target_population.strip(),
            estimated_sample_size=max(0, sample_size or 0),
            has_minors=has_minors,
            has_biological_samples=has_samples,
            has_sensitive_data=has_sensitive,
            has_international_transfer=has_transfer,
            has_ai_component=has_ai,
            has_vulnerable=has_vulnerable,
            known_risks=risks_list,
            expected_benefits=benefits_list,
        )

        dossier = generate_dossier(profile)
    except Exception as exc:
        return f"❌ Error generando dossier: {exc}", gr.update(visible=False, value=None)

    # Build preview markdown with all documents
    preview_parts: list[str] = []
    doc_labels = {
        "protocol": "📄 Protocolo",
        "hip": "📋 Hoja de Información al Paciente",
        "ci": "✍️ Consentimiento Informado",
        "assent": "🧒 Asentimiento Menores",
        "data_protection": "🔒 Protección de Datos",
        "samples_annex": "🧪 Anexo Muestras Biológicas",
    }
    preview_parts.append(
        f"## ✅ Dossier generado — {len(dossier.documents)} documento(s)\n"
    )
    for doc_name, content in dossier.documents.items():
        label = doc_labels.get(doc_name, doc_name)
        # Show first ~40 lines of each as preview
        lines = content.split("\n")
        preview = "\n".join(lines[:40])
        if len(lines) > 40:
            preview += f"\n\n*… ({len(lines) - 40} líneas más)*"
        preview_parts.append(f"### {label}\n\n{preview}\n\n---\n")

    # Write all documents to a temp dir for download as zip
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="ceim_dossier_"))
        write_dossier(dossier, tmp_dir)

        # Optional: generate DOCX versions alongside the Markdown files.
        # Silently skipped if python-docx is not installed.
        try:
            from researchclaw.ceim_dossier import export_dossier_docx
            export_dossier_docx(dossier, tmp_dir)
        except Exception:
            pass  # DOCX export is optional; ZIP always contains .md files

        # Create zip (picks up both .md and .docx files if present)
        import zipfile
        zip_path = tmp_dir.parent / f"ceim_dossier_{title[:30].replace(' ', '_')}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(tmp_dir.iterdir()):
                if f.is_file():
                    zf.write(f, f.name)

        return "\n\n".join(preview_parts), gr.update(visible=True, value=str(zip_path))
    except Exception as exc:
        return "\n\n".join(preview_parts), gr.update(visible=False, value=None)


# ---------------------------------------------------------------------------
# Pipeline runner — genera tuplas de 8 elementos para todos los outputs
# ---------------------------------------------------------------------------

def run_pipeline(
    idea: str,
    uploaded_files: list[str] | None,
    protocol_file: str | None,
    model: str | None,
    guardrails_on: bool,
    n_slides: int,
    audience: str,
    output_formats: list[str] | None = None,
    notify_desktop: bool = False,
    notify_email: bool = False,
    dest_email: str = "",
    smtp_preset: str = "Gmail",
    smtp_host_custom: str = "",
    smtp_user: str = "",
    smtp_pass: str = "",
    cloud_model: str = "",
    cloud_api_key: str = "",
    poster_logo_hospital: str | None = None,
    poster_logo_university: str | None = None,
    poster_logo_congress: str | None = None,
):
    """Compone el prompt, parchea la config y hace streaming de los logs."""

    want_pdf    = "PDF"                   in (output_formats or ["PDF"])
    want_docx   = "Word (.docx)"          in (output_formats or [])
    want_pptx   = "PowerPoint (.pptx)"    in (output_formats or [])
    want_poster = "Póster Congreso (.pptx)" in (output_formats or [])

    btn_hidden     = gr.update(visible=False)
    pdf_hidden     = gr.update(visible=False, value=None)
    docx_hidden    = gr.update(visible=False, value=None)
    pptx_hidden    = gr.update(visible=False, value=None)
    poster_hidden  = gr.update(visible=False, value=None)
    panel_hidden   = gr.update(visible=False, value="")

    def _idle(msg: str = "", notice: str = ""):
        return msg, notice, btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden

    if not idea.strip():
        yield _idle("⚠️ Escribe una idea de investigación antes de comenzar.")
        return

    yield _idle("⏳ Procesando archivos adjuntos...\n")

    protocol_block, data_note = _process_files(uploaded_files)
    protocol_prefix = _load_protocol(protocol_file)
    is_pptx_run    = _proto_has_panel(protocol_file, "pptx_panel")
    is_ceim_run    = _is_ceim_protocol(protocol_file)
    is_poster_run  = _proto_has_panel(protocol_file, "poster_logo_panel")
    # El póster se genera automáticamente cuando se activa el protocolo de póster
    if is_poster_run:
        want_poster = True

    # Inyección de parámetros de presentación en el prompt
    if is_pptx_run:
        pptx_injection = (
            f"\n\nGenera una presentación de exactamente {n_slides} diapositivas, "
            f"adaptando el tono y el contenido para una audiencia de: {audience}."
        )
    else:
        pptx_injection = ""

    # Componer el topic
    combined = idea.strip()

    # Modo CEIm: si no hay idea, usar prompt predeterminado de auditoría
    if is_ceim_run and not combined:
        combined = (
            "Realiza una auditoría completa del protocolo de investigación adjunto "
            "siguiendo el checklist de 20 puntos CEIm y emite el dictamen correspondiente."
        )

    if pptx_injection:
        combined += pptx_injection
    if data_note:
        combined += f" {data_note}"
    if protocol_block:
        combined += protocol_block
    if protocol_prefix:
        combined = f"{protocol_prefix}\n\n---\n\n{combined}"

    # Prefijos de sistema (orden: confidencialidad → CEIm → guardarraíles)
    if is_ceim_run:
        combined = _CONFIDENTIALITY_PROMPT + _CEIM_OFFLINE_PROMPT + combined
    if guardrails_on:
        combined = _GUARDRAILS_PROMPT + combined

    # Config temporal con modelo seleccionado
    tmp_config: Path | None = None
    _using_cloud = bool(cloud_model and cloud_model != "(Ninguno)" and cloud_api_key.strip())
    effective_model = model if model and model != "(Predeterminado)" else None

    if _using_cloud:
        # Cloud model overrides local model
        try:
            tmp_config = _write_cloud_config(cloud_model, cloud_api_key)
        except Exception as exc:
            yield _idle(
                f"⚠️ No se pudo crear config para modelo cloud: {exc}\n"
                "Continuando con config.yaml original...\n"
            )
    elif effective_model:
        try:
            tmp_config = _write_temp_config(effective_model)
        except Exception as exc:
            yield _idle(
                f"⚠️ No se pudo crear config temporal: {exc}\n"
                "Continuando con config.yaml original...\n"
            )

    cmd = [str(RESEARCHCLAW_CMD), "run", "--topic", combined, "--auto-approve"]
    if protocol_file:
        cmd += ["--protocol-file", protocol_file]
    if tmp_config:
        cmd += ["--config", str(tmp_config)]

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    # Inject cloud API key into subprocess environment
    if _using_cloud:
        provider_key, _ = _cloud_provider_cfg(cloud_model)
        if provider_key == "openai":
            env["OPENAI_API_KEY"] = cloud_api_key.strip()
        elif provider_key == "anthropic":
            env["ANTHROPIC_API_KEY"] = cloud_api_key.strip()
        else:
            env["OPENAI_API_KEY"] = cloud_api_key.strip()

    log_lines: list[str] = []

    # Cabecera de inicio
    header: list[str] = ["🚀 Iniciando pipeline ResearchClaw...\n"]
    if _using_cloud:
        provider_label = _CLOUD_PROVIDER_LABELS.get(cloud_model, "Cloud")
        header.append(f"☁️ Modelo cloud: {cloud_model} ({provider_label})\n")
    elif effective_model:
        header.append(f"🧠 Modelo: {effective_model}\n")
    if protocol_file:
        header.append(f"📋 Protocolo: {protocol_file}\n")
    if guardrails_on:
        header.append("🛡️ Guardarraíles Médicos: ACTIVOS\n")
    if is_ceim_run:
        header.append("🏛️ Modo Auditoría CEIm: ACTIVO (análisis offline — sin búsqueda externa)\n")
        header.append("🔒 Confidencialidad: documentos tratados con protección estricta\n")
    if is_pptx_run:
        header.append(
            f"📊 Presentación: {n_slides} diapositivas · Audiencia: {audience}\n"
        )
    if is_poster_run:
        header.append("🖼️ Modo Póster Congreso: ACTIVO — se generará póster A0 al finalizar\n")
    if data_note:
        header.append(f"📊 Datos adjuntos guardados en: {DATA_INPUTS_DIR}\n")
    if protocol_block:
        header.append("📄 Contexto de archivos inyectado.\n")
    header.append(
        "🔎 Fuentes: PubMed · OpenAlex · ClinicalTrials.gov · Semantic Scholar · arXiv\n\n"
    )
    log_lines.extend(header)
    yield "".join(log_lines), "", btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(PROJECT_DIR), env=env, bufsize=1,
        )
    except FileNotFoundError:
        yield (
            "".join(log_lines)
            + f"❌ No se encontró el comando researchclaw.\n"
              f"   Ruta esperada: {RESEARCHCLAW_CMD}\n"
              f"   Instala con: pip install -e '.[all]'",
            "", btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden,
        )
        return

    assert proc.stdout is not None
    for line in proc.stdout:
        log_lines.append(line)
        yield "".join(log_lines), "", btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden

    proc.wait()

    if tmp_config and tmp_config.exists():
        tmp_config.unlink(missing_ok=True)

    if proc.returncode == 0:
        run_dir = _find_latest_run()
        deliverables = (run_dir / "deliverables") if run_dir else None

        generated_files: list[Path] = []  # para adjuntar al email

        # ── PDF ──────────────────────────────────────────────────────────
        pdf_path: Path | None = None
        if want_pdf and run_dir:
            pdf_path = _find_pdf(run_dir)          # PDF de LaTeX del pipeline
            if not pdf_path:
                log_lines.append("⚙️ Generando PDF desde Markdown...\n")
                yield "".join(log_lines), "", btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden
                pdf_path = _build_pdf_from_md(run_dir)
            if pdf_path:
                log_lines.append(f"✅ PDF listo: {pdf_path.name}\n")
                generated_files.append(pdf_path)
        pdf_update = (
            gr.update(visible=True, value=str(pdf_path))
            if pdf_path else gr.update(visible=False, value=None)
        )

        # ── Word (.docx) ──────────────────────────────────────────────────
        docx_path: Path | None = None
        if want_docx and run_dir:
            log_lines.append("⚙️ Generando documento Word (.docx)...\n")
            yield "".join(log_lines), "", btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden
            docx_path = _build_docx(run_dir, guardrails_on)
            if docx_path:
                log_lines.append(f"✅ Word listo: {docx_path.name}\n")
                generated_files.append(docx_path)
        docx_update = (
            gr.update(visible=True, value=str(docx_path))
            if docx_path else gr.update(visible=False, value=None)
        )

        # ── PowerPoint (.pptx) ───────────────────────────────────────────
        pptx_path: Path | None = None
        if want_pptx and run_dir:
            log_lines.append("⚙️ Generando presentación PowerPoint...\n")
            yield "".join(log_lines), "", btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden
            pptx_path = _build_pptx(run_dir, n_slides, audience, guardrails_on)
            if pptx_path:
                log_lines.append(f"✅ PowerPoint listo: {pptx_path.name}\n")
                generated_files.append(pptx_path)
        pptx_update = (
            gr.update(visible=True, value=str(pptx_path))
            if pptx_path else gr.update(visible=False, value=None)
        )

        # ── Póster Congreso A0 (.pptx) ────────────────────────────────────
        poster_path: Path | None = None
        _tmp_logos: list[str] = []  # para limpiar tras generación
        if want_poster and run_dir:
            log_lines.append("🖼️ Generando póster A0 para congreso...\n")
            if poster_logo_hospital:
                log_lines.append(f"   • Logo hospital: {Path(poster_logo_hospital).name}\n")
                _tmp_logos.append(poster_logo_hospital)
            if poster_logo_university:
                log_lines.append(f"   • Logo universidad: {Path(poster_logo_university).name}\n")
                _tmp_logos.append(poster_logo_university)
            if poster_logo_congress:
                log_lines.append(f"   • Logo congreso: {Path(poster_logo_congress).name}\n")
                _tmp_logos.append(poster_logo_congress)
            yield "".join(log_lines), "", btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden
            poster_path = _build_poster(
                run_dir,
                logo_hospital=poster_logo_hospital,
                logo_university=poster_logo_university,
                logo_congress=poster_logo_congress,
            )
            # Limpiar imágenes temporales subidas en la UI
            for _tmp in _tmp_logos:
                try:
                    Path(_tmp).unlink(missing_ok=True)
                except Exception:
                    pass
            if poster_path:
                log_lines.append(f"✅ Póster A0 listo: {poster_path.name}\n")
                generated_files.append(poster_path)
        poster_update = (
            gr.update(visible=True, value=str(poster_path))
            if poster_path else gr.update(visible=False, value=None)
        )

        notice = (
            f"## ✅ Investigación completada\n\n"
            f"Resultados en: `{deliverables or 'artifacts/'}`"
        )

        summary_text = _extract_summary(run_dir) if run_dir else ""
        guardrails_banner = (
            "\n\n> 🛡️ **Modo Guardarraíles activo** — el contenido ha sido generado "
            "con verificación estricta de fuentes.\n"
            if guardrails_on else ""
        )
        panel_content = (
            "## 💡 Recomendaciones Clave del Modelo\n\n"
            f"{guardrails_banner}"
            f"{summary_text}"
        )
        panel_update = gr.update(visible=True, value=panel_content)

        yield (
            "".join(log_lines),
            notice,
            gr.update(visible=True),  # open_btn
            pdf_update,
            docx_update,
            pptx_update,
            poster_update,
            panel_update,
        )

        # ── Post-yield: notificaciones ────────────────────────────────────

        if notify_desktop:
            _notify_macos(
                title="ResearchClaw — Investigación Finalizada",
                message="Los documentos están listos en tu carpeta.",
                subtitle=run_dir.name if run_dir else "",
            )

        if notify_email:
            # generated_files contiene solo archivos de SALIDA; nunca los subidos
            ok, email_log = _send_email_results(
                dest_email=dest_email,
                smtp_preset=smtp_preset,
                smtp_host_custom=smtp_host_custom,
                smtp_user=smtp_user,
                smtp_pass=smtp_pass,
                attachments=generated_files,
                run_id=run_dir.name if run_dir else "",
            )
            print(f"[email] {email_log}")

    else:
        notice = (
            f"## ❌ Pipeline terminado con errores (código {proc.returncode})\n\n"
            "Revisa los logs para diagnosticar el problema."
        )
        yield "".join(log_lines), notice, btn_hidden, pdf_hidden, docx_hidden, pptx_hidden, poster_hidden, panel_hidden


# ---------------------------------------------------------------------------
# Motor de recomendación proactiva de modelos
# ---------------------------------------------------------------------------

_KW_DATA = frozenset([
    "estadística", "estadisticas", "estadístico", "correlación", "correlacion",
    "regresión", "regresion", "gráfico", "grafico", "análisis", "analisis",
    "dataset", "datos", "tabla", "scipy", "pandas", "numpy", "plot",
    "clustering", "machine learning", "clasificación", "clasificacion",
    "random forest", "neural", "deep learning", "anova", "t-test",
    "chi-cuadrado", "kaplan-meier", "cox", "log-rank", "odds ratio", "r2",
])

_KW_MEDICAL = frozenset([
    "paciente", "pacientes", "clínico", "clinico", "ensayo", "trial",
    "fármaco", "farmaco", "medicamento", "dosis", "terapia", "tratamiento",
    "diagnóstico", "diagnostico", "síntoma", "sintoma", "oncología", "oncologia",
    "carcinoma", "tumor", "cáncer", "cancer", "nsclc", "sclc", "metástasis",
    "metastasis", "supervivencia", "mortalidad", "morbilidad", "placebo",
    "randomizado", "aleatorizado", "cohorte", "epidemiología", "epidemiologia",
    "farmacovigilancia", "toxicidad", "eficacia", "seguridad", "adverse",
    "pico", "rct", "meta-análisis", "metaanálisis", "revisión sistemática",
])

_KW_WRITING = frozenset([
    "resumen", "redactar", "redacción", "redaccion", "escribir", "artículo",
    "articulo", "paper", "ensayo", "revisión", "revision", "informe",
    "síntesis", "sintesis", "introducción", "introduccion", "conclusión",
    "conclusion", "abstract", "manuscrito", "imrad", "congreso", "ponencia",
    "poster", "divulgación", "divulgacion", "familias", "lenguaje sencillo",
    "case report", "reporte de caso", "care", "diapositivas", "presentación",
    "presentacion", "powerpoint", "pptx",
])

_MODEL_FRAGMENTS = {
    "qwen2.5-coder": ["qwen2.5-coder:14b", "qwen2.5-coder:7b", "qwen2.5-coder"],
    "gemma":         ["gemma2", "gemma3", "gemma:7b", "gemma:2b", "gemma"],
    "llama":         ["llama3.1", "llama3", "llama2", "llama"],
}

# Protocol families for model recommendation — derived from registry
_MEDICAL_FILENAMES: frozenset[str] = frozenset(
    d.filename for d in _PROTOCOL_REGISTRY
    if d.filename and d.family in (_PFamily.RESEARCH, _PFamily.CLINICAL)
)
_WRITING_FILENAMES: frozenset[str] = frozenset(
    d.filename for d in _PROTOCOL_REGISTRY
    if d.filename and d.family == _PFamily.DISSEMINATION
)


def _best_available(fragments: list[str], available: list[str]) -> str | None:
    av_lower = [m.lower() for m in available]
    for frag in fragments:
        for i, m in enumerate(av_lower):
            if frag.lower() in m:
                return available[i]
    return None


def _recommend_model(
    idea: str,
    uploaded_files: list[str] | None,
    protocol: str | None,
) -> str:
    idea_lower = (idea or "").lower()
    available  = _ollama_models()

    has_data_file   = bool(
        uploaded_files
        and any(Path(f).suffix.lower() in (".xlsx", ".csv") for f in uploaded_files)
    )
    has_data_kw     = any(kw in idea_lower for kw in _KW_DATA)
    has_medical_kw  = any(kw in idea_lower for kw in _KW_MEDICAL)
    has_writing_kw  = any(kw in idea_lower for kw in _KW_WRITING)
    is_medical_proto = bool(protocol and protocol in _MEDICAL_FILENAMES)
    is_writing_proto = bool(protocol and protocol in _WRITING_FILENAMES)

    if has_data_file or has_data_kw:
        target_name   = "Qwen2.5-Coder"
        target_reason = "Especializado en código y análisis estadístico de datos."
        fragments     = _MODEL_FRAGMENTS["qwen2.5-coder"]
    elif is_medical_proto or (has_medical_kw and not has_writing_kw):
        target_name   = "Gemma 2/3"
        target_reason = "Mayor rigor en lógica científica y razonamiento médico."
        fragments     = _MODEL_FRAGMENTS["gemma"]
    elif is_writing_proto or has_writing_kw:
        target_name   = "Llama 3.1"
        target_reason = "Excelente fluidez narrativa para redacción y divulgación."
        fragments     = _MODEL_FRAGMENTS["llama"]
    else:
        return (
            "<small style='color:#6b7280'>"
            "💬 Describe tu tarea para recibir una recomendación de modelo."
            "</small>"
        )

    matched = _best_available(fragments, available)
    if matched:
        return (
            f"<span style='color:#16a34a;font-weight:600'>⭐ Recomendado: {target_name}</span>"
            f"<span style='color:#374151'> — {target_reason}</span>"
        )
    pull_cmd = fragments[0]
    return (
        f"<span style='color:#d97706;font-weight:600'>⭐ Se recomienda {target_name}</span>"
        f", pero no está descargado. "
        f"<code style='background:#fef3c7;padding:1px 5px;border-radius:3px'>"
        f"ollama run {pull_cmd}</code>"
    )


# ---------------------------------------------------------------------------
# Visibilidad condicional del panel de presentación y banner CEIm
# ---------------------------------------------------------------------------

def _proto_has_panel(protocol: str | None, panel_id: str) -> bool:
    """Check if the selected protocol has a specific UI panel via registry."""
    if not protocol:
        return False
    desc = _get_proto_by_filename(protocol)
    return desc is not None and desc.has_ui_panel and desc.ui_panel_id == panel_id


def _pptx_visibility(protocol: str | None):
    """Devuelve un update para mostrar/ocultar el panel de parámetros de presentación."""
    return gr.update(visible=_proto_has_panel(protocol, "pptx_panel"))


def _poster_panel_visibility(protocol: str | None):
    """Muestra el panel de logos cuando se activa el protocolo de póster."""
    return gr.update(visible=_proto_has_panel(protocol, "poster_logo_panel"))


def _poster_format_autoselect(protocol: str | None, current_formats: list[str]) -> list[str]:
    """Auto-activa 'Póster Congreso (.pptx)' cuando se selecciona el protocolo de póster."""
    _poster_fmt = "Póster Congreso (.pptx)"
    if _proto_has_panel(protocol, "poster_logo_panel"):
        if _poster_fmt not in (current_formats or []):
            return list(current_formats or []) + [_poster_fmt]
    return current_formats or []


def _is_ceim_protocol(protocol: str | None) -> bool:
    """Check if the selected protocol is a CEIm/ethics protocol via registry."""
    if not protocol:
        return False
    desc = _get_proto_by_filename(protocol)
    return desc is not None and desc.family == _PFamily.ETHICS


def _ceim_banner(protocol: str | None) -> str:
    """Devuelve HTML de aviso cuando se activa el modo CEIm."""
    if _is_ceim_protocol(protocol):
        return (
            "<div style='background:#92400e;color:#ffffff;"
            "border-left:6px solid #fbbf24;"
            "padding:14px 18px;border-radius:8px;margin:8px 0;"
            "font-size:1em;line-height:1.6'>"
            "<strong style='font-size:1.1em'>"
            "🏛️ Modo Auditoría CEIm activo</strong><br>"
            "El sistema analizará <b>exclusivamente</b> los documentos que subas. "
            "No se realizarán búsquedas externas. "
            "<b>🔒 Confidencialidad garantizada.</b>"
            "</div>"
        )
    return ""


def _ceim_section_visibility(protocol: str | None):
    """Muestra la sección CEIm cuando se activa el protocolo CEIm."""
    return gr.update(visible=_is_ceim_protocol(protocol))


# ---------------------------------------------------------------------------
# Interfaz Gradio
# ---------------------------------------------------------------------------

_ollama_detected = _ollama_models()
print(f"✅ MODELOS OLLAMA CARGADOS: {_ollama_detected}")

_MODELS    = ["(Predeterminado)"] + _ollama_detected
_NONE_CHOICE = "(Ninguno)"
_PROTOCOLS = [(_NONE_CHOICE, _NONE_CHOICE)] + _protocol_choices()

_AUDIENCES = [
    "Comité Científico / Congresos",
    "Colegas Médicos / Sesión Clínica",
    "Pacientes y Familias",
    "Estudiantes de Medicina",
]

_CSS = """
.section-header { margin-top: 8px !important; margin-bottom: 2px !important; }
footer { display: none !important; }
.poster-logo-panel {
    background: #f0f7ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 6px 0;
}
.ceim-tools-panel {
    background: #fffbeb !important;
    border: 2px solid #f59e0b !important;
    border-radius: 10px !important;
    padding: 14px 18px;
    margin: 10px 0;
    box-shadow: 0 2px 8px rgba(245, 158, 11, 0.15);
}
"""

with gr.Blocks(title="ResearchClaw — Laboratorio de IA") as app:

    # ── Cabecera ──────────────────────────────────────────────────────────
    gr.Markdown(
        "# 🔬 ResearchClaw — Laboratorio de IA Médica\n"
        "**Fuentes:** PubMed · OpenAlex · ClinicalTrials.gov · Semantic Scholar · arXiv  "
        "| Deduplicación automática · 11 protocolos metodológicos",
    )

    # ── SECCIÓN 1: Configuración ──────────────────────────────────────────
    gr.Markdown("### ⚙️ Configuración del Laboratorio", elem_classes="section-header")

    with gr.Row(equal_height=True):
        model_dropdown = gr.Dropdown(
            label="🧠 Cerebro (Modelo Ollama)",
            choices=_MODELS,
            value=_MODELS[1] if len(_MODELS) > 1 else _MODELS[0],
            scale=3,
        )
        refresh_models_btn = gr.Button(
            "🔄",
            scale=0,
            min_width=48,
            variant="secondary",
            elem_id="refresh-models-btn",
        )
        protocol_dropdown = gr.Dropdown(
            label="📋 Protocolo Metodológico",
            choices=_PROTOCOLS,
            value=_NONE_CHOICE,
            scale=3,
        )

    rec_box = gr.HTML(
        value=(
            "<small style='color:#6b7280'>"
            "💬 Describe tu tarea para recibir una recomendación de modelo."
            "</small>"
        )
    )

    ceim_banner = gr.HTML(value="")

    format_group = gr.CheckboxGroup(
        label="📄 Formatos de salida deseados",
        choices=["PDF", "Word (.docx)", "PowerPoint (.pptx)", "Póster Congreso (.pptx)"],
        value=["PDF", "Word (.docx)", "PowerPoint (.pptx)"],
        info="Selecciona todos los formatos que quieres generar al finalizar. 'Póster Congreso' se activa automáticamente con el protocolo de póster.",
    )

    guardrails_toggle = gr.Checkbox(
        label="🛡️ Modo Guardarraíles Médicos (Verificación Estricta)",
        value=False,
        info=(
            "Cuando está activo, el sistema inyecta reglas anti-alucinación: "
            "cita antes de afirmar, marca datos no verificados como "
            "[DATO NO VERIFICADO EN FUENTES]. Más lento, triplemente seguro."
        ),
    )

    # ── ☁️ Modelos Cloud ──────────────────────────────────────────────────
    with gr.Accordion("☁️ Modelos Cloud (OpenAI · Anthropic · Google)", open=False):
        gr.Markdown(
            "> ⚠️ **Aviso de Privacidad**: Al usar modelos de la nube, los documentos "
            "analizados se enviarán a servidores externos (OpenAI, Anthropic o Google). "
            "**Para datos clínicos confidenciales, utiliza modelos locales (Ollama).**"
        )
        with gr.Row():
            cloud_model_dd = gr.Dropdown(
                label="☁️ Modelo Cloud",
                choices=["(Ninguno)"] + _CLOUD_MODELS_LIST,
                value="(Ninguno)",
                info=(
                    "gpt-4o / gpt-4o-mini / o3-mini → OpenAI  |  "
                    "claude-* → Anthropic  |  gemini-* → Google"
                ),
                scale=2,
            )
            cloud_api_key_box = gr.Textbox(
                label="🔑 API Key",
                placeholder="sk-... / sk-ant-... / AIza...",
                type="password",
                info="La clave no se almacena en disco. Se usa solo durante la ejecución.",
                scale=2,
            )
        cloud_status_html = gr.HTML(
            value="<small style='color:#6b7280'>Selecciona un modelo cloud e introduce tu API Key para activar.</small>"
        )

    # ── 📬 Notificaciones y envío automático ─────────────────────────────
    with gr.Accordion("📬 Notificaciones y Envío Automático", open=False):
        with gr.Row():
            notify_toggle = gr.Checkbox(
                label="🔔 Notificación de escritorio al finalizar",
                value=False,
                scale=1,
                info="Lanza una notificación nativa de macOS al completar el pipeline.",
            )
            email_toggle = gr.Checkbox(
                label="📧 Enviar resultados por email al finalizar",
                value=False,
                scale=1,
                info="Envía PDF y PPTX generados. Los documentos subidos NO se adjuntan.",
            )

        with gr.Group(visible=False) as email_config_panel:
            email_status_html = gr.HTML(value=_email_status_html())
            gr.Markdown(
                "> 🔒 **Privacidad**: solo se adjuntan los archivos de salida generados "
                "(PDF/PPTX). Los documentos médicos que hayas subido **nunca** se envían.  \n"
                "> 💡 **Gmail**: usa una Contraseña de Aplicación "
                "(`myaccount.google.com/apppasswords`), no tu contraseña habitual."
            )
            with gr.Row():
                smtp_preset_dd = gr.Dropdown(
                    label="🖥️ Servidor SMTP",
                    choices=["Gmail", "Outlook", "Personalizado"],
                    value="Gmail",
                    scale=1,
                )
                dest_email_box = gr.Textbox(
                    label="📨 Email de destino",
                    placeholder="destinatario@ejemplo.com",
                    value=_ENV_EMAIL_DESTINO,
                    scale=1,
                )
            with gr.Row(visible=False) as smtp_custom_row:
                smtp_host_box = gr.Textbox(
                    label="Host SMTP personalizado (host:puerto)",
                    placeholder="smtp.miservidor.com:587",
                    scale=1,
                )
            with gr.Row():
                smtp_user_box = gr.Textbox(
                    label="👤 Usuario SMTP (tu email de envío)",
                    placeholder="tu@gmail.com",
                    value=_ENV_EMAIL_USER,
                    scale=1,
                )
                smtp_pass_box = gr.Textbox(
                    label="🔑 Contraseña de aplicación",
                    placeholder="xxxx xxxx xxxx xxxx",
                    value=_ENV_EMAIL_PASS,
                    type="password",
                    scale=1,
                )

    # ── Panel de parámetros de presentación (visible solo con PowerPoint) ─
    with gr.Row(visible=False) as pptx_panel:
        slides_slider = gr.Slider(
            minimum=5, maximum=30, value=12, step=1,
            label="🖼️ Número de Diapositivas",
            scale=1,
        )
        audience_dropdown = gr.Dropdown(
            label="👥 Audiencia de la Presentación",
            choices=_AUDIENCES,
            value=_AUDIENCES[0],
            scale=1,
        )

    # ── Panel de logos para póster (visible solo con protocolo Poster_Congreso) ──
    with gr.Group(visible=False, elem_classes="poster-logo-panel") as poster_logo_panel:
        gr.Markdown(
            "#### 🖼️ Logos para el Póster A0\n"
            "Sube los logos en PNG (fondo transparente recomendado). "
            "Si no subes ninguno, el póster se generará sin logos."
        )
        with gr.Row():
            logo_hospital_img = gr.Image(
                type="filepath",
                label="🏥 Logo Hospital (PNG)",
                height=140,
                scale=1,
            )
            logo_university_img = gr.Image(
                type="filepath",
                label="🎓 Logo Universidad (PNG)",
                height=140,
                scale=1,
            )
            logo_congress_img = gr.Image(
                type="filepath",
                label="🏛️ Logo Congreso / Evento (PNG)",
                height=140,
                scale=1,
            )
        gr.Markdown(
            "<small style='color:#6b7280'>💡 Posicionamiento automático: "
            "Hospital → izquierda · Congreso → centro · Universidad → derecha. "
            "Los archivos temporales se eliminan tras generar el póster.</small>"
        )

    gr.Markdown("---")

    # ── SECCIÓN CEIm: Herramientas de ética y dossier ──────────────────
    with gr.Group(visible=False, elem_classes="ceim-tools-panel") as ceim_section:
        gr.Markdown(
            "### 🏥 Herramientas CEIm\n"
            "<small style='color:#6b7280'>"
            "Evaluación ética y generación de dossier CEIm. "
            "**No requieren LLM** — funcionan directamente con tus datos.</small>"
        )
        with gr.Tabs():

            # ── Tab 1: CEIm Review ────────────────────────────────────
            with gr.Tab("📝 CEIm Review"):
                gr.Markdown(
                    "Pega el texto del protocolo o sube un PDF/DOCX. "
                    "Se generará una evaluación estructurada con checklist "
                    "adaptado al tipo de estudio."
                )
                with gr.Row():
                    with gr.Column(scale=2):
                        ceim_review_text = gr.Textbox(
                            label="Texto del protocolo / trabajo",
                            placeholder="Pega aquí el texto completo del protocolo, HIP o artículo…",
                            lines=10,
                        )
                    with gr.Column(scale=1):
                        ceim_review_files = gr.File(
                            label="📎 O sube PDF / DOCX / MD",
                            file_count="multiple",
                            file_types=[".pdf", ".docx", ".doc", ".md", ".txt"],
                        )
                ceim_review_type = gr.Dropdown(
                    choices=["Auto-detectar", "Observacional", "Cualitativo", "Mixto"],
                    value="Auto-detectar",
                    label="Tipo de estudio",
                    info="Deja 'Auto-detectar' para clasificación automática por keywords.",
                )
                ceim_review_btn = gr.Button(
                    "🔍 Generar Review CEIm",
                    variant="primary",
                )
                ceim_review_output = gr.Markdown(
                    label="Resultado de la Review",
                )
                ceim_review_download = gr.File(
                    label="⬇️ Descargar Review (.md)",
                    visible=False,
                )

            # ── Tab 2: CEIm Dossier Generator ─────────────────────────
            with gr.Tab("📋 Dossier Generator"):
                gr.Markdown(
                    "Rellena los campos del estudio y se generará un borrador "
                    "estructurado del dossier CEIm completo (protocolo, HIP, CI, "
                    "protección de datos y anexos aplicables)."
                )
                with gr.Row():
                    with gr.Column():
                        dossier_title = gr.Textbox(
                            label="Título del estudio *",
                            placeholder="Ej: Eficacia de intervención X en pacientes con HTA",
                        )
                        dossier_study_type = gr.Dropdown(
                            choices=["Observacional", "Cualitativo", "Mixto"],
                            value="Observacional",
                            label="Tipo de estudio",
                        )
                        dossier_pi = gr.Textbox(
                            label="Investigador principal",
                            placeholder="Dra. María García",
                        )
                        dossier_institution = gr.Textbox(
                            label="Centro / Institución",
                            placeholder="Hospital Clínico Universitario",
                        )
                    with gr.Column():
                        dossier_objective = gr.Textbox(
                            label="Objetivo primario",
                            placeholder="Evaluar la eficacia de…",
                            lines=3,
                        )
                        dossier_population = gr.Textbox(
                            label="Población diana",
                            placeholder="Adultos con HTA grado I-II",
                        )
                        dossier_sample_size = gr.Number(
                            label="Tamaño muestral estimado",
                            value=0,
                            precision=0,
                        )
                gr.Markdown("**Características del estudio:**")
                with gr.Row():
                    dossier_minors = gr.Checkbox(label="Menores", value=False)
                    dossier_vulnerable = gr.Checkbox(label="Población vulnerable", value=False)
                    dossier_samples = gr.Checkbox(label="Muestras biológicas", value=False)
                    dossier_sensitive = gr.Checkbox(label="Datos sensibles", value=False)
                    dossier_transfer = gr.Checkbox(label="Transferencia internacional", value=False)
                    dossier_ai = gr.Checkbox(label="Componente IA", value=False)
                with gr.Row():
                    dossier_risks = gr.Textbox(
                        label="Riesgos conocidos (separados por coma)",
                        placeholder="Hipotensión leve, cefalea transitoria",
                        scale=1,
                    )
                    dossier_benefits = gr.Textbox(
                        label="Beneficios esperados (separados por coma)",
                        placeholder="Reducción riesgo CV, mejora calidad de vida",
                        scale=1,
                    )
                dossier_btn = gr.Button(
                    "📋 Generar Dossier CEIm",
                    variant="primary",
                )
                dossier_output = gr.Markdown(
                    label="Vista previa del Dossier",
                )
                dossier_download = gr.File(
                    label="⬇️ Descargar Dossier (.zip)",
                    visible=False,
                )

    gr.Markdown("---")

    # ── SECCIÓN 2: Tarea de investigación ─────────────────────────────────
    gr.Markdown("### 📝 Tu Investigación", elem_classes="section-header")

    with gr.Row():
        with gr.Column(scale=2):
            idea_box = gr.Textbox(
                label="Idea o pregunta de investigación",
                placeholder=(
                    "Ej: Eficacia de pembrolizumab vs quimioterapia en NSCLC estadio III — "
                    "análisis de supervivencia global y libre de progresión (KEYNOTE-189)"
                ),
                lines=6,
            )
            with gr.Row():
                optimize_btn = gr.Button(
                    "✨ Optimizar Pregunta",
                    variant="secondary",
                    scale=1,
                    min_width=200,
                    elem_id="optimize-prompt-btn",
                )
                gr.HTML(
                    "<small style='color:#6b7280;align-self:center;padding-left:8px'>"
                    "Expande tu idea a un prompt clínico formal (PICO + tipo de estudio) "
                    "usando el modelo local activo."
                    "</small>",
                )
        with gr.Column(scale=1):
            file_upload = gr.File(
                label="📎 Archivos adjuntos (opcional)",
                file_count="multiple",
                file_types=[".xlsx", ".csv", ".pdf", ".doc", ".docx"],
            )

    start_btn = gr.Button(
        "▶  Comenzar Investigación",
        variant="primary",
        size="lg",
    )

    gr.Markdown("---")

    # ── SECCIÓN 3: Monitor del pipeline ───────────────────────────────────
    gr.Markdown("### 📊 Monitor del Pipeline", elem_classes="section-header")

    logs_box = gr.Textbox(
        label="Logs en tiempo real",
        lines=20,
        max_lines=60,
        interactive=False,
    )

    result_md = gr.Markdown()

    with gr.Row():
        open_btn = gr.Button(
            "📂 Abrir Carpeta de Resultados",
            variant="secondary",
            visible=False,
            scale=1,
        )
        pdf_download = gr.File(
            label="⬇️ PDF",
            visible=False,
            scale=1,
        )
        docx_download = gr.File(
            label="⬇️ Word (.docx)",
            visible=False,
            scale=1,
        )
        pptx_download = gr.File(
            label="⬇️ PowerPoint (.pptx)",
            visible=False,
            scale=1,
        )
        poster_download = gr.File(
            label="⬇️ Póster Congreso A0 (.pptx)",
            visible=False,
            scale=1,
        )

    # ── SECCIÓN 4: Recomendaciones Clave ──────────────────────────────────
    summary_panel = gr.Markdown(visible=False)

    # ── Eventos ───────────────────────────────────────────────────────────

    def _on_start(
        idea, files, protocol, model, guardrails, n_slides, audience,
        formats, do_notify, do_email, d_email, smtp_pst, smtp_host, s_user, s_pass,
        c_model, c_api_key,
        logo_hosp, logo_univ, logo_cong,
    ):
        eff_protocol = None if protocol in (None, _NONE_CHOICE) else protocol
        eff_model    = None if model in (None, "(Predeterminado)") else model
        yield from run_pipeline(
            idea, files, eff_protocol, eff_model,
            guardrails, n_slides, audience,
            output_formats=formats or [],
            notify_desktop=do_notify,
            notify_email=do_email,
            dest_email=d_email,
            smtp_preset=smtp_pst,
            smtp_host_custom=smtp_host,
            smtp_user=s_user,
            smtp_pass=s_pass,
            cloud_model=c_model or "",
            cloud_api_key=c_api_key or "",
            poster_logo_hospital=logo_hosp,
            poster_logo_university=logo_univ,
            poster_logo_congress=logo_cong,
        )

    start_btn.click(
        fn=_on_start,
        inputs=[
            idea_box, file_upload, protocol_dropdown, model_dropdown,
            guardrails_toggle, slides_slider, audience_dropdown,
            format_group,
            notify_toggle, email_toggle,
            dest_email_box, smtp_preset_dd, smtp_host_box,
            smtp_user_box, smtp_pass_box,
            cloud_model_dd, cloud_api_key_box,
            logo_hospital_img, logo_university_img, logo_congress_img,
        ],
        outputs=[
            logs_box, result_md, open_btn,
            pdf_download, docx_download, pptx_download, poster_download,
            summary_panel,
        ],
    )

    open_btn.click(fn=open_results_folder, inputs=[], outputs=[])

    # ── CEIm Review ────────────────────────────────────────────────────────
    ceim_review_btn.click(
        fn=_run_ceim_review,
        inputs=[ceim_review_text, ceim_review_files, ceim_review_type],
        outputs=[ceim_review_output, ceim_review_download],
    )

    # ── CEIm Dossier Generator ─────────────────────────────────────────────
    dossier_btn.click(
        fn=_run_ceim_dossier,
        inputs=[
            dossier_title, dossier_study_type, dossier_pi, dossier_institution,
            dossier_objective, dossier_population, dossier_sample_size,
            dossier_minors, dossier_samples, dossier_sensitive,
            dossier_transfer, dossier_ai, dossier_vulnerable,
            dossier_risks, dossier_benefits,
        ],
        outputs=[dossier_output, dossier_download],
    )

    # ── Optimizador de Prompt ──────────────────────────────────────────────
    def _on_optimize(idea: str, model: str) -> dict:
        """Call _optimize_prompt and return the improved text to idea_box."""
        improved = _optimize_prompt(idea, model)
        return gr.update(value=improved)

    optimize_btn.click(
        fn=_on_optimize,
        inputs=[idea_box, model_dropdown],
        outputs=[idea_box],
    )

    # Refresco dinámico de modelos Ollama + reset de outputs
    def _refresh_models():
        detected = _ollama_models()
        print(f"🔄 Refresco — Modelos detectados: {detected}")
        choices = ["(Predeterminado)"] + detected
        default = choices[1] if len(choices) > 1 else choices[0]
        return (
            gr.update(choices=choices, value=default),  # model_dropdown
            "",                                          # logs_box
            "",                                          # result_md
            gr.update(visible=False),                    # open_btn
            gr.update(visible=False, value=None),        # pdf_download
            gr.update(visible=False, value=None),        # docx_download
            gr.update(visible=False, value=None),        # pptx_download
            gr.update(visible=False, value=None),        # poster_download
            gr.update(visible=False, value=""),          # summary_panel
        )

    refresh_models_btn.click(
        fn=_refresh_models,
        inputs=[],
        outputs=[
            model_dropdown, logs_box, result_md, open_btn,
            pdf_download, docx_download, pptx_download, poster_download,
            summary_panel,
        ],
    )

    # Actualizar estado del email cuando cambia el destinatario
    def _update_email_status(dest: str):
        return gr.update(value=_email_status_html(dest))

    dest_email_box.change(
        fn=_update_email_status,
        inputs=[dest_email_box],
        outputs=[email_status_html],
    )

    # Actualizar estado del modelo cloud
    def _update_cloud_status(model: str, api_key: str):
        if model and model != "(Ninguno)" and api_key.strip():
            provider = _CLOUD_PROVIDER_LABELS.get(model, "Cloud")
            return gr.update(value=(
                f"<small style='color:#16a34a'>✅ Listo — se usará <strong>{model}</strong> "
                f"({provider}). La clave se inyecta solo durante la ejecución.</small>"
            ))
        if model and model != "(Ninguno)" and not api_key.strip():
            return gr.update(value=(
                "<small style='color:#d97706'>⚠️ Introduce tu API Key para activar este modelo.</small>"
            ))
        return gr.update(value=(
            "<small style='color:#6b7280'>Selecciona un modelo cloud e introduce tu API Key para activar.</small>"
        ))

    cloud_model_dd.change(
        fn=_update_cloud_status,
        inputs=[cloud_model_dd, cloud_api_key_box],
        outputs=[cloud_status_html],
    )
    cloud_api_key_box.change(
        fn=_update_cloud_status,
        inputs=[cloud_model_dd, cloud_api_key_box],
        outputs=[cloud_status_html],
    )

    # Mostrar/ocultar panel email config
    email_toggle.change(
        fn=lambda v: gr.update(visible=v),
        inputs=[email_toggle],
        outputs=[email_config_panel],
    )
    # Mostrar/ocultar fila host personalizado
    smtp_preset_dd.change(
        fn=lambda v: gr.update(visible=(v == "Personalizado")),
        inputs=[smtp_preset_dd],
        outputs=[smtp_custom_row],
    )

    # Mostrar/ocultar panel de presentación y banner CEIm al cambiar protocolo
    protocol_dropdown.change(
        fn=_pptx_visibility,
        inputs=[protocol_dropdown],
        outputs=[pptx_panel],
    )
    protocol_dropdown.change(
        fn=_ceim_banner,
        inputs=[protocol_dropdown],
        outputs=[ceim_banner],
    )
    # Mostrar/ocultar sección CEIm tools al seleccionar protocolo CEIm
    protocol_dropdown.change(
        fn=_ceim_section_visibility,
        inputs=[protocol_dropdown],
        outputs=[ceim_section],
    )
    # Mostrar/ocultar panel de logos del póster
    protocol_dropdown.change(
        fn=_poster_panel_visibility,
        inputs=[protocol_dropdown],
        outputs=[poster_logo_panel],
    )
    # Auto-activar "Póster Congreso (.pptx)" al seleccionar el protocolo de póster
    protocol_dropdown.change(
        fn=_poster_format_autoselect,
        inputs=[protocol_dropdown, format_group],
        outputs=[format_group],
    )

    # Recomendación en tiempo real
    _rec_inputs = [idea_box, file_upload, protocol_dropdown]
    idea_box.change(fn=_recommend_model, inputs=_rec_inputs, outputs=[rec_box])
    file_upload.change(fn=_recommend_model, inputs=_rec_inputs, outputs=[rec_box])
    protocol_dropdown.change(fn=_recommend_model, inputs=_rec_inputs, outputs=[rec_box])


if __name__ == "__main__":
    webbrowser.open("http://localhost:7860")
    app.launch(server_name="0.0.0.0", server_port=7860, css=_CSS)
