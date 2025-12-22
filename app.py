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


def _estrutura_inicial():
    return {
        "registo_principal": {
            "data": date.today().strftime("%d/%m/%Y"),
            "periodo": "Manhã",
            "viatura": "",
            "num_ordem_cct": "",
            "num_ordem_pm": "",
            "registo_guardado": False,
        },
        "ocorrencias": [],
        # ✅ NOVO: histórico persistente de todas as ocorrências (todas as sessões)
        "historico_ocorrencias": []
    }


def carregar_dados():
    path = get_data_path()
    if not os.path.exists(path):
        return _estrutura_inicial()

    try:
        with open(path, "r", encoding="utf-8") as f:
            dados = json.load(f)

        # ✅ garantir chaves novas mesmo em ficheiros antigos
        if "historico_ocorrencias" not in dados:
            dados["historico_ocorrencias"] = []
        if "ocorrencias" not in dados:
            dados["ocorrencias"] = []
        if "registo_principal" not in dados:
            dados["registo_principal"] = _estrutura_inicial()["registo_principal"]

        return dados
    except Exception:
        return _estrutura_inicial()


def guardar_dados(dados):
    path = get_data_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def proximo_id_ocorrencia(dados):
    # ✅ id global com base em histórico + atuais
    todos = (dados.get("historico_ocorrencias", []) or []) + (dados.get("ocorrencias", []) or [])
    if not todos:
        return 1
    return max(o.get("id", 0) for o in todos) + 1


def obter_todas_ocorrencias(dados):
    """
    ✅ devolve TODAS as ocorrências (histórico + atuais) num formato uniforme
    já com os campos pedidos (data/hora/período/viatura/números/...).
    """
    hist = dados.get("historico_ocorrencias", []) or []
    atuais = dados.get("ocorrencias", []) or []

    # garantir que as atuais também aparecem no admin
    todas = hist + atuais

    def chave_ordenacao(o):
        # data dd/mm/yyyy + hora HH:MM
        try:
            d = datetime.strptime(o.get("data", ""), "%d/%m/%Y")
        except Exception:
            d = datetime.min
        try:
            h = datetime.strptime(o.get("hora", "00:00"), "%H:%M").time()
        except Exception:
            h = datetime.strptime("00:00", "%H:%M").time()
        return (d, h)

    todas_ordenadas = sorted(todas, key=chave_ordenacao, reverse=True)
    return todas_ordenadas


# =========================
#  ROTAS
# =========================

