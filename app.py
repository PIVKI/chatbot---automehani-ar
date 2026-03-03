from flask import Flask, request, session, jsonify, render_template_string
import re
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

KNOWN_BRANDS = [
    "bmw","audi","mercedes","vw","volkswagen","opel","ford","toyota","honda","kia","hyundai",
    "peugeot","renault","fiat","škoda","skoda","seat","tesla","mazda","nissan","citroen","citroën",
    "volvo","alfa","alfa romeo","suzuki","dacia","mini"
]

STOP_WORDS = {
    "i","ne","mu","se","pri","kad","iz","na","u","je","su","mi","ti","ga","ju","me","te",
    "velikoj","brzini","brzina","hladno","hladan","toplo","topao","pali","radi","koci","koči",
    "trese","vibrira","na","od","do"
}

CAR_TRIGGERS = [
    "auto","automobil","vozilo","motor","mjenjač","mjenjac","kvačilo","kvacilo","kočnice","kocnice",
    "ulje","filter","gume","pneumatik","akumulator","baterija","benzin","dizel","diesel","lpg","plin",
    "turbo","dpf","egr","obd","servis","registracija","tehnički","tehnicki","check engine","lampica",
    "kilometri","km","ne pali","vergla","trese","vibrira","dim","dimi","kucka","škripi","skripi","curi",
    "pregrijava","grije","proklizava","vuče","bucha","buči","ne koči","ne koci"
]

WHAT_IS = {
    "kvačilo": "Kvačilo spaja/razdvaja motor od mjenjača. Kad pritisneš papučicu, odvaja pogon da možeš mijenjati brzine.",
    "kvacilo": "Kvačilo spaja/razdvaja motor od mjenjača. Kad pritisneš papučicu, odvaja pogon da možeš mijenjati brzine.",
    "mjenjač": "Mjenjač mijenja prijenosni omjer kako bi auto imao snagu pri kretanju i nižu potrošnju pri većoj brzini.",
    "mjenjac": "Mjenjač mijenja prijenosni omjer kako bi auto imao snagu pri kretanju i nižu potrošnju pri većoj brzini.",
    "dpf": "DPF je filter čestica na dizelu. Hvata čađu i povremeno radi regeneraciju (spaljivanje čađe).",
    "egr": "EGR ventil vraća dio ispušnih plinova u usis radi smanjenja NOx. Kad se zaprlja, može uzrokovati dim i gubitak snage.",
    "turbo": "Turbo povećava snagu komprimiranjem zraka. Kvar se često vidi kao gubitak snage, dim ili zviždanje."
}

def norm(s: str) -> str:
    return " ".join((s or "").lower().strip().split())

def is_short_reply(text: str) -> bool:
    t = norm(text)
    if t in {"da","ne","dizel","benzin","plin","lpg"}:
        return True
    if re.fullmatch(r"\d+", t):
        return True
    if re.fullmatch(r"\d+\s*-\s*\d+", t):
        return True
    if re.fullmatch(r"\d+\s*(km/h|kmh)", t):
        return True
    return False

def is_car_topic(text: str) -> bool:
    t = norm(text)
    if any(b in t for b in KNOWN_BRANDS):
        return True
    if any(k in t for k in CAR_TRIGGERS):
        return True
    if re.search(r"\b\d+\s*(km/h|kmh|ks|hp)\b", t):
        return True
    if t.startswith(("što je","sta je","šta je")) and any(k in t for k in WHAT_IS):
        return True
    return False

def extract_brand_model(text: str):
    t = norm(text)

    brand_key = None
    for b in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if b in t:
            brand_key = b
            break
    if not brand_key:
        return None, None

    brand_norm = brand_key
    if brand_norm == "vw":
        brand_norm = "volkswagen"
    if brand_norm in ["škoda","skoda"]:
        brand_norm = "skoda"

    idx = t.find(brand_key)
    after = t[idx + len(brand_key):].strip()
    tokens = after.split()

    model_tokens = []
    for tok in tokens:
        clean = re.sub(r"[^\w\-]", "", tok)
        if not clean:
            continue
        if clean in STOP_WORDS:
            break
        if re.match(r"^(19\d{2}|20\d{2})$", clean):
            break
        if re.match(r"^\d\.\d$", clean):
            break
        model_tokens.append(clean)
        if len(model_tokens) == 2:
            break

    model = " ".join(model_tokens).strip() or None
    return brand_norm.title(), (model.upper() if model else None)

