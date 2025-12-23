from flask import Flask, render_template, request, redirect, url_for, Response
from datetime import datetime, date
import os
import json
import io

app = Flask(__name__)

# =========================
#  FICHEIROS (JSON + VIATURAS)
# =========================

def get_data_path():
    os.makedirs("data", exist_ok=True)
    return os.path.join("data", "vigilantes_registo.json")


def get_viaturas_path():
    os.makedirs("data", exist_ok=True)
    return os.path.join("data", "viaturas.txt")


def carregar_viaturas():
    """
    Lê a lista de viaturas do ficheiro data/viaturas.txt.
    Uma viatura por linha. Se não existir, cria com alguns exemplos.
    """
    path = get_viaturas_path()

    if not os.path.exists(path):
        exemplos = ["VPN 01", "VPN 02", "VPN 03"]
        with open(path, "w", encoding="utf-8") as f:
            for v in exemplos:
                f.write(v + "\n")

    viaturas = []
    with open(path, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                viaturas.append(linha)

    return viaturas


# =========================
#  PERÍODO AUTOMÁTICO
# =========================

def periodo_atual(dt=None) -> str:
    dt = dt or datetime.now()
    return "Manhã" if dt.hour < 13 else "Tarde"


def novo_registo_principal_limpo() -> dict:
    return {
        "data": date.today().strftime("%d/%m/%Y"),
        "periodo": periodo_atual(),
        "viatura": "",
        "num_ordem_cct": "",
        "num_ordem_pm": "",
        "registo_guardado": False,
    }


def _estrutura_inicial():
    # ÚNICO JSON: todas as ocorrências ficam em "ocorrencias"
    return {
        "registo_principal": novo_registo_principal_limpo(),
        "ocorrencias": []
    }


def carregar_dados():
    """
    Carrega o JSON único.
    Migração automática:
      - se existirem chaves antigas como 'historico_ocorrencias', junta tudo em 'ocorrencias'
    """
    path = get_data_path()
    if not os.path.exists(path):
        return _estrutura_inicial()

    try:
        with open(path, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if not isinstance(dados, dict):
            return _estrutura_inicial()

        # garantir estrutura
        dados.setdefault("registo_principal", novo_registo_principal_limpo())
        dados.setdefault("ocorrencias", [])

        # migração (se vier de versões antigas)
        if "historico_ocorrencias" in dados:
            hist = dados.get("historico_ocorrencias") or []
            atuais = dados.get("ocorrencias") or []
            if isinstance(hist, list) and isinstance(atuais, list):
                dados["ocorrencias"] = hist + atuais
            dados.pop("historico_ocorrencias", None)

        # garantir campos do registo_principal
        base = novo_registo_principal_limpo()
        if not isinstance(dados["registo_principal"], dict):
            dados["registo_principal"] = base
        else:
            for k, v in base.items():
                dados["registo_principal"].setdefault(k, v)

        # garantir lista
        if not isinstance(dados["ocorrencias"], list):
            dados["ocorrencias"] = []

        return dados

    except Exception:
        return _estrutura_inicial()


def guardar_dados(dados):
    path = get_data_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def proximo_id_ocorrencia(dados):
    ocorrencias = dados.get("ocorrencias", []) or []
    if not ocorrencias:
        return 1
    return max(int(o.get("id", 0) or 0) for o in ocorrencias) + 1


def servico_key_do_registo(registo: dict) -> str:
    """
    Chave estável para separar ocorrências por "serviço".
    Assim:
      - index mostra apenas ocorrências do serviço atual
      - admin mostra todas
    """
    data_ = (registo.get("data") or "").strip()
    periodo = (registo.get("periodo") or "").strip()
    viatura = (registo.get("viatura") or "").strip()
    cct = (registo.get("num_ordem_cct") or "").strip()
    pm = (registo.get("num_ordem_pm") or "").strip()
    return f"{data_}|{periodo}|{viatura}|{cct}|{pm}"


def ocorrencias_do_servico(dados, registo):
    key = servico_key_do_registo(registo)
    return [o for o in (dados.get("ocorrencias", []) or []) if (o.get("servico_key") or "") == key]


def ordenar_ocorrencias(occs):
    def chave(o):
        # data dd/mm/yyyy + hora HH:MM
        try:
            d = datetime.strptime(o.get("data", ""), "%d/%m/%Y")
        except Exception:
            d = datetime.min
        try:
            t = datetime.strptime(o.get("hora", "00:00"), "%H:%M").time()
        except Exception:
            t = datetime.strptime("00:00", "%H:%M").time()
        return (d, t)
    return sorted(occs, key=chave, reverse=False)


# =========================
#  ROTAS
# =========================

@app.route("/", methods=["GET", "POST"])
def index():
    dados = carregar_dados()
    registo = dados["registo_principal"]

    # Quando NÃO está guardado, o formulário abre sempre LIMPO
    if request.method == "GET" and not registo.get("registo_guardado"):
        dados["registo_principal"] = novo_registo_principal_limpo()
        registo = dados["registo_principal"]
        guardar_dados(dados)

    viaturas = carregar_viaturas()

    if request.method == "POST" and request.form.get("acao") == "guardar_registo":
        # DATA: yyyy-mm-dd (input type="date") => dd/mm/yyyy
        data_form = (request.form.get("data", "") or "").strip()
        if data_form:
            try:
                registo["data"] = datetime.strptime(data_form, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                registo["data"] = date.today().strftime("%d/%m/%Y")
        else:
            registo["data"] = date.today().strftime("%d/%m/%Y")

        # Período (se vier vazio -> automático)
        periodo = (request.form.get("periodo", "") or "").strip()
        registo["periodo"] = periodo or periodo_atual()

        # Viatura / OUTRA
        viatura_escolhida = (request.form.get("viatura", "") or "").strip()
        outra_viatura = (request.form.get("outra_viatura", "") or "").strip()

        if viatura_escolhida == "OUTRA" and outra_viatura:
            registo["viatura"] = outra_viatura
        else:
            registo["viatura"] = viatura_escolhida

        registo["num_ordem_cct"] = (request.form.get("num_ordem_cct", "") or "").strip()
        registo["num_ordem_pm"] = (request.form.get("num_ordem_pm", "") or "").strip()

        # Só libera ocorrências se TODOS os campos obrigatórios estiverem preenchidos
        data_ok = bool((registo.get("data") or "").strip())
        periodo_ok = bool((registo.get("periodo") or "").strip())
        viatura_ok = bool((registo.get("viatura") or "").strip())
        cct_ok = bool((registo.get("num_ordem_cct") or "").strip())
        pm_ok = bool((registo.get("num_ordem_pm") or "").strip())
        registo["registo_guardado"] = all([data_ok, periodo_ok, viatura_ok, cct_ok, pm_ok])

        dados["registo_principal"] = registo
        guardar_dados(dados)
        return redirect(url_for("index"))

    # Converter data armazenada (dd/mm/aaaa) => yyyy-mm-dd p/ input date
    try:
        data_iso = datetime.strptime(registo.get("data", ""), "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        data_iso = date.today().strftime("%Y-%m-%d")

    # MOSTRAR APENAS OCORRÊNCIAS DO SERVIÇO ATUAL
    ocorrencias = ordenar_ocorrencias(ocorrencias_do_servico(dados, registo))

    return render_template(
        "index.html",
        registo=registo,
        ocorrencias=ocorrencias,
        viaturas=viaturas,
        data_iso=data_iso,
        tipos_ocorrencia=[
            "Multas em corredor BUS",
            "Multas em áreas de paragem",
            "Multas a dificultar manobra",
            "Multa – outras situações",
            "Pedidos de reboque",
            "Pedidos de bloqueamento",
            "Advertências",
            "Observações gerais",
        ]
    )


@app.route("/ocorrencias/nova", methods=["GET", "POST"])
def nova_ocorrencia():
    dados = carregar_dados()
    registo = dados["registo_principal"]

    # Só deixa criar ocorrências se o registo principal estiver guardado
    if not registo.get("registo_guardado"):
        return redirect(url_for("index"))

    if request.method == "GET":
        tipo = request.args.get("tipo", "Ocorrência")
        agora = datetime.now()
        data_str = agora.strftime("%d/%m/%Y")
        hora_str = agora.strftime("%H:%M")
        return render_template(
            "nova_ocorrencia.html",
            tipo=tipo,
            data_ocorr=data_str,
            hora_ocorr=hora_str
        )

    # POST – guardar ocorrência (já grava logo no JSON único)
    tipo = request.form.get("tipo")
    matricula = (request.form.get("matricula", "") or "").upper().strip()
    descricao = (request.form.get("descricao", "") or "").strip()
    data_ocorr = (request.form.get("data_ocorr", "") or "").strip()
    hora_ocorr = (request.form.get("hora_ocorr", "") or "").strip()
    morada = (request.form.get("morada", "") or "").strip()
    latitude = (request.form.get("latitude", "") or "").strip()
    longitude = (request.form.get("longitude", "") or "").strip()

    # Validações básicas
    if not tipo or not data_ocorr or not hora_ocorr or not matricula or not morada:
        return redirect(url_for("index"))

    key = servico_key_do_registo(registo)

    ocorrencia = {
        "id": proximo_id_ocorrencia(dados),

        "servico_key": key,  # <- mantém separação de serviços

        "data": data_ocorr,
        "hora": hora_ocorr,

        "periodo": registo.get("periodo", ""),
        "viatura": registo.get("viatura", ""),
        "numero_ordem_cct": registo.get("num_ordem_cct", ""),
        "numero_ordem_pm": registo.get("num_ordem_pm", ""),

        "tipo": tipo,
        "matricula": matricula,
        "morada": morada,
        "latitude": latitude,
        "longitude": longitude,
        "descricao": descricao,
    }

    dados["ocorrencias"].append(ocorrencia)
    guardar_dados(dados)
    return redirect(url_for("index"))


@app.route("/ocorrencias/<int:occ_id>")
def detalhe_ocorrencia(occ_id):
    dados = carregar_dados()
    occ = next((o for o in (dados.get("ocorrencias", []) or []) if o.get("id") == occ_id), None)
    if not occ:
        return redirect(url_for("index"))
    registo = dados["registo_principal"]
    return render_template("detalhe_ocorrencia.html", ocorrencia=occ, registo=registo)


@app.route("/ocorrencias/<int:occ_id>/apagar", methods=["POST"])
def apagar_ocorrencia(occ_id):
    """
    Apaga globalmente (fica guardado num único JSON, por isso remove da lista única).
    """
    dados = carregar_dados()
    dados["ocorrencias"] = [o for o in (dados.get("ocorrencias", []) or []) if o.get("id") != occ_id]
    guardar_dados(dados)
    return redirect(url_for("index"))


@app.route("/admin/ocorrencias")
def admin_ocorrencias():
    dados = carregar_dados()
    todas = dados.get("ocorrencias", []) or []

    # ordenar DESC no admin (mais recentes em cima)
    def chave(o):
        try:
            d = datetime.strptime(o.get("data", ""), "%d/%m/%Y")
        except Exception:
            d = datetime.min
        try:
            t = datetime.strptime(o.get("hora", "00:00"), "%H:%M").time()
        except Exception:
            t = datetime.strptime("00:00", "%H:%M").time()
        return (d, t)

    todas = sorted(todas, key=chave, reverse=True)
    return render_template("admin_ocorrencias.html", ocorrencias=todas)


@app.route("/admin/ocorrencias/<int:occ_id>/apagar", methods=["POST"])
def admin_apagar_ocorrencia(occ_id):
    dados = carregar_dados()
    dados["ocorrencias"] = [o for o in (dados.get("ocorrencias", []) or []) if o.get("id") != occ_id]
    guardar_dados(dados)
    return redirect(url_for("admin_ocorrencias"))


@app.route("/admin/ocorrencias/<int:occ_id>/editar", methods=["GET", "POST"])
def admin_editar_ocorrencia(occ_id):
    dados = carregar_dados()
    ocorrencias = dados.get("ocorrencias", []) or []
    occ = next((o for o in ocorrencias if o.get("id") == occ_id), None)
    if not occ:
        return redirect(url_for("admin_ocorrencias"))

    if request.method == "GET":
        return render_template("admin_editar_ocorrencia.html", ocorrencia=occ)

    campos = [
        "data", "hora", "periodo", "viatura",
        "numero_ordem_cct", "numero_ordem_pm",
        "tipo", "matricula", "morada",
        "latitude", "longitude", "descricao"
    ]

    for c in campos:
        val = (request.form.get(c, "") or "").strip()
        if c == "matricula":
            val = val.upper()
        occ[c] = val

    # não altero servico_key aqui (pode ser útil para manter “serviço”)
    guardar_dados(dados)
    return redirect(url_for("admin_ocorrencias"))


@app.route("/fim_servico", methods=["POST"])
def fim_servico():
    """
    Exporta CSV APENAS das ocorrências do serviço atual,
    mas NÃO apaga as ocorrências do JSON (porque agora queremos manter tudo guardado).
    """
    dados = carregar_dados()
    registo = dados["registo_principal"]

    occs_servico = ocorrencias_do_servico(dados, registo)

    output = io.StringIO()
    header = [
        "data", "hora", "periodo", "viatura", "numero_ordem_cct",
        "numero_ordem_pm", "tipo_ocorrencia", "matricula",
        "morada_completa", "latitude", "longitude", "descricao"
    ]
    output.write(";".join(header) + "\n")

    for o in occs_servico:
        morada = (o.get("morada", "") or "").replace("\n", " ").replace(";", ",")
        descricao = (o.get("descricao", "") or "").replace("\n", " ").replace(";", ",")

        linha = [
            o.get("data", registo.get("data", "")),
            o.get("hora", ""),
            o.get("periodo", registo.get("periodo", "")),
            o.get("viatura", registo.get("viatura", "")),
            o.get("numero_ordem_cct", registo.get("num_ordem_cct", "")),
            o.get("numero_ordem_pm", registo.get("num_ordem_pm", "")),
            o.get("tipo", ""),
            o.get("matricula", ""),
            morada,
            o.get("latitude", ""),
            o.get("longitude", ""),
            descricao,
        ]
        output.write(";".join(linha) + "\n")

    csv_data = output.getvalue()
    output.close()

    nome_data = (registo.get("data", "") or "").replace("/", "-")
    periodo = registo.get("periodo", "")
    cct = registo.get("num_ordem_cct", "")
    filename = f"Vigilantes_{nome_data}_{periodo}_{cct}.csv"

    # RESET do registo principal para novo serviço (mas mantém ocorrências guardadas)
    dados["registo_principal"] = novo_registo_principal_limpo()
    guardar_dados(dados)

    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
