import os
import json
import requests
import threading
from flask import Flask, request
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID")
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID")
NOTION_MEMORY_ID = os.environ.get("NOTION_MEMORY_ID")
NOTION_KPIS_ID = os.environ.get("NOTION_KPIS_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })

def load_memory():
    if not NOTION_MEMORY_ID:
        return []
    try:
        url = f"https://api.notion.com/v1/blocks/{NOTION_MEMORY_ID}/children"
        response = requests.get(url, headers=NOTION_HEADERS)
        data = response.json()
        for block in data.get("results", []):
            if block.get("type") == "code":
                content = block["code"]["rich_text"]
                if content:
                    return json.loads(content[0]["plain_text"])
        return []
    except:
        return []

def save_memory(history):
    if not NOTION_MEMORY_ID:
        return
    try:
        url = f"https://api.notion.com/v1/blocks/{NOTION_MEMORY_ID}/children"
        response = requests.get(url, headers=NOTION_HEADERS)
        for block in response.json().get("results", []):
            requests.delete(f"https://api.notion.com/v1/blocks/{block['id']}", headers=NOTION_HEADERS)
        recent = history[-20:]
        requests.patch(url, headers=NOTION_HEADERS, json={
            "children": [{
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": json.dumps(recent, ensure_ascii=False)}}],
                    "language": "json"
                }
            }]
        })
    except Exception as e:
        print(f"Error guardando memoria: {e}")

def get_kpis():
    if not NOTION_KPIS_ID:
        return ""
    try:
        url = f"https://api.notion.com/v1/blocks/{NOTION_KPIS_ID}/children"
        response = requests.get(url, headers=NOTION_HEADERS)
        data = response.json()
        kpi_text = []
        for block in data.get("results", []):
            block_type = block.get("type")
            if block_type == "table":
                rows_url = f"https://api.notion.com/v1/blocks/{block['id']}/children"
                rows = requests.get(rows_url, headers=NOTION_HEADERS).json().get("results", [])
                for row in rows:
                    cells = row.get("table_row", {}).get("cells", [])
                    row_text = " | ".join([cell[0]["plain_text"] if cell else "" for cell in cells])
                    kpi_text.append(row_text)
            elif block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                rich_text = block.get(block_type, {}).get("rich_text", [])
                if rich_text:
                    kpi_text.append(rich_text[0].get("plain_text", ""))
        return "\n".join(kpi_text) if kpi_text else ""
    except:
        return ""

def get_tasks():
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    response = requests.post(url, headers=NOTION_HEADERS, json={})
    data = response.json()
    tasks = []
    for page in data.get("results", []):
        props = page.get("properties", {})
        name = ""
        title_prop = props.get("Tarea") or props.get("Name") or props.get("Nombre")
        if title_prop and title_prop.get("title"):
            name = title_prop["title"][0]["plain_text"] if title_prop["title"] else ""
        status = ""
        status_prop = props.get("Status") or props.get("Estado")
        if status_prop:
            if status_prop.get("status"):
                status = status_prop["status"].get("name", "")
            elif status_prop.get("select"):
                status = status_prop["select"].get("name", "")
        priority = ""
        priority_prop = props.get("Prioridad")
        if priority_prop and priority_prop.get("select"):
            priority = priority_prop["select"].get("name", "")
        due = ""
        due_prop = props.get("Fecha límite") or props.get("Fecha Límite") or props.get("Due")
        if due_prop and due_prop.get("date") and due_prop["date"]:
            due = due_prop["date"].get("start", "")
        if name and status != "Done":
            tasks.append({"id": page["id"], "name": name, "status": status, "priority": priority, "due": due})
    return tasks