def extract_year_engine(text: str, ctx: dict) -> None:
    t = norm(text)
    m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if m:
        ctx["year"] = m.group(1)

    m = re.search(r"\b(\d\.\d)\s*(tdi|tsi|tfsi|dci|hdi|cdti|jtd|tce|mpi|gdi|crdi)\b", t)
    if m:
        ctx["engine"] = f"{m.group(1)} {m.group(2).upper()}"

def ctx_line(ctx: dict) -> str:
    parts = []
    for k in ("brand","model","year","engine","fuel"):
        if ctx.get(k):
            parts.append(ctx[k])
    return " / ".join(parts) if parts else "nije postavljeno"

def set_issue(ctx: dict, issue: str, step: str = None):
    ctx["issue"] = issue
    if step:
        ctx["step"] = step

def update_context(user: str, ctx: dict):
    brand, model = extract_brand_model(user)
    if brand and ctx.get("brand") and brand != ctx.get("brand"):
        for k in ("model","year","engine","fuel","issue","step","speed_range","cranks_ok"):
            ctx.pop(k, None)

    if brand:
        ctx["brand"] = brand
    if model:
        ctx["model"] = model

    extract_year_engine(user, ctx)

    t = norm(user)
    if t in ("dizel","diesel"):
        ctx["fuel"] = "DIZEL"
    elif t == "benzin":
        ctx["fuel"] = "BENZIN"
    elif t in ("lpg","plin"):
        ctx["fuel"] = "LPG"

def parse_speed(text: str):
    t = norm(text).replace("km/h","").replace("kmh","").strip()
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a,b), max(a,b))
    m = re.fullmatch(r"(\d+)", t)
    if m:
        v = int(m.group(1))
        return (v, v)
    return None

