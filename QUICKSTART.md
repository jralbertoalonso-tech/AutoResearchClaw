# QUICKSTART — AutoResearchClaw v1.0

Hay dos formas de usar AutoResearchClaw. Elige la que corresponde a tu caso.

---

## Modo A — Web UI (recomendado para protocolos clínicos y de investigación)

Interfaz gráfica local con Ollama. Sin claves de API externas.

### Requisitos

- Python ≥ 3.11
- [Ollama](https://ollama.com) instalado y corriendo (`ollama serve`)
- Al menos un modelo descargado, p. ej.:
  ```bash
  ollama pull gemma2:latest
  ```

### Instalación

```bash
git clone https://github.com/aiming-lab/AutoResearchClaw.git
cd AutoResearchClaw
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[export]"      # incluye exportadores PDF, DOCX y PPTX
pip install gradio               # interfaz web (requerida para web_ui.py)
```

### Arranque

**macOS — doble clic:**
```
Iniciar_Investigador.command
```

**Cualquier sistema — terminal:**
```bash
source .venv/bin/activate
python web_ui.py
```

La app abre automáticamente en `http://localhost:7860`.

### Protocolos disponibles

| Familia | Protocolos MVP |
|---------|---------------|
| Investigación | Revisión Sistemática PRISMA · Análisis Rápido de Evidencia |
| Clínico | Consulta Clínica PICO |
| Difusión | Póster · Resumen de Congreso · Presentación PowerPoint |
| Ética | Auditoría CEIm · Dossier CEIm |

---

## Modo B — CLI Pipeline (ML research paper desde cero)

Pipeline autónomo de 23 etapas para generar papers con experimentos.

### Requisitos

- Python ≥ 3.11
- Clave de API de un proveedor LLM compatible con OpenAI (GPT-4o, Claude, etc.)

### Instalación

```bash
git clone https://github.com/aiming-lab/AutoResearchClaw.git
cd AutoResearchClaw
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[export]"
```

### Configuración

```bash
cp config.researchclaw.example.yaml config.yaml
# Edita config.yaml — pon tu endpoint LLM y modelo
```

Variables de entorno opcionales — copia `.env.example` a `.env` y rellena:

```bash
cp .env.example .env
# Edita .env con tus claves
```

### Ejecución

```bash
export OPENAI_API_KEY="sk-..."        # o pon la clave en .env
researchclaw run \
  --config config.yaml \
  --topic  "Tu idea de investigación" \
  --auto-approve
```

Resultado → `artifacts/rc-YYYYMMDD-*/deliverables/`

---

## Exportadores opcionales

Los protocolos que generan PDF, DOCX y PPTX requieren el extra `[export]`:

```bash
pip install -e ".[export]"
```

Incluye: `python-docx` · `fpdf2` · `python-pptx`

---

## Verificar entorno

```bash
researchclaw doctor
```

---

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---------|---------------|---------|
| `ModuleNotFoundError: gradio` | Gradio no instalado | `pip install gradio` |
| Web UI no detecta modelos | Ollama no corre | `ollama serve` |
| `No config file found` | Falta `config.yaml` | `cp config.researchclaw.example.yaml config.yaml` |
| PDF/DOCX no se genera | Extra `[export]` no instalado | `pip install -e ".[export]"` |
