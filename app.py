from __future__ import annotations
import sqlite3
from contextlib import contextmanager

import json
import os
from datetime import date, datetime
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troca-isto-por-uma-chave-forte")


# =========================
# Paths / Data files
# =========================
def _ensure_data_dir() -> None:
    os.makedirs("data", exist_ok=True)


def get_data_path() -> str:
    _ensure_data_dir()
    return os.path.join("data", "vigilantes_registo.json")


def get_viaturas_path() -> str:
    _ensure_data_dir()
    return os.path.join("data", "viaturas.txt")


def get_users_path() -> str:
    _ensure_data_dir()
    return os.path.join("data", "users.json")


def get_settings_path() -> str:
    _ensure_data_dir()
    return os.path.join("data", "system_settings.json")


# =========================
# System Settings
# =========================
def _default_settings() -> Dict[str, Any]:
    return {
        "enable_multi_matricula": True,
        "enable_user_edit_occurrence": False,
    }


def carregar_settings() -> Dict[str, Any]:
    path = get_settings_path()
    if not os.path.exists(path):
        s = _default_settings()
        guardar_settings(s)
        return s

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        base = _default_settings()
        for k, v in base.items():
            data.setdefault(k, v)
        return {k: data.get(k) for k in base.keys()}
    except Exception:
        s = _default_settings()
        guardar_settings(s)
        return s