def reply(user: str, ctx: dict) -> str:
    t = norm(user)
    car = ctx_line(ctx)

    # komande
    if t in ("status","stanje"):
        return f"Tvoj auto: {car}"
    if t in ("reset","obrisi","obriši","novi auto"):
        ctx.clear()
        return "U redu — obrisao sam spremljene podatke o autu."
    if t in ("auto","postavi auto","set auto"):
        return "Napiši npr: 'Imam Renault Clio 4 2016 1.5 dCi' pa ću zapamtiti."

    # "što je"
    if t.startswith(("što je","sta je","šta je")):
        for k,v in WHAT_IS.items():
            if k in t:
                return v

    # detekcija problema
    if "trese" in t or "vibrira" in t:
        set_issue(ctx, "vibracije", "ask_speed")
        return f"[{car}] Na kojoj brzini se trese? (npr. 80-100 ili 100)"

    if ("ne pali" in t) or ("neće upaliti" in t) or ("nece upaliti" in t) or ("vergla" in t):
        set_issue(ctx, "ne_pali", "ask_crank")
        if ctx.get("fuel"):
            return f"[{car}] Vergla li normalno (da/ne)?"
        return f"[{car}] Je li benzin ili dizel?"

    if ("ne koči" in t) or ("ne koci" in t) or ("kočnice" in t) or ("kocnice" in t):
        set_issue(ctx, "kocnice", "ask_pedal")
        return f"[{car}] Kakav je osjećaj na pedali: tvrda ili spužvasta? (tvrda/spužvasta)"

    if ("kvačilo" in t) or ("kvacilo" in t):
        if any(x in t for x in ("ne radi","prokliz","klize")):
            set_issue(ctx, "kvacilo", "ask_slip")
            return f"[{car}] Proklizava li u višim brzinama pod gasom? (da/ne)"
        return WHAT_IS["kvačilo"]

    # koraci dijagnostike
    issue = ctx.get("issue")
    step = ctx.get("step")

    if issue == "vibracije" and step == "ask_speed":
        sp = parse_speed(user)
        if sp:
            ctx["speed_range"] = sp
            set_issue(ctx, "vibracije", "ask_gas")
            a,b = sp
            s = f"{a}" if a==b else f"{a}-{b}"
            return (f"[{car}] OK, trese na {s} km/h.\n"
                    "Događa li se pod gasom ili i kad pustiš gas? (pod gasom / bez gasa / oba)")
        return f"[{car}] Napiši brzinu kao broj (100) ili raspon (80-100)."

    if issue == "vibracije" and step == "ask_gas":
        if "pod gasom" in t:
            set_issue(ctx, "vibracije", "done")
            return (f"[{car}] Ako trese uglavnom pod gasom: moguće poluosovine/homokinetički zglobovi, nosači motora "
                    "ili (kod dizela) zamašnjak.\n"
                    "Osjetiš li trešnju u volanu ili u sjedalu?")
        if "bez gasa" in t or "kad pustim" in t or "pustim gas" in t:
            set_issue(ctx, "vibracije", "done")
            return (f"[{car}] Ako trese i bez gasa: najčešće gume (balans), felge, geometrija ili ležaj kotača.\n"
                    "Prvi korak: balans + provjera felgi i tlaka u gumama.")
        if "oba" in t:
            set_issue(ctx, "vibracije", "done")
            return (f"[{car}] Ako trese i pod gasom i bez gasa: kreni od guma/balansa/geometrije pa tek onda poluosovine.\n"
                    "Je li više u volanu ili u sjedalu?")
        return f"[{car}] Odgovori: 'pod gasom', 'bez gasa' ili 'oba'."

    if issue == "ne_pali":
        if step == "ask_crank":
            if not ctx.get("fuel"):
                if t in ("dizel","diesel"):
                    ctx["fuel"] = "DIZEL"
                    return f"[{car}] Vergla li normalno (da/ne)?"
                if t == "benzin":
                    ctx["fuel"] = "BENZIN"
                    return f"[{car}] Vergla li normalno (da/ne)?"
                return f"[{car}] Napiši: benzin ili dizel."

            if t in ("da","ne"):
                ctx["cranks_ok"] = (t == "da")
                set_issue(ctx, "ne_pali", "ask_temp")
                return f"[{car}] Je li problem samo kad je hladno? (da/ne)"
            return f"[{car}] Odgovori 'da' ili 'ne' (vergla li normalno)."

        if step == "ask_temp":
            if t in ("da","ne"):
                cold_only = (t == "da")
                set_issue(ctx, "ne_pali", "done")

                fuel = ctx.get("fuel","?")
                cranks_ok = ctx.get("cranks_ok", True)

                if not cranks_ok:
                    return (f"[{car}] Ako slabo vergla: prvo akumulator, kleme, mase i anlaser. Zimi je to najčešće.")
                if fuel == "DIZEL" and cold_only:
                    return (f"[{car}] Dizel i pali loše na hladno: grijači/grijačna elektronika, slab akumulator "
                            "ili zrak u dovodu goriva.\n"
                            "Ako možeš: OBD očitanje + test grijača.")
                if fuel == "BENZIN" and cold_only:
                    return (f"[{car}] Benzin i pali loše na hladno: svjećice, bobine (coil), senzor temperature "
                            "ili prljava leptirasta zaklopka.\n"
                            "Pali li iz druge i osjetiš li miris benzina?")
                return (f"[{car}] Ako vergla normalno a ne pali: dovod goriva/senzori (radilica/bregasta) + OBD greške.\n"
                        "Pali li se 'check engine'?")
            return f"[{car}] Odgovori 'da' ili 'ne'."

    if issue == "kocnice" and step == "ask_pedal":
        if "tvrda" in t:
            set_issue(ctx, "kocnice", "done")
            return (f"[{car}] Tvrda pedala: često problem s vakuumom (vakuum crijevo/pumpa) ili pojačivačem kočnica.\n"
                    "Čuje li se šištanje ili je pedala tvrda stalno?")
        if "spužvasta" in t or "spuzvasta" in t:
            set_issue(ctx, "kocnice", "done")
            return (f"[{car}] Spužvasta pedala: zrak u sistemu, niska tekućina ili curenje.\n"
                    "Provjeri razinu tekućine i tragove curenja na kotačima/kliještima.")
        return f"[{car}] Napiši: 'tvrda' ili 'spužvasta'."

    if issue == "kvacilo" and step == "ask_slip":
        if t in ("da","ne"):
            set_issue(ctx, "kvacilo", "done")
            if t == "da":
                return (f"[{car}] Proklizavanje: istrošeno kvačilo ili zamašnjak (često kod dizela). "
                        "Tipično rješenje je zamjena seta kvačila (često i zamašnjaka).")
            return (f"[{car}] Ako ne proklizava, a teško odvaja: moguća hidraulika (cilindri) ili problem s isključivanjem.\n"
                    "Je li teško ubaciti u brzinu dok je motor upaljen? (da/ne)")
        return f"[{car}] Odgovori 'da' ili 'ne'."

    # kratki odgovor bez aktivnog problema
    if is_short_reply(user) and not ctx.get("issue"):
        return f"[{car}] To izgleda kao kratak odgovor. Napiši i problem (npr. 'trese na 100' ili 'dizel ne pali')."

    return f"[{car}] Napiši problem (npr. 'trese', 'ne pali', 'ne koči', 'check engine')."

