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


def carregar_dados():
    path = get_data_path()
    if not os.path.exists(path):
        return {
            "registo_principal": {
                "data": date.today().strftime("%d/%m/%Y"),
                "periodo": "Manhã",
                "viatura": "",
                "num_ordem_cct": "",
                "num_ordem_pm": "",
                "registo_guardado": False,
            },
            "ocorrencias": []
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Em caso de erro, começa de novo
        return {
            "registo_principal": {
                "data": date.today().strftime("%d/%m/%Y"),
                "periodo": "Manhã",
                "viatura": "",
                "num_ordem_cct": "",
                "num_ordem_pm": "",
                "registo_guardado": False,
            },
            "ocorrencias": []
        }


def guardar_dados(dados):
    path = get_data_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def proximo_id_ocorrencia(dados):
    ocorrencias = dados.get("ocorrencias", [])
    if not ocorrencias:
        return 1
    return max(o.get("id", 0) for o in ocorrencias) + 1


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

    viaturas = carregar_viaturas()  # lista dinâmica de viaturas

    if request.method == "POST" and request.form.get("acao") == "guardar_registo":
        # === DATA: vem em formato yyyy-mm-dd do input type="date" ===
        data_form = request.form.get("data", "").strip()
        if data_form:
            try:
                # guarda no JSON em dd/mm/aaaa
                registo["data"] = datetime.strptime(
                    data_form, "%Y-%m-%d"
                ).strftime("%d/%m/%Y")
            except ValueError:
                # se der erro, mantém a que já lá estava
                pass

        # Período
        registo["periodo"] = request.form.get("periodo", "Manhã")

        # --- Tratamento especial da viatura / OUTRA ---
        viatura_escolhida = request.form.get("viatura", "").strip()
        outra_viatura = request.form.get("outra_viatura", "").strip()

        if viatura_escolhida == "OUTRA" and outra_viatura:
            registo["viatura"] = outra_viicula
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

    # Validações básicas (agora também obriga matrícula e morada)
    if (
        not tipo
        or not data_ocorr
        or not hora_ocorr
        or not matricula
        or not morada
    ):
        return redirect(url_for("index"))

    ocorrencia = {
        "id": proximo_id_ocorrencia(dados),
        "tipo": tipo,
        "matricula": matricula,
        "descricao": descricao,
        "data": data_ocorr,
        "hora": hora_ocorr,
        "morada": morada,
        "latitude": latitude,
        "longitude": longitude,
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


@app.route("/fim_servico", methods=["POST"])
def fim_servico():
    dados = carregar_dados()
    registo = dados["registo_principal"]
    ocorrencias = dados.get("ocorrencias", [])

    # Gerar CSV em memória
    output = io.StringIO()

    header = [
        "data","hora","periodo","viatura","numero_ordem_cct",
        "numero_ordem_pm","tipo_ocorrencia","matricula",
        "morada_completa","latitude","longitude","descricao"
    ]
    output.write(";".join(header) + "\n")

    for o in ocorrencias:
        morada = (o.get("morada", "") or "").replace("\n", " ").replace(";", ",")
        descricao = (o.get("descricao", "") or "").replace("\n", " ").replace(";", ",")

        linha = [
            registo.get("data", ""),
            o.get("hora", ""),
            registo.get("periodo", ""),
            registo.get("viatura", ""),
            registo.get("num_ordem_cct", ""),
            registo.get("num_ordem_pm", ""),
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
    nome_data   = registo.get("data","").replace("/", "-")
    periodo     = registo.get("periodo","")
    cct         = registo.get("num_ordem_cct","")
    filename    = f"Vigilantes_{nome_data}_{periodo}_{cct}.csv"

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