def guardar_settings(settings: Dict[str, Any]) -> None:
    base = _default_settings()
    safe = {k: bool(settings.get(k)) for k in base.keys()}
    with open(get_settings_path(), "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)


# =========================
# Context global (templates)
# =========================
@app.context_processor
def inject_globals():
    return {
        "current_user_ordem": session.get("user_ordem"),
        "current_user_is_admin": session.get("role") == "admin",
        "system_settings": carregar_settings(),
    }


# =========================
# Viaturas helpers
# =========================
def _normalizar_viatura(v: str) -> str:
    v = (v or "").strip()
    v = " ".join(v.split())
    return v.upper()


def carregar_viaturas() -> List[str]:
    path = get_viaturas_path()

    if not os.path.exists(path):
        exemplos = ["VPN 01", "VPN 02", "VPN 03"]
        with open(path, "w", encoding="utf-8") as f:
            for v in exemplos:
                f.write(v + "\n")

    with open(path, "r", encoding="utf-8") as f:
        return [linha.strip() for linha in f if linha.strip()]


def guardar_viaturas(lista: List[str]) -> List[str]:
    path = get_viaturas_path()
    lista = [(_normalizar_viatura(v)) for v in (lista or []) if _normalizar_viatura(v)]

    seen = set()
    final: List[str] = []
    for v in lista:
        if v not in seen:
            seen.add(v)
            final.append(v)

    with open(path, "w", encoding="utf-8") as f:
        for v in final:
            f.write(v + "\n")

    return final


# =========================
# AUTH: Users helpers (login por Nº ORDEM)
# =========================
def _users_estrutura_inicial() -> Dict[str, Any]:
    admin_ordem = os.environ.get("ADMIN_ORDEM", "190123").strip()
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@admin.com").strip().lower()
    admin_pwd = os.environ.get("ADMIN_PASSWORD", "12345678")

    return {
        "users": {
            admin_ordem: {
                "ordem": admin_ordem,
                "email": admin_email,
                "role": "admin",
                "password_hash": generate_password_hash(admin_pwd),
                "must_change": True,
                "active": True,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        }
    }


def guardar_users(data: Dict[str, Any]) -> None:
    with open(get_users_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def carregar_users() -> Dict[str, Any]:
    path = get_users_path()
    if not os.path.exists(path):
        data = _users_estrutura_inicial()
        guardar_users(data)
        return data

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        if "users" not in data or not isinstance(data["users"], dict):
            data = _users_estrutura_inicial()
            guardar_users(data)
        return data
    except Exception:
        data = _users_estrutura_inicial()
        guardar_users(data)
        return data


def get_user_by_ordem(ordem: str) -> Optional[Dict[str, Any]]:
    data = carregar_users()
    return (data.get("users") or {}).get((ordem or "").strip())


def set_user(user: Dict[str, Any]) -> None:
    data = carregar_users()
    users_dict = data.get("users") or {}
    users_dict[user["ordem"]] = user
    data["users"] = users_dict
    guardar_users(data)


def delete_user(ordem: str) -> bool:
    ordem = (ordem or "").strip()
    data = carregar_users()
    users_dict = data.get("users") or {}
    if ordem in users_dict:
        del users_dict[ordem]
        data["users"] = users_dict
        guardar_users(data)
        return True
    return False


# =========================
# Decorators
# =========================
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_ordem"):
            return redirect(url_for("login"))
        if session.get("must_change") and request.endpoint not in {"alterar_password", "logout"}:
            return redirect(url_for("alterar_password"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_ordem"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


# =========================
# Registo / Ocorrências data
# =========================
def periodo_atual() -> str:
    hour = datetime.now().hour
    return "Manhã" if hour < 13 else "Tarde"


def novo_registo_principal_limpo() -> dict:
    return {
        "data": date.today().strftime("%d/%m/%Y"),
        "periodo": periodo_atual(),
        "viatura": "",
        "num_ordem_cct": "",
        "num_ordem_pm": "",
        "registo_guardado": False,
    }


def _estrutura_inicial() -> dict:
    return {"registo_principal": novo_registo_principal_limpo(), "ocorrencias": []}


def carregar_dados() -> dict:
    path = get_data_path()
    if not os.path.exists(path):
        return _estrutura_inicial()

    try:
        with open(path, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if "ocorrencias" not in dados or not isinstance(dados["ocorrencias"], list):
            dados["ocorrencias"] = []
        if "registo_principal" not in dados or not isinstance(dados["registo_principal"], dict):
            dados["registo_principal"] = novo_registo_principal_limpo()

        if "historico_ocorrencias" in dados and isinstance(dados["historico_ocorrencias"], list):
            dados["ocorrencias"].extend(dados["historico_ocorrencias"])
            del dados["historico_ocorrencias"]

        base = novo_registo_principal_limpo()
        for k, v in base.items():
            dados["registo_principal"].setdefault(k, v)

        return dados
    except Exception:
        return _estrutura_inicial()


def guardar_dados(dados: dict) -> None:
    with open(get_data_path(), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def proximo_id_ocorrencia(dados: dict) -> int:
    ocorrencias = dados.get("ocorrencias", []) or []
    if not ocorrencias:
        return 1
    return max(int(o.get("id", 0) or 0) for o in ocorrencias) + 1


def obter_todas_ocorrencias_ordenadas(dados: dict) -> List[dict]:
    ocorrencias = dados.get("ocorrencias", []) or []

    def chave(o: dict):
        try:
            d = datetime.strptime(o.get("data", ""), "%d/%m/%Y")
        except Exception:
            d = datetime.min
        try:
            h = datetime.strptime(o.get("hora", "00:00"), "%H:%M").time()
        except Exception:
            h = datetime.strptime("00:00", "%H:%M").time()
        return (d, h)

    return sorted(ocorrencias, key=chave, reverse=True)


def filtrar_ocorrencias_do_servico(dados: dict) -> List[dict]:
    reg = dados.get("registo_principal", {}) or {}
    ocorrencias = dados.get("ocorrencias", []) or []

    if not reg.get("registo_guardado"):
        return []

    data_srv = (reg.get("data") or "").strip()
    periodo = (reg.get("periodo") or "").strip()
    cct = (reg.get("num_ordem_cct") or "").strip()

    def match(o: dict) -> bool:
        return (
            (o.get("data") or "").strip() == data_srv
            and (o.get("periodo") or "").strip() == periodo
            and (o.get("numero_ordem_cct") or "").strip() == cct
        )

    filtradas = [o for o in ocorrencias if match(o)]

    def chave_dt(o: dict):
        dt_txt = f"{(o.get('data') or '').strip()} {(o.get('hora') or '00:00').strip()}"
        try:
            return datetime.strptime(dt_txt, "%d/%m/%Y %H:%M")
        except Exception:
            return datetime.min

    return sorted(filtradas, key=chave_dt, reverse=True)


def _user_pode_mexer_nesta_ocorrencia(occ: dict) -> bool:
    if session.get("role") == "admin":
        return True
    return (occ.get("numero_ordem_cct") or "").strip() == (session.get("user_ordem") or "").strip()


# =========================
# AUTH: Rotas
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    ordem = (request.form.get("ordem") or "").strip()
    password = request.form.get("password") or ""

    user = get_user_by_ordem(ordem)
    if not user or not user.get("active"):
        flash("Login inválido.", "danger")
        return redirect(url_for("login"))

    if not check_password_hash(user.get("password_hash", ""), password):
        flash("Login inválido.", "danger")
        return redirect(url_for("login"))

    session["user_ordem"] = user["ordem"]
    session["role"] = user.get("role", "user")
    session["must_change"] = bool(user.get("must_change"))

    if session["must_change"]:
        flash("Tens de definir uma nova palavra-passe.", "warning")
        return redirect(url_for("alterar_password"))

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/alterar_password", methods=["GET", "POST"])
@login_required
def alterar_password():
    if request.method == "GET":
        return render_template("alterar_password.html")

    p1 = request.form.get("nova_password") or ""
    p2 = request.form.get("repetir_password") or ""

    if len(p1) < 8:
        flash("A palavra-passe deve ter pelo menos 8 caracteres.", "danger")
        return redirect(url_for("alterar_password"))

    if p1 != p2:
        flash("As palavras-passe não coincidem.", "danger")
        return redirect(url_for("alterar_password"))

    ordem = session.get("user_ordem")
    user = get_user_by_ordem(ordem)
    if not user:
        session.clear()
        return redirect(url_for("login"))

    user["password_hash"] = generate_password_hash(p1)
    user["must_change"] = False
    set_user(user)

    session["must_change"] = False
    flash("Palavra-passe atualizada com sucesso.", "success")
    return redirect(url_for("index"))


# =========================
# Admin: Parametrizações do sistema
# =========================
@app.route("/admin/parametrizacoes", methods=["GET", "POST"])
@admin_required
def admin_parametrizacoes():
    settings = carregar_settings()

    if request.method == "POST":
        settings["enable_user_edit_occurrence"] = bool(request.form.get("enable_user_edit_occurrence"))
        settings["enable_multi_matricula"] = bool(request.form.get("enable_multi_matricula"))
        guardar_settings(settings)
        flash("Parametrizações guardadas.", "success")
        return redirect(url_for("admin_parametrizacoes"))

    return render_template("admin_parametrizacoes.html", settings=settings)


# =========================
# Admin: Gerir logins
# =========================
@app.route("/admin/logins", methods=["GET", "POST"])
@admin_required
def admin_logins():
    data = carregar_users()
    users_dict = data["users"]

    if request.method == "POST":
        acao = (request.form.get("acao") or "").strip()

        if acao == "adicionar":
            ordem = (request.form.get("ordem") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            role = (request.form.get("role") or "user").strip()

            if not ordem.isdigit() or len(ordem) < 4:
                flash("Nº de ordem inválido (usa apenas dígitos).", "danger")
                return redirect(url_for("admin_logins"))

            if not email or "@" not in email:
                flash("Email inválido.", "danger")
                return redirect(url_for("admin_logins"))

            if ordem in users_dict:
                flash("Esse nº de ordem já existe.", "warning")
                return redirect(url_for("admin_logins"))

            users_dict[ordem] = {
                "ordem": ordem,
                "email": email,
                "role": "admin" if role == "admin" else "user",
                "password_hash": generate_password_hash("12345678"),
                "must_change": True,
                "active": True,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            guardar_users(data)
            flash(
                "Utilizador criado. Password temporária: 12345678 (obrigado a trocar no login).",
                "success",
            )
            return redirect(url_for("admin_logins"))

        if acao == "reset":
            ordem = (request.form.get("ordem") or "").strip()
            u = users_dict.get(ordem)
            if not u:
                flash("Utilizador não encontrado.", "danger")
                return redirect(url_for("admin_logins"))

            u["password_hash"] = generate_password_hash("12345678")
            u["must_change"] = True
            users_dict[ordem] = u
            guardar_users(data)
            flash(f"Password reposta para 12345678 (ordem {ordem}).", "success")
            return redirect(url_for("admin_logins", edit=ordem))

        if acao == "toggle_active":
            ordem = (request.form.get("ordem") or "").strip()
            u = users_dict.get(ordem)
            if not u:
                flash("Utilizador não encontrado.", "danger")
                return redirect(url_for("admin_logins"))

            if ordem == session.get("user_ordem"):
                flash("Não podes desativar o teu próprio utilizador.", "warning")
                return redirect(url_for("admin_logins", edit=ordem))

            u["active"] = not bool(u.get("active"))
            users_dict[ordem] = u
            guardar_users(data)
            flash("Estado atualizado.", "success")
            return redirect(url_for("admin_logins", edit=ordem))

        if acao == "guardar_edicao":
            ordem_antiga = (request.form.get("ordem_antiga") or "").strip()
            ordem_nova = (request.form.get("ordem") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            role = (request.form.get("role") or "user").strip()
            active = request.form.get("active") == "1"

            u = users_dict.get(ordem_antiga)
            if not u:
                flash("Utilizador não encontrado.", "danger")
                return redirect(url_for("admin_logins"))

            if not ordem_nova.isdigit() or len(ordem_nova) < 4:
                flash("Nº de ordem inválido (usa apenas dígitos).", "danger")
                return redirect(url_for("admin_logins", edit=ordem_antiga))

            if not email or "@" not in email:
                flash("Email inválido.", "danger")
                return redirect(url_for("admin_logins", edit=ordem_antiga))

            if ordem_nova != ordem_antiga and ordem_nova in users_dict:
                flash("Já existe um utilizador com esse nº de ordem.", "danger")
                return redirect(url_for("admin_logins", edit=ordem_antiga))

            if ordem_antiga == session.get("user_ordem") and role != "admin":
                flash("Não podes retirar o teu próprio perfil de admin.", "warning")
                return redirect(url_for("admin_logins", edit=ordem_antiga))

            u["ordem"] = ordem_nova
            u["email"] = email
            u["role"] = "admin" if role == "admin" else "user"
            u["active"] = active

            if ordem_nova != ordem_antiga:
                del users_dict[ordem_antiga]
            users_dict[ordem_nova] = u

            guardar_users(data)
            flash("Utilizador atualizado.", "success")

            if ordem_antiga == session.get("user_ordem"):
                session["user_ordem"] = ordem_nova
                session["role"] = u["role"]

            return redirect(url_for("admin_logins", edit=ordem_nova))

        if acao == "eliminar":
            ordem = (request.form.get("ordem") or "").strip()
            if ordem == session.get("user_ordem"):
                flash("Não podes eliminar o teu próprio utilizador.", "warning")
                return redirect(url_for("admin_logins", edit=ordem))

            ok = delete_user(ordem)
            flash("Utilizador eliminado." if ok else "Utilizador não encontrado.", "success" if ok else "danger")
            return redirect(url_for("admin_logins"))

    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "todos").strip()
    edit = (request.args.get("edit") or "").strip()

    users_list = list(users_dict.values())

    if q:
        users_list = [u for u in users_list if q in (u.get("ordem") or "")]

    if status == "ativos":
        users_list = [u for u in users_list if u.get("active")]
    elif status == "inativos":
        users_list = [u for u in users_list if not u.get("active")]

    def _sort(u: dict):
        return (0 if u.get("role") == "admin" else 1, u.get("ordem") or "")

    users_list = sorted(users_list, key=_sort)
    edit_user = users_dict.get(edit) if edit else None

    return render_template(
        "admin_logins.html",
        users=users_list,
        q=q,
        status=status,
        edit_user=edit_user,
    )


# =========================
# Admin: Gerir viaturas
# =========================
@app.route("/admin/viaturas", methods=["GET", "POST"])
@admin_required
def admin_viaturas():
    viaturas = carregar_viaturas()

    if request.method == "POST":
        acao = (request.form.get("acao") or "").strip()

        if acao == "adicionar":
            nova = _normalizar_viatura(request.form.get("viatura") or "")
            if not nova:
                flash("Indica uma viatura válida.", "danger")
                return redirect(url_for("admin_viaturas"))

            existentes = set(_normalizar_viatura(v) for v in viaturas)
            if nova in existentes:
                flash("Essa viatura já existe.", "warning")
                return redirect(url_for("admin_viaturas"))

            viaturas.append(nova)
            guardar_viaturas(viaturas)
            flash("Viatura adicionada.", "success")
            return redirect(url_for("admin_viaturas"))

        if acao == "eliminar":
            v = _normalizar_viatura(request.form.get("viatura") or "")
            viaturas = [x for x in viaturas if _normalizar_viatura(x) != v]
            guardar_viaturas(viaturas)
            flash("Viatura removida.", "success")
            return redirect(url_for("admin_viaturas"))

        if acao == "guardar_edicao":
            antiga = _normalizar_viatura(request.form.get("antiga") or "")
            nova = _normalizar_viatura(request.form.get("nova") or "")

            if not antiga or not nova:
                flash("Preenche a viatura antiga e a nova.", "danger")
                return redirect(url_for("admin_viaturas", edit=antiga))

            existentes = set(_normalizar_viatura(v) for v in viaturas)
            if nova in existentes and nova != antiga:
                flash("Já existe uma viatura com esse nome.", "warning")
                return redirect(url_for("admin_viaturas", edit=antiga))

            novas_lista: List[str] = []
            for x in viaturas:
                if _normalizar_viatura(x) == antiga:
                    novas_lista.append(nova)
                else:
                    novas_lista.append(_normalizar_viatura(x))

            guardar_viaturas(novas_lista)
            flash("Viatura atualizada.", "success")
            return redirect(url_for("admin_viaturas"))

    edit = _normalizar_viatura(request.args.get("edit") or "")
    edit_viatura = None
    if edit:
        for v in viaturas:
            if _normalizar_viatura(v) == edit:
                edit_viatura = _normalizar_viatura(v)
                break

    viaturas = [_normalizar_viatura(v) for v in viaturas]
    viaturas = sorted(list(dict.fromkeys(viaturas)))

    return render_template("admin_viaturas.html", viaturas=viaturas, edit_viatura=edit_viatura)


# =========================
# ROTAS DO SISTEMA
# =========================
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    dados = carregar_dados()
    registo = dados.get("registo_principal", {}) or {}

    if request.method == "POST":
        acao = (request.form.get("acao") or "").strip()

        if acao == "guardar_registo":
            data_iso = (request.form.get("data") or "").strip()
            try:
                d = datetime.strptime(data_iso, "%Y-%m-%d").date()
                data_pt = d.strftime("%d/%m/%Y")
            except Exception:
                data_pt = date.today().strftime("%d/%m/%Y")

            periodo = (request.form.get("periodo") or "").strip() or periodo_atual()
            viatura = _normalizar_viatura(request.form.get("viatura") or "")
            num_ordem_cct = (request.form.get("num_ordem_cct") or "").strip()
            num_ordem_pm = (request.form.get("num_ordem_pm") or "").strip()

            if not viatura:
                flash("Seleciona uma viatura.", "danger")
                return redirect(url_for("index"))

            if not num_ordem_pm:
                flash("Indica o Nº PM.", "danger")
                return redirect(url_for("index"))

            registo["data"] = data_pt
            registo["periodo"] = periodo
            registo["viatura"] = viatura
            registo["num_ordem_cct"] = num_ordem_cct
            registo["num_ordem_pm"] = num_ordem_pm
            registo["registo_guardado"] = True

            dados["registo_principal"] = registo
            guardar_dados(dados)
            return redirect(url_for("index"))

    viaturas = carregar_viaturas()
    fim_ok = request.args.get("fim_ok") == "1"

    try:
        d = datetime.strptime(registo.get("data") or "", "%d/%m/%Y").date()
    except Exception:
        d = date.today()
    data_iso = d.strftime("%Y-%m-%d")

    ocorrencias_servico = filtrar_ocorrencias_do_servico(dados)

    return render_template(
        "index.html",
        registo=registo,
        ocorrencias=ocorrencias_servico,
        viaturas=viaturas,
        data_iso=data_iso,
        fim_ok=fim_ok,
        tipos_ocorrencia=[
            "Multas em corredor BUS",
            "Multas em áreas de paragem",
            "Multas a dificultar manobra",
            "Multa – outras situações",
            "Pedidos de reboque",
            "Pedidos de bloqueamento",
            "Advertências",
            "Observações gerais",
        ],
    )


@app.route("/ocorrencias/nova", methods=["GET", "POST"])
@login_required
def nova_ocorrencia():
    dados = carregar_dados()
    registo = dados["registo_principal"]
    settings = carregar_settings()

    if not registo.get("registo_guardado"):
        return redirect(url_for("index"))

    if request.method == "GET":
        tipo = request.args.get("tipo", "Ocorrência")
        agora = datetime.now()
        return render_template(
            "nova_ocorrencia.html",
            tipo=tipo,
            data_ocorr=agora.strftime("%d/%m/%Y"),
            hora_ocorr=agora.strftime("%H:%M"),
        )

    tipo = (request.form.get("tipo") or "").strip()
    descricao = (request.form.get("descricao", "") or "").strip()
    data_ocorr = (request.form.get("data_ocorr", "") or "").strip()
    hora_ocorr = (request.form.get("hora_ocorr", "") or "").strip()
    morada = (request.form.get("morada", "") or "").strip()
    latitude = (request.form.get("latitude", "") or "").strip()
    longitude = (request.form.get("longitude", "") or "").strip()

    if not tipo or not data_ocorr or not hora_ocorr:
        return redirect(url_for("index"))

    if tipo == "Observações gerais":
        if not descricao:
            return redirect(url_for("index"))

        occ = {
            "id": proximo_id_ocorrencia(dados),
            "data": data_ocorr,
            "hora": hora_ocorr,
            "periodo": registo.get("periodo", ""),
            "viatura": registo.get("viatura", ""),
            "numero_ordem_cct": registo.get("num_ordem_cct", ""),
            "numero_ordem_pm": registo.get("num_ordem_pm", ""),
            "tipo": tipo,
            "matricula": "",
            "morada": "",
            "latitude": "",
            "longitude": "",
            "descricao": descricao,
        }
        dados["ocorrencias"].append(occ)
        guardar_dados(dados)
        return redirect(url_for("index"))

    if not morada:
        return redirect(url_for("index"))

    matriculas: List[str] = []
    if settings.get("enable_multi_matricula"):
        matriculas = [m.upper().strip() for m in request.form.getlist("matriculas[]") if (m or "").strip()]
        if not matriculas:
            m1 = (request.form.get("matricula") or "").upper().strip()
            if m1:
                matriculas = [m1]
    else:
        m1 = (request.form.get("matricula") or "").upper().strip()
        if m1:
            matriculas = [m1]

    matriculas = list(dict.fromkeys(matriculas))

    if not matriculas:
        return redirect(url_for("index"))

    next_id = proximo_id_ocorrencia(dados)
    for m in matriculas:
        occ = {
            "id": next_id,
            "data": data_ocorr,
            "hora": hora_ocorr,
            "periodo": registo.get("periodo", ""),
            "viatura": registo.get("viatura", ""),
            "numero_ordem_cct": registo.get("num_ordem_cct", ""),
            "numero_ordem_pm": registo.get("num_ordem_pm", ""),
            "tipo": tipo,
            "matricula": m,
            "morada": morada,
            "latitude": latitude,
            "longitude": longitude,
            "descricao": descricao,
        }
        dados["ocorrencias"].append(occ)
        next_id += 1

    guardar_dados(dados)
    return redirect(url_for("index"))


@app.route("/ocorrencias/<int:occ_id>")
@login_required
def detalhe_ocorrencia(occ_id: int):
    dados = carregar_dados()
    occ = next((o for o in (dados.get("ocorrencias", []) or []) if o.get("id") == occ_id), None)
    if not occ:
        return redirect(url_for("index"))

    registo = dados["registo_principal"]
    return render_template("detalhe_ocorrencia.html", ocorrencia=occ, registo=registo)


@app.route("/ocorrencias/<int:occ_id>/editar", methods=["GET", "POST"])
@login_required
def editar_ocorrencia_user(occ_id: int):
    settings = carregar_settings()
    if not settings.get("enable_user_edit_occurrence"):
        abort(404)

    dados = carregar_dados()
    ocorrencias = dados.get("ocorrencias", []) or []
    occ = next((o for o in ocorrencias if o.get("id") == occ_id), None)
    if not occ:
        return redirect(url_for("index"))

    if not _user_pode_mexer_nesta_ocorrencia(occ):
        abort(403)

    if request.method == "GET":
        return render_template("editar_ocorrencia.html", ocorrencia=occ)

    campos = ["tipo", "matricula", "morada", "latitude", "longitude", "descricao"]
    for c in campos:
        val = (request.form.get(c, "") or "").strip()
        if c == "matricula":
            val = val.upper()
        occ[c] = val

    guardar_dados(dados)
    flash("Ocorrência atualizada.", "success")
    return redirect(url_for("detalhe_ocorrencia", occ_id=occ_id))


@app.route("/ocorrencias/<int:occ_id>/apagar", methods=["POST"])
@login_required
def apagar_ocorrencia(occ_id: int):
    dados = carregar_dados()
    dados["ocorrencias"] = [o for o in (dados.get("ocorrencias", []) or []) if o.get("id") != occ_id]
    guardar_dados(dados)
    return redirect(url_for("index"))


# =========================
# Admin: Ocorrências (✅ filtros + export CSV)
# =========================
@app.route("/admin/ocorrencias")
@admin_required
def admin_ocorrencias():
    import csv
    from io import StringIO

    dados = carregar_dados()
    ocorrencias = obter_todas_ocorrencias_ordenadas(dados)

    # filtros GET
    data_de = (request.args.get("data_de") or "").strip()       # YYYY-MM-DD
    data_ate = (request.args.get("data_ate") or "").strip()     # YYYY-MM-DD
    tipo = (request.args.get("tipo") or "").strip()
    viatura = (request.args.get("viatura") or "").strip().upper()
    cct = (request.args.get("cct") or "").strip()
    pm = (request.args.get("pm") or "").strip()
    matricula = (request.args.get("matricula") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()

    def _parse_iso(d: str):
        try:
            return datetime.strptime(d, "%Y-%m-%d").date()
        except Exception:
            return None

    def _parse_pt(d: str):
        try:
            return datetime.strptime(d, "%d/%m/%Y").date()
        except Exception:
            return None

    d_de = _parse_iso(data_de) if data_de else None
    d_ate = _parse_iso(data_ate) if data_ate else None

    filtradas: List[dict] = []
    for o in ocorrencias:
        d_occ = _parse_pt((o.get("data") or "").strip())

        if d_de and d_occ and d_occ < d_de:
            continue
        if d_ate and d_occ and d_occ > d_ate:
            continue

        if tipo and (o.get("tipo") or "").strip() != tipo:
            continue

        if viatura and (o.get("viatura") or "").strip().upper() != viatura:
            continue

        if cct and (o.get("numero_ordem_cct") or "").strip() != cct:
            continue

        if pm and (o.get("numero_ordem_pm") or "").strip() != pm:
            continue

        if matricula and matricula not in (o.get("matricula") or "").strip().upper():
            continue

        if q:
            hay = " ".join([
                (o.get("data") or ""),
                (o.get("hora") or ""),
                (o.get("periodo") or ""),
                (o.get("viatura") or ""),
                (o.get("numero_ordem_cct") or ""),
                (o.get("numero_ordem_pm") or ""),
                (o.get("tipo") or ""),
                (o.get("matricula") or ""),
                (o.get("morada") or ""),
                (o.get("descricao") or ""),
                (o.get("latitude") or ""),
                (o.get("longitude") or ""),
            ]).lower()
            if q not in hay:
                continue

        filtradas.append(o)

    # ✅ Export CSV (respeita filtros) - CORRIGIDO PARA EXCEL (UTF-8 BOM)
    if request.args.get("export") == "1":
        out = StringIO()
        writer = csv.writer(out, delimiter=";", lineterminator="\n")

        writer.writerow([
            "id", "data", "hora", "periodo", "viatura",
            "numero_ordem_cct", "numero_ordem_pm",
            "tipo", "matricula", "morada", "latitude", "longitude", "descricao",
        ])

        for o in filtradas:
            writer.writerow([
                o.get("id", ""),
                o.get("data", ""),
                o.get("hora", ""),
                o.get("periodo", ""),
                o.get("viatura", ""),
                o.get("numero_ordem_cct", ""),
                o.get("numero_ordem_pm", ""),
                o.get("tipo", ""),
                o.get("matricula", ""),
                o.get("morada", ""),
                o.get("latitude", ""),
                o.get("longitude", ""),
                o.get("descricao", ""),
            ])

        filename = f"ocorrencias_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        csv_text = out.getvalue()

        # 🔥 BOM para o Excel interpretar UTF-8 e não aparecer ManhÃ£
        csv_text = "\ufeff" + csv_text

        return Response(
            csv_text,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # dropdowns
    tipos = sorted({(o.get("tipo") or "").strip() for o in ocorrencias if (o.get("tipo") or "").strip()})
    viaturas = sorted({(o.get("viatura") or "").strip() for o in ocorrencias if (o.get("viatura") or "").strip()})

    return render_template(
        "admin_ocorrencias.html",
        ocorrencias=filtradas,
        filtros={
            "data_de": data_de,
            "data_ate": data_ate,
            "tipo": tipo,
            "viatura": viatura,
            "cct": cct,
            "pm": pm,
            "matricula": matricula,
            "q": q,
        },
        tipos=tipos,
        viaturas=viaturas,
        total=len(filtradas),
    )


@app.route("/admin/ocorrencias/<int:occ_id>/apagar", methods=["POST"])
@admin_required
def admin_apagar_ocorrencia(occ_id: int):
    dados = carregar_dados()
    dados["ocorrencias"] = [o for o in (dados.get("ocorrencias", []) or []) if o.get("id") != occ_id]
    guardar_dados(dados)
    return redirect(url_for("admin_ocorrencias"))


@app.route("/admin/ocorrencias/<int:occ_id>/editar", methods=["GET", "POST"])
@admin_required
def admin_editar_ocorrencia(occ_id: int):
    dados = carregar_dados()
    ocorrencias = dados.get("ocorrencias", []) or []
    occ = next((o for o in ocorrencias if o.get("id") == occ_id), None)
    if not occ:
        return redirect(url_for("admin_ocorrencias"))

    if request.method == "GET":
        return render_template("admin_editar_ocorrencia.html", ocorrencia=occ)

    campos = [
        "data",
        "hora",
        "periodo",
        "viatura",
        "numero_ordem_cct",
        "numero_ordem_pm",
        "tipo",
        "matricula",
        "morada",
        "latitude",
        "longitude",
        "descricao",
    ]

    for c in campos:
        val = (request.form.get(c, "") or "").strip()
        if c == "matricula":
            val = val.upper()
        if c == "viatura":
            val = _normalizar_viatura(val)
        occ[c] = val

    guardar_dados(dados)
    return redirect(url_for("admin_ocorrencias"))


# =========================
# Fim de serviço
# =========================
@app.route("/fim_servico", methods=["POST"])
@login_required
def fim_servico():
    dados = carregar_dados()
    registo = dados.get("registo_principal", {}) or {}

    if not registo.get("registo_guardado"):
        dados["registo_principal"] = novo_registo_principal_limpo()
        guardar_dados(dados)
        return redirect(url_for("index", fim_ok=1))

    ocorrencias_servico = filtrar_ocorrencias_do_servico(dados)

    if len(ocorrencias_servico) == 0:
        agora = datetime.now()
        ocorrencia_auto = {
            "id": proximo_id_ocorrencia(dados),
            "data": (registo.get("data") or date.today().strftime("%d/%m/%Y")),
            "hora": agora.strftime("%H:%M"),
            "periodo": (registo.get("periodo") or ""),
            "viatura": (registo.get("viatura") or ""),
            "numero_ordem_cct": (registo.get("num_ordem_cct") or ""),
            "numero_ordem_pm": (registo.get("num_ordem_pm") or ""),
            "tipo": "Sem Ocorrências",
            "matricula": "",
            "morada": "",
            "latitude": "",
            "longitude": "",
            "descricao": "",
        }
        dados["ocorrencias"].append(ocorrencia_auto)

    dados["registo_principal"] = novo_registo_principal_limpo()
    guardar_dados(dados)
    return redirect(url_for("index", fim_ok=1))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