def get_all_tasks():
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    response = requests.post(url, headers=NOTION_HEADERS, json={})
    data = response.json()
    tasks = []
    for page in data.get("results", []):
        props = page.get("properties", {})
        name = ""
        title_prop = props.get("Tarea") or props.get("Name") or props.get("Nombre")
        if title_prop and title_prop.get("title"):
            name = title_prop["title"][0]["plain_text"] if title_prop["title"] else ""
        if name:
            tasks.append({"id": page["id"], "name": name})
    return tasks

def mark_task_done(task_name):
    for task in get_all_tasks():
        if task_name.lower() in task["name"].lower():
            requests.patch(f"https://api.notion.com/v1/pages/{task['id']}", headers=NOTION_HEADERS, json={
                "properties": {"Status": {"status": {"name": "Done"}}}
            })
            return task["name"]
    return None

def create_task(name, priority="Media", due=None):
    properties = {
        "Tarea": {"title": [{"text": {"content": name}}]},
        "Prioridad": {"select": {"name": priority}},
        "Status": {"status": {"name": "Not started"}}
    }
    if due:
        properties["Fecha límite"] = {"date": {"start": due}}
    response = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json={
        "parent": {"database_id": NOTION_DB_ID},
        "properties": properties
    })
    return response.status_code == 200

def add_note_to_task(task_name, note):
    for task in get_all_tasks():
        if task_name.lower() in task["name"].lower():
            today = datetime.now().strftime("%Y-%m-%d %H:%M")
            response = requests.patch(f"https://api.notion.com/v1/blocks/{task['id']}/children", headers=NOTION_HEADERS, json={
                "children": [{
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"type": "text", "text": {"content": f"📝 {today}\n{note}"}}],
                        "icon": {"emoji": "📌"},
                        "color": "gray_background"
                    }
                }]
            })
            if response.status_code == 200:
                return task["name"]
    return None

def generate_and_send_news(chat_id):
    """Genera el boletin en un hilo separado y lo manda cuando este listo"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = f"""Hoy es {today}. Eres Jade, asistente de Vivian, Territory Product Manager de Intel NUC, Chromebox y Mini PC para Sudamerica (Colombia, Ecuador, Centroamerica, Chile, Peru, Argentina).

Genera un boletin ejecutivo breve sobre novedades tech relevantes para su negocio. Incluye tendencias de:
- Intel NUC y Mini PC
- Chromebox enterprise
- IA en dispositivos locales y edge computing
- Hardware LATAM

Formato:

🗞️ *Noticiario Tech — {today}*

1. [emoji] *[Titulo]*
[2 parrafos de descripcion con impacto LATAM]
💡 *Accion:* [recomendacion para Vivian]

2. [emoji] *[Titulo]*
[descripcion]
💡 *Accion:* [recomendacion]

3. [emoji] *[Titulo]*
[descripcion]
💡 *Accion:* [recomendacion]

---
*Resumen:* [2 lineas con lo mas importante]

Maximo 2500 caracteres. Español, tono ejecutivo."""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-5-20250929",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=120
        )
        data = response.json()
        if "content" in data:
            news = data["content"][0]["text"]
            if len(news) > 4000:
                parts = [news[i:i+4000] for i in range(0, len(news), 4000)]
                for part in parts:
                    send_message(chat_id, part)
            else:
                send_message(chat_id, news)
        else:
            send_message(chat_id, "No pude generar el boletin. Intenta de nuevo.")
    except Exception as e:
        print(f"Error generando noticias: {e}")
        send_message(chat_id, "Hubo un error generando el boletin. Intenta de nuevo.")

def ask_jade(user_message, tasks, kpis):
    history = load_memory()
    task_list = "\n".join([
        f"- {t['name']} | Estado: {t['status']} | Prioridad: {t['priority']} | Vence: {t['due'] or 'sin fecha'}"
        for t in tasks
    ]) if tasks else "No hay tareas pendientes."

    today = datetime.now().strftime("%Y-%m-%d")

    system = f"""Eres Jade, asistente personal de productividad de Vivian.