HTML = """
<!doctype html>
<html lang="hr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Auto Mehaničar Chat</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 0; background:#0b0f14; color:#e8eef5; }
    .wrap { max-width: 860px; margin: 0 auto; padding: 16px; }
    .card { background:#121a24; border:1px solid #1f2a38; border-radius: 14px; padding: 14px; }
    .msgs { height: 62vh; overflow:auto; padding: 10px; border-radius: 12px; background:#0e151f; border:1px solid #1f2a38; }
    .m { margin: 10px 0; display:flex; gap:10px; }
    .me { justify-content:flex-end; }
    .b { max-width: 78%; padding: 10px 12px; border-radius: 12px; white-space: pre-wrap; line-height:1.25; }
    .me .b { background:#2a3a52; }
    .bot .b { background:#162233; }
    .row { display:flex; gap:10px; margin-top: 12px; }
    input { flex:1; padding: 12px; border-radius: 12px; border:1px solid #1f2a38; background:#0e151f; color:#e8eef5; }
    button { padding: 12px 14px; border-radius: 12px; border:1px solid #1f2a38; background:#1a2a3f; color:#e8eef5; cursor:pointer; }
    .hint { opacity:.85; font-size: 13px; margin: 10px 2px 0; }
    .chips { display:flex; flex-wrap:wrap; gap:8px; margin: 10px 0 0; }
    .chip { font-size: 13px; padding: 8px 10px; border-radius: 999px; border:1px solid #1f2a38; background:#0e151f; cursor:pointer; }
  </style>
</head>
<body>
  <div class="wrap">
    <h2 style="margin:6px 2px 10px;">🚗 Auto Mehaničar Chat</h2>
    <div class="card">
      <div id="msgs" class="msgs"></div>

      <div class="chips">
        <div class="chip" onclick="sendChip('Imam Renault Clio 4 2016 1.5 dCi')">Postavi auto</div>
        <div class="chip" onclick="sendChip('trese na 100')">Trese</div>
        <div class="chip" onclick="sendChip('ne pali hladan dizel')">Ne pali</div>
        <div class="chip" onclick="sendChip('ne koči dobro')">Kočnice</div>
        <div class="chip" onclick="sendChip('status')">Status</div>
        <div class="chip" onclick="sendChip('reset')">Reset</div>
      </div>

      <div class="row">
        <input id="inp" placeholder="Napiši problem (npr. 'trese', 'ne pali', 'ne koči')..." />
        <button onclick="send()">Pošalji</button>
      </div>
      <div class="hint">Savjet: možeš odgovarati kratko (npr. <b>100</b>, <b>80-100</b>, <b>dizel</b>, <b>da/ne</b>) — pamti kontekst.</div>
    </div>
  </div>

<script>
const msgs = document.getElementById('msgs');
const inp = document.getElementById('inp');

function add(role, text){
  const row = document.createElement('div');
  row.className = 'm ' + (role === 'me' ? 'me' : 'bot');
  const b = document.createElement('div');
  b.className = 'b';
  b.textContent = text;
  row.appendChild(b);
  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;
}

async function send(){
  const text = inp.value.trim();
  if(!text) return;
  inp.value = '';
  add('me', text);

  const res = await fetch('/chat', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({message:text})
  });
  const data = await res.json();
  add('bot', data.reply);
}

function sendChip(t){
  inp.value = t;
  send();
}

inp.addEventListener('keydown', (e)=>{ if(e.key==='Enter') send(); });

add('bot', "Bok! Napiši npr. 'Imam Golf 6 2012 1.6 TDI' pa zatim problem: 'trese', 'ne pali', 'ne koči'.");
</script>
</body>
</html>
"""

@app.get("/")
def home():
    if "ctx" not in session:
        session["ctx"] = {}
    return render_template_string(HTML)

@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()

    ctx = session.get("ctx", {})
    # dozvoli kratke odgovore ako je u tijeku issue
    if not is_car_topic(msg) and not (is_short_reply(msg) and ctx.get("issue")):
        return jsonify({"reply": "Odgovaram samo na temu automobila 🚗. Napiši problem vezan uz auto."})

    update_context(msg, ctx)
    r = reply(msg, ctx)

    session["ctx"] = ctx
    return jsonify({"reply": r})
from flask import render_template_string

HTML = """
<!doctype html>
<html>
<head>
  <title>Chatbot Automehaničar</title>
</head>
<body style="font-family:Arial; padding:20px;">
  <h2>🚗 Chatbot Automehaničar radi!</h2>
  <p>Aplikacija je uspješno deployana na Render.</p>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
