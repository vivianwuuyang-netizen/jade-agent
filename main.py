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
    response = requests.post(url, headers=NOTION_HEADERS, json={
        "filter": {
            "property": "Status",
            "select": {
                "does_not_equal": "Done"
            }
        }
    })
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
        if status_prop and status_prop.get("select"):
            status = status_prop["select"].get("name", "")
        priority = ""
        priority_prop = props.get("Prioridad")
        if priority_prop and priority_prop.get("select"):
            priority = priority_prop["select"].get("name", "")
        due = ""
        due_prop = props.get("Fecha límite") or props.get("Fecha Límite") or props.get("Due")
        if due_prop and due_prop.get("date") and due_prop["date"]:
            due = due_prop["date"].get("start", "")
        if name:
            tasks.append({
                "id": page["id"],
                "name": name,
                "status": status,
                "priority": priority,
                "due": due
            })
    return tasks

def mark_task_done(task_name, tasks):
    for task in tasks:
        if task_name.lower() in task["name"].lower():
            url = f"https://api.notion.com/v1/pages/{task['id']}"
            requests.patch(url, headers=NOTION_HEADERS, json={
                "properties": {
                    "Status": {"select": {"name": "Done"}}
                }
            })
            return task["name"]
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
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    data = response.json()
    return data["content"][0]["text"]

def analyze_tasks(tasks):
    if not tasks:
        return "No tienes tareas pendientes. ¡Todo al día! ✅"
    task_list = "\n".join([
        f"- {t['name']} | Estado: {t['status']} | Prioridad: {t['priority']} | Fecha límite: {t['due'] or 'sin fecha'}"
        for t in tasks
    ])
    prompt = f"""Eres Jade, asistente personal de productividad. Analiza estas tareas pendientes y responde en español de forma concisa y útil:

{task_list}

Responde con:
1. 🚨 *Urgente* — tareas vencidas o críticas
2. 🎯 *Top 3 para hoy* — las más importantes
3. 💡 *Recomendación* — un consejo breve para avanzar

Usa emojis y formato Telegram (con *negrita*)."""
    return ask_claude(prompt)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if chat_id != ALLOWED_CHAT_ID:
        return "ok"

    text_lower = text.lower()

    if any(word in text_lower for word in ["pendiente", "tarea", "hoy", "semana", "analiza", "jade", "que tengo", "qué tengo"]):
        send_message(chat_id, "🔍 Revisando tus tareas en Notion...")
        tasks = get_tasks()
        analysis = analyze_tasks(tasks)
        send_message(chat_id, analysis)

    elif any(word in text_lower for word in ["completé", "complete", "terminé", "termine", "done", "hice", "ya hice", "ya terminé"]):
        send_message(chat_id, "🔍 Buscando la tarea en Notion...")
        tasks = get_tasks()
        words_to_remove = ["completé", "complete", "terminé", "termine", "done", "hice", "ya hice", "ya terminé", "la tarea", "la"]
        task_name = text_lower
        for word in words_to_remove:
            task_name = task_name.replace(word, "").strip()
        completed = mark_task_done(task_name, tasks)
        if completed:
            send_message(chat_id, f"✅ Marqué *{completed}* como Done en Notion.")
        else:
            send_message(chat_id, "No encontré esa tarea. ¿Puedes escribir parte del nombre exacto?")

    elif text_lower in ["/start", "/help", "ayuda", "hola"]:
        send_message(chat_id, "👋 Hola, soy *Jade*, tu asistente de productividad.\n\nPuedes escribirme:\n• *¿Qué tengo pendiente?* → analizo tus tareas\n• *Completé [nombre de tarea]* → la marco como Done en Notion\n• *Hola* → te saludo 😊")

    else:
        send_message(chat_id, "No entendí bien. Escríbeme *¿qué tengo pendiente?* para ver tus tareas, o *completé [tarea]* para marcar una como lista.")

    return "ok"

@app.route("/")
def home():
    return "Jade está activa ✅"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