Vivian es Territory Product Manager de NUC, Chromebox y Mini PC para Sudamerica en Intel.
Su region incluye: Colombia, Ecuador, Centroamerica, Chile, Peru y Argentina.
Sus KPIs son revenue y unidades por trimestre en 3 categorias: MR/AR (Mini PC + NUC Barebone), MS/AS (Mini PC + NUC System) y GX10.
Hoy es {today}.

KPIs 2026:
{kpis}

Tareas actuales en Notion:
{task_list}

Cuando Vivian pregunte sobre prioridades, conecta sus tareas con sus KPIs.
Eres conversacional, inteligente y concisa. Recuerdas conversaciones anteriores.

Puedes ejecutar acciones incluyendolas AL FINAL de tu respuesta:
[ACCION: {{"tipo": "crear", "nombre": "...", "prioridad": "Alta|Media|Baja", "fecha": "YYYY-MM-DD o null"}}]
[ACCION: {{"tipo": "done", "nombre": "parte del nombre de la tarea"}}]
[ACCION: {{"tipo": "nota", "tarea": "parte del nombre", "nota": "texto de la nota"}}]

Solo incluye ACCION si el usuario pide explicitamente crear tarea, completar tarea o agregar nota.
Responde siempre en español."""

    history.append({"role": "user", "content": user_message})
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1000,
            "system": system,
            "messages": history
        },
        timeout=30
    )
    data = response.json()
    if "content" not in data:
        return "Hubo un error. Intenta de nuevo.", None

    full_response = data["content"][0]["text"]
    history.append({"role": "assistant", "content": full_response})
    save_memory(history)

    action = None
    clean_response = full_response
    if "[ACCION:" in full_response:
        try:
            action_str = full_response.split("[ACCION:")[1].split("]")[0].strip()
            action = json.loads(action_str)
            clean_response = full_response.split("[ACCION:")[0].strip()
        except:
            pass

    return clean_response, action

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        message = data.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()

        if chat_id != ALLOWED_CHAT_ID:
            return "ok"

        if text in ["/start", "/help"]:
            send_message(chat_id, "Hola, soy *Jade*!\n\nHabla conmigo naturalmente:\n- _que tengo pendiente?_\n- _como voy con mis KPIs?_\n- _agrega tarea: llamar a proveedor_\n- _ya termine el pipeline_\n- _agrega nota al pipeline: bloqueado_\n- _dame las noticias tech_")
            return "ok"

        text_lower = text.lower()

        if any(word in text_lower for word in ["noticia", "boletin", "boletín", "noticias tech", "novedades tech"]):
            send_message(chat_id, "📰 Preparando tu boletin tech... te llega en unos segundos.")
            thread = threading.Thread(target=generate_and_send_news, args=(chat_id,))
            thread.daemon = True
            thread.start()
            return "ok"

        tasks = get_tasks()
        kpis = get_kpis()
        response_text, action = ask_jade(text, tasks, kpis)

        if action:
            if action.get("tipo") == "crear":
                success = create_task(name=action.get("nombre", ""), priority=action.get("prioridad", "Media"), due=action.get("fecha"))
                response_text += f"\n\n✅ Cree *{action.get('nombre')}* en Notion." if success else "\n\n❌ No pude crear la tarea."
            elif action.get("tipo") == "done":
                completed = mark_task_done(action.get("nombre", ""))
                response_text += f"\n\n✅ Marque *{completed}* como Done en Notion." if completed else "\n\n❌ No encontre la tarea."
            elif action.get("tipo") == "nota":
                saved = add_note_to_task(action.get("tarea", ""), action.get("nota", ""))
                response_text += f"\n\n📝 Nota agregada a *{saved}* en Notion." if saved else "\n\n❌ No encontre la tarea."

        send_message(chat_id, response_text)

    except Exception as e:
        print(f"ERROR: {e}")
        send_message(chat_id, "Hubo un error. Intenta de nuevo.")

    return "ok"

@app.route("/")
def home():
    return "Jade esta activa"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
