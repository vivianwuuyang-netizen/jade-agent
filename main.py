import os
import json
import requests
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
    """Lee los KPIs desde la pagina de Notion"""
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
                table_id = block["id"]
                rows_url = f"https://api.notion.com/v1/blocks/{table_id}/children"
                rows_response = requests.get(rows_url, headers=NOTION_HEADERS)
                rows = rows_response.json().get("results", [])
                for row in rows:
                    cells = row.get("table_row", {}).get("cells", [])
                    row_text = " | ".join([
                        cell[0]["plain_text"] if cell else ""
                        for cell in cells
                    ])
                    kpi_text.append(row_text)
            elif block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                rich_text = block.get(block_type, {}).get("rich_text", [])
                if rich_text:
                    kpi_text.append(rich_text[0].get("plain_text", ""))
        return "\n".join(kpi_text) if kpi_text else "No se pudieron cargar los KPIs."
    except Exception as e:
        print(f"Error leyendo KPIs: {e}")
        return "No se pudieron cargar los KPIs."

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
            tasks.append({
                "id": page["id"],
                "name": name,
                "status": status,
                "priority": priority,
                "due": due
            })
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
    all_tasks = get_all_tasks()
    for task in all_tasks:
        if task_name.lower() in task["name"].lower():
            url = f"https://api.notion.com/v1/pages/{task['id']}"
            requests.patch(url, headers=NOTION_HEADERS, json={
                "properties": {"Status": {"status": {"name": "Done"}}}
            })
            return task["name"]
    return None

def create_task(name, priority="Media", due=None):
    url = "https://api.notion.com/v1/pages"
    properties = {
        "Tarea": {"title": [{"text": {"content": name}}]},
        "Prioridad": {"select": {"name": priority}},
        "Status": {"status": {"name": "Not started"}}
    }
    if due:
        properties["Fecha límite"] = {"date": {"start": due}}
    response = requests.post(url, headers=NOTION_HEADERS, json={
        "parent": {"database_id": NOTION_DB_ID},
        "properties": properties
    })
    return response.status_code == 200

def add_note_to_task(task_name, note):
    all_tasks = get_all_tasks()
    for task in all_tasks:
        if task_name.lower() in task["name"].lower():
            today = datetime.now().strftime("%Y-%m-%d %H:%M")
            url = f"https://api.notion.com/v1/blocks/{task['id']}/children"
            response = requests.patch(url, headers=NOTION_HEADERS, json={
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

def ask_jade(user_message, tasks, kpis):
    history = load_memory()

    task_list = "\n".join([
        f"- {t['name']} | Estado: {t['status']} | Prioridad: {t['priority']} | Vence: {t['due'] or 'sin fecha'}"
        for t in tasks
    ]) if tasks else "No hay tareas pendientes."

    today = datetime.now().strftime("%Y-%m-%d")
    current_month = datetime.now().strftime("%B")

    system = f"""Eres Jade, asistente personal de productividad de Vivian.
Vivian es Territory Product Manager de NUC, Chromebox y Mini PC para Sudamerica en Intel.
Su region incluye: Colombia, Ecuador, Centroamerica, Chile, Peru y Argentina.
Sus KPIs se miden en revenue y unidades por trimestre en 3 categorias: MR/AR (Mini PC + NUC Barebone), MS/AS (Mini PC + NUC System) y GX10.
Hoy es {today}. Mes actual: {current_month}.

KPIs 2026 (metas anuales y avance mensual):
{kpis}

Tareas actuales en Notion:
{task_list}

Cuando Vivian te pregunte sobre prioridades, conecta sus tareas con sus KPIs. 
Por ejemplo: si hay una orden grande de MR/AR pendiente y estamos cerca del cierre del trimestre, esa orden es critica para el KPI.

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
        }
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
            send_message(chat_id, "Hola, soy *Jade*!\n\nHabla conmigo naturalmente:\n- _que tengo pendiente?_\n- _agrega tarea: llamar a proveedor el viernes_\n- _ya termine el pipeline_\n- _agrega nota al pipeline: bloqueado por presupuesto_\n- _como voy con mis KPIs este trimestre?_")
            return "ok"

        tasks = get_tasks()
        kpis = get_kpis()
        response_text, action = ask_jade(text, tasks, kpis)

        if action:
            if action.get("tipo") == "crear":
                success = create_task(
                    name=action.get("nombre", ""),
                    priority=action.get("prioridad", "Media"),
                    due=action.get("fecha")
                )
                if success:
                    response_text += f"\n\n✅ Cree *{action.get('nombre')}* en Notion."
                else:
                    response_text += "\n\n❌ No pude crear la tarea en Notion."

            elif action.get("tipo") == "done":
                completed = mark_task_done(action.get("nombre", ""))
                if completed:
                    response_text += f"\n\n✅ Marque *{completed}* como Done en Notion."
                else:
                    response_text += f"\n\n❌ No encontre la tarea en Notion."

            elif action.get("tipo") == "nota":
                saved = add_note_to_task(action.get("tarea", ""), action.get("nota", ""))
                if saved:
                    response_text += f"\n\n📝 Nota agregada a *{saved}* en Notion."
                else:
                    response_text += f"\n\n❌ No encontre la tarea para agregar la nota."

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
