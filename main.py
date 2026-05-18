import os
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

def mark_task_done(task_name, all_tasks):
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

def parse_new_task(text, claude_key):
    prompt = f"""Extrae la información de esta tarea y devuelve SOLO un JSON sin backticks:
"{text}"

Formato exacto:
{{"name": "nombre de la tarea", "priority": "Alta|Media|Baja", "due": "YYYY-MM-DD o null"}}

Si no se menciona prioridad usa "Media". Si no se menciona fecha usa null."""
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": claude_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    data = response.json()
    if "content" not in data:
        return None
    import json
    try:
        text_response = data["content"][0]["text"].strip()
        return json.loads(text_response)
    except:
        return None

def ask_claude(prompt):
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
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    data = response.json()
    if "content" not in data:
        return f"Error: {data.get('error', {}).get('message', str(data))}"
    return data["content"][0]["text"]

def analyze_tasks(tasks):
    if not tasks:
        return "No tienes tareas pendientes. Todo al dia!"
    task_list = "\n".join([
        f"- {t['name']} | Estado: {t['status']} | Prioridad: {t['priority']} | Fecha limite: {t['due'] or 'sin fecha'}"
        for t in tasks
    ])
    prompt = f"""Eres Jade, asistente personal de productividad. Analiza estas tareas pendientes y responde en español de forma concisa:

{task_list}

Responde con:
1. Urgente: tareas vencidas o criticas
2. Top 3 para hoy: las mas importantes
3. Recomendacion: un consejo breve para avanzar"""
    return ask_claude(prompt)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        message = data.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()

        if chat_id != ALLOWED_CHAT_ID:
            return "ok"

        text_lower = text.lower()

        if any(word in text_lower for word in ["pendiente", "tarea", "hoy", "semana", "analiza", "jade", "que tengo"]):
            send_message(chat_id, "Revisando tus tareas en Notion...")
            tasks = get_tasks()
            analysis = analyze_tasks(tasks)
            send_message(chat_id, analysis)

        elif any(word in text_lower for word in ["nueva tarea", "agregar tarea", "crear tarea", "nueva:", "tarea:"]):
            send_message(chat_id, "Creando tarea en Notion...")
            task_info = parse_new_task(text, CLAUDE_API_KEY)
            if task_info:
                success = create_task(
                    name=task_info.get("name", text),
                    priority=task_info.get("priority", "Media"),
                    due=task_info.get("due")
                )
                if success:
                    due_text = f", fecha: {task_info.get('due')}" if task_info.get("due") else ""
                    send_message(chat_id, f"Tarea creada en Notion:\n*{task_info.get('name')}*\nPrioridad: {task_info.get('priority')}{due_text}")
                else:
                    send_message(chat_id, "No pude crear la tarea. Intenta de nuevo.")
            else:
                send_message(chat_id, "No entendi bien la tarea. Ejemplo: 'nueva tarea: reunión con cliente, prioridad alta, 2026-05-20'")

        elif any(word in text_lower for word in ["complete", "termine", "done", "hice", "ya hice"]):
            send_message(chat_id, "Buscando la tarea en Notion...")
            all_tasks = get_all_tasks()
            words_to_remove = ["complete", "termine", "done", "hice", "ya hice", "la tarea", "la"]
            task_name = text_lower
            for word in words_to_remove:
                task_name = task_name.replace(word, "").strip()
            completed = mark_task_done(task_name, all_tasks)
            if completed:
                send_message(chat_id, f"Marque '{completed}' como Done en Notion.")
            else:
                send_message(chat_id, "No encontre esa tarea. Escribe parte del nombre exacto.")

        elif text_lower in ["/start", "/help", "ayuda", "hola"]:
            send_message(chat_id, "Hola, soy *Jade*!\n\nEscribeme:\n- *que tengo pendiente* → analizo tus tareas\n- *nueva tarea: [descripcion]* → creo la tarea en Notion\n- *complete [nombre]* → marco como Done en Notion")

        else:
            send_message(chat_id, "Escribeme *que tengo pendiente*, *nueva tarea: [descripcion]*, o *complete [nombre]*.")

    except Exception as e:
        print(f"ERROR: {e}")

    return "ok"

@app.route("/")
def home():
    return "Jade esta activa"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