@app.route("/", methods=["GET", "POST"])
def index():
    dados = carregar_dados()
    registo = dados["registo_principal"]

    ocorrencias = sorted(
        dados.get("ocorrencias", []),
        key=lambda o: (o.get("data", ""), o.get("hora", "")),
        reverse=False
    )

    viaturas = carregar_viaturas()

    if request.method == "POST" and request.form.get("acao") == "guardar_registo":
        # === DATA: vem em formato yyyy-mm-dd do input type="date" ===
        data_form = request.form.get("data", "").strip()
        if data_form:
            try:
                registo["data"] = datetime.strptime(
                    data_form, "%Y-%m-%d"
                ).strftime("%d/%m/%Y")
            except ValueError:
                pass

        # Período
        registo["periodo"] = request.form.get("periodo", "Manhã")

        # --- Tratamento especial da viatura / OUTRA ---
        viatura_escolhida = request.form.get("viatura", "").strip()
        outra_viatura = request.form.get("outra_viatura", "").strip()

        # ✅ FIX: havia um bug "outra_viicula" (NameError). Corrigido.
        if viatura_escolhida == "OUTRA" and outra_viatura:
            registo["viatura"] = outra_viatura
        else:
            registo["viatura"] = viatura_escolhida

        registo["num_ordem_cct"] = request.form.get("num_ordem_cct", "").strip()
        registo["num_ordem_pm"] = request.form.get("num_ordem_pm", "").strip()
        registo["registo_guardado"] = True

        dados["registo_principal"] = registo
        guardar_dados(dados)
        return redirect(url_for("index"))

    # ==== Converter a data armazenada (dd/mm/aaaa) para yyyy-mm-dd para o input ====
    try:
        data_iso = datetime.strptime(
            registo.get("data", ""), "%d/%m/%Y"
        ).strftime("%Y-%m-%d")
    except Exception:
        data_iso = date.today().strftime("%Y-%m-%d")

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

    # POST – guardar ocorrência
    tipo = request.form.get("tipo")
    matricula = request.form.get("matricula", "").upper().strip()
    descricao = request.form.get("descricao", "").strip()
    data_ocorr = request.form.get("data_ocorr", "").strip()
    hora_ocorr = request.form.get("hora_ocorr", "").strip()
    morada = request.form.get("morada", "").strip()
    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()

    # Validações básicas
    if (
        not tipo
        or not data_ocorr
        or not hora_ocorr
        or not matricula
        or not morada
    ):
        return redirect(url_for("index"))

    # ✅ NOVO: guardar também os dados do registo principal DENTRO da ocorrência
    # para o admin ter todos os campos (mesmo depois do fim_servico/reset).
    ocorrencia = {
        "id": proximo_id_ocorrencia(dados),

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
    ocorrencias = dados.get("ocorrencias", [])
    occ = next((o for o in ocorrencias if o.get("id") == occ_id), None)
    if not occ:
        return redirect(url_for("index"))
    registo = dados["registo_principal"]
    return render_template("detalhe_ocorrencia.html", ocorrencia=occ, registo=registo)


@app.route("/ocorrencias/<int:occ_id>/apagar", methods=["POST"])
def apagar_ocorrencia(occ_id):
    dados = carregar_dados()
    ocorrencias = dados.get("ocorrencias", [])
    ocorrencias = [o for o in ocorrencias if o.get("id") != occ_id]
    dados["ocorrencias"] = ocorrencias
    guardar_dados(dados)
    return redirect(url_for("index"))


# =========================
#  ✅ ADMIN - LISTA COMPLETA COM FILTROS
# =========================
@app.route("/admin/ocorrencias")
def admin_ocorrencias():
    dados = carregar_dados()
    todas = obter_todas_ocorrencias(dados)
    return render_template("admin_ocorrencias.html", ocorrencias=todas)


@app.route("/fim_servico", methods=["POST"])
def fim_servico():
    dados = carregar_dados()
    registo = dados["registo_principal"]
    ocorrencias = dados.get("ocorrencias", [])

    # Gerar CSV em memória
    output = io.StringIO()

    header = [
        "data", "hora", "periodo", "viatura", "numero_ordem_cct",
        "numero_ordem_pm", "tipo_ocorrencia", "matricula",
        "morada_completa", "latitude", "longitude", "descricao"
    ]
    output.write(";".join(header) + "\n")

    for o in ocorrencias:
        morada = (o.get("morada", "") or "").replace("\n", " ").replace(";", ",")
        descricao = (o.get("descricao", "") or "").replace("\n", " ").replace(";", ",")

        # ✅ usar campos guardados na ocorrência (se existirem) para ser consistente
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

    # Criar nome do ficheiro conforme pedido
    nome_data = registo.get("data", "").replace("/", "-")
    periodo = registo.get("periodo", "")
    cct = registo.get("num_ordem_cct", "")
    filename = f"Vigilantes_{nome_data}_{periodo}_{cct}.csv"

    # ✅ NOVO: antes de limpar, mover as ocorrências atuais para o histórico
    if ocorrencias:
        dados["historico_ocorrencias"].extend(ocorrencias)

    # Limpar registos para novo serviço
    dados["registo_principal"]["registo_guardado"] = False
    dados["ocorrencias"] = []
    guardar_dados(dados)

    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
