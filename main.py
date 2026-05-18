import os
import json
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID")
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# Memoria de conversacion en memoria (se resetea al reiniciar)
conversation_history = []

def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })

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
                "properties": {
                    "Status": {"status": {"name": "Done"}}
                }
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

def ask_claude_conversational(user_message, tasks):
    global conversation_history

    task_list = "\n".join([
        f"- {t['name']} | Estado: {t['status']} | Prioridad: {t['priority']} | Vence: {t['due'] or 'sin fecha'}"
        for t in tasks
    ]) if tasks else "No hay tareas pendientes."

    system = f"""Eres Jade, asistente personal de productividad de Vivian. Eres conversacional, util y concisa.

Tienes acceso a las tareas actuales de Notion:
{task_list}

Puedes hacer estas acciones respondiendo con JSON al final de tu mensaje cuando sea necesario:
- Crear tarea: [ACCION: {{"tipo": "crear", "nombre": "...", "prioridad": "Alta|Media|Baja", "fecha": "YYYY-MM-DD o null"}}]
- Marcar como done: [ACCION: {{"tipo": "done", "nombre": "parte del nombre"}}]

Si no necesitas hacer ninguna accion, no incluyas el bloque ACCION.
Responde siempre en español. Se breve y directa."""

    conversation_history.append({"role": "user", "content": user_message})

    # Mantener solo los ultimos 10 mensajes
    if len(conversation_history) > 10:
        conversation_history = conversation_history[-10:]

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
            "messages": conversation_history
        }
    )
    data = response.json()
    if "content" not in data:
        return "Hubo un error. Intenta de nuevo.", None

    full_response = data["content"][0]["text"]
    conversation_history.append({"role": "assistant", "content": full_response})

    # Extraer accion si existe
    action = None
    if "[ACCION:" in full_response:
        try:
            action_str = full_response.split("[ACCION:")[1].split("]")[0].strip()
            action = json.loads(action_str)
            # Limpiar el texto de la respuesta
            clean_response = full_response.split("[ACCION:")[0].strip()
        except:
            clean_response = full_response
    else:
        clean_response = full_response

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
            send_message(chat_id, "Hola, soy *Jade*!\n\nPuedo ayudarte con tus tareas de Notion. Habla conmigo naturalmente, por ejemplo:\n- _que tengo pendiente hoy?_\n- _agrega una tarea para llamar al proveedor_\n- _ya termine la tarea del pipeline_\n- _que deberia priorizar esta semana?_")
            return "ok"

        tasks = get_tasks()
        response_text, action = ask_claude_conversational(text, tasks)

        # Ejecutar accion si Claude la indico
        if action:
            if action.get("tipo") == "crear":
                success = create_task(
                    name=action.get("nombre", ""),
                    priority=action.get("prioridad", "Media"),
                    due=action.get("fecha")
                )
                if success:
                    response_text += f"\n\n✅ Cree la tarea *{action.get('nombre')}* en Notion."
                else:
                    response_text += "\n\n❌ No pude crear la tarea en Notion."

            elif action.get("tipo") == "done":
                completed = mark_task_done(action.get("nombre", ""))
                if completed:
                    response_text += f"\n\n✅ Marque *{completed}* como Done en Notion."
                else:
                    response_text += f"\n\n❌ No encontre la tarea '{action.get('nombre')}' en Notion."

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
