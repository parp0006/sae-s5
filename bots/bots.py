import os, re, time, random, requests, logging
from bs4 import BeautifulSoup

FLARUM   = os.getenv("FLARUM_URL", "http://localhost")
KEY      = os.environ["FLARUM_KEY"]
OLLAMA   = os.getenv("LLM_URL", "http://localhost:11434/v1/chat/completions")
MAX_PER_HOUR = 20
MAX_CONTEXT_POSTS = 12

BOTS = {
    2: {"name": "Alice", "model": "mistral",
        "persona": "Tu es Alice, optimiste et pragmatique. Tu participes à un forum. "
                   "Réponds en français, 2 à 4 phrases, sans te présenter ni répéter les autres."},
    3: {"name": "Bob", "model": "qwen2.5:7b",
        "persona": "Tu es Bob, sceptique et ironique, mais poli. Réponds en français, 2 à 4 phrases."},
    4: {"name": "Chloé", "model": "gemma2:9b",
        "persona": "Tu es Chloé, curieuse et philosophe. Pose parfois une question. 2 à 4 phrases."},
}
NAMES = {uid: b["name"] for uid, b in BOTS.items()}

logging.basicConfig(level=logging.INFO)
sent_times = []

def hdr(uid):
    return {"Authorization": f"Token {KEY}; userId={uid}", "Content-Type": "application/json"}

def clean(html):
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)   # modèles « raisonneurs »
    return text.strip()

def get_discussion(did):
    r = requests.get(f"{FLARUM}/api/discussions/{did}", headers=hdr(2), timeout=30)
    r.raise_for_status()
    return r.json()

def get_posts(did):
    r = requests.get(f"{FLARUM}/api/posts", headers=hdr(2), timeout=30, params={
        "filter[discussion]": did, "sort": "-createdAt", "page[limit]": MAX_CONTEXT_POSTS,
        "include": "user"})
    r.raise_for_status()
    j = r.json()
    users = {u["id"]: u["attributes"]["displayName"] for u in j.get("included", []) if u["type"] == "users"}
    posts = list(reversed(j["data"]))
    out = []
    for p in posts:
        uid = p["relationships"]["user"]["data"]["id"]
        out.append((int(uid), users.get(uid, "Inconnu"), clean(p["attributes"].get("contentHtml", ""))))
    return out

def build_messages(bot, posts):
    msgs = [{"role": "system", "content": bot["persona"]}]
    for uid, name, text in posts:
        role = "assistant" if NAMES.get(uid) == bot["name"] else "user"
        content = text if role == "assistant" else f"{name} : {text}"
        msgs.append({"role": role, "content": content})
    return msgs

def ask_llm(bot, posts):
    r = requests.post(OLLAMA, timeout=300, json={
        "model": bot["model"], "messages": build_messages(bot, posts),
        "temperature": 0.9, "max_tokens": 250})
    r.raise_for_status()
    txt = clean(r.json()["choices"][0]["message"]["content"])
    return re.sub(rf"^{bot['name']}\s*:\s*", "", txt)        # enlève un préfixe « Alice : »

def post(did, uid, content):
    body = {"data": {"type": "posts", "attributes": {"content": content},
            "relationships": {"discussion": {"data": {"type": "discussions", "id": str(did)}}}}}
    r = requests.post(f"{FLARUM}/api/posts", json=body, headers=hdr(uid), timeout=30)
    r.raise_for_status()

def rate_ok():
    now = time.time()
    sent_times[:] = [t for t in sent_times if now - t < 3600]
    return len(sent_times) < MAX_PER_HOUR

def step(did):
    posts = get_posts(did)
    last_uid = posts[-1][0]
    candidates = [u for u in BOTS if u != last_uid]
    uid = random.choice(candidates)
    reply = ask_llm(BOTS[uid], posts)
    if len(reply) > 5:
        post(did, uid, reply)
        sent_times.append(time.time())
        logging.info("%s a répondu dans %s", BOTS[uid]["name"], did)

if __name__ == "__main__":
    DISCUSSIONS = [int(x) for x in os.getenv("DISCUSSIONS", "1").split(",")]
    while True:
        if os.path.exists("/tmp/STOP_BOTS"):          # interrupteur d'arrêt
            time.sleep(10); continue
        if rate_ok():
            try:
                step(random.choice(DISCUSSIONS))
            except Exception as e:
                logging.error("Erreur : %s", e)
        time.sleep(random.randint(30, 180))
