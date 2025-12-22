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
#  HELPERS
# =========================

def parse_ddmmyyyy(s):
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        return None


def contains(hay, needle):
    return needle.lower() in (hay or "").lower()


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
        data_form = request.form.get("data", "").strip()
        if data_form:
            try:
                registo["data"] = datetime.strptime(data_form, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                pass

        registo["periodo"] = request.form.get("periodo", "Manhã")

        viatura_escolhida = request.form.get("viatura", "").strip()
        outra_viatura = request.form.get("outra_viatura", "").strip()

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

    try:
        data_iso = datetime.strptime(registo.get("data", ""), "%d/%m/%Y").strftime("%Y-%m-%d")
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

    tipo = request.form.get("tipo")
    matricula = request.form.get("matricula", "").upper().strip()
    descricao = request.form.get("descricao", "").strip()
    data_ocorr = request.form.get("data_ocorr", "").strip()
    hora_ocorr = request.form.get("hora_ocorr", "").strip()
    morada = request.form.get("morada", "").strip()
    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()

    # Obriga matrícula e morada
    if (not tipo or not data_ocorr or not hora_ocorr or not matricula or not morada):
        return redirect(url_for("index"))

    # ✅ Guardar também os dados do registo principal na ocorrência
    ocorrencia = {
        "id": proximo_id_ocorrencia(dados),

        # ordem pedida (a tabela no admin vai usar estes campos)
        "data": data_ocorr,
        "hora": hora_ocorr,
        "periodo": registo.get("periodo", ""),
        "viatura": registo.get("viatura", ""),
        "numero_ordem_cct": registo.get("num_ordem_cct", ""),
        "numero_ordem_pm": registo.get("num_ordem_pm", ""),

        "tipo_ocorrencia": tipo,
        "matricula": matricula,
        "morada_completa": morada,
        "latitude": latitude,
        "longitude": longitude,
        "descricao": descricao,
    }

    dados["ocorrencias"].append(ocorrencia)
    guardar_dados(dados)
    return redirect(url_for("index"))


@app.route("/admin", methods=["GET"])
def admin():
    dados = carregar_dados()
    ocorrencias = dados.get("ocorrencias", [])

    # filtros (GET)
    data_de = request.args.get("data_de", "").strip()     # yyyy-mm-dd
    data_ate = request.args.get("data_ate", "").strip()   # yyyy-mm-dd
    periodo = request.args.get("periodo", "").strip()
    viatura = request.args.get("viatura", "").strip()
    cct = request.args.get("cct", "").strip()
    pm = request.args.get("pm", "").strip()
    tipo = request.args.get("tipo", "").strip()
    matricula = request.args.get("matricula", "").strip()
    q = request.args.get("q", "").strip()

    d_de = None
    d_ate = None
    try:
        if data_de:
            d_de = datetime.strptime(data_de, "%Y-%m-%d").date()
        if data_ate:
            d_ate = datetime.strptime(data_ate, "%Y-%m-%d").date()
    except Exception:
        d_de, d_ate = None, None

    filtradas = []
    for o in ocorrencias:
        ok = True

        d_o = parse_ddmmyyyy(o.get("data", ""))
        if d_de and (not d_o or d_o < d_de):
            ok = False
        if d_ate and (not d_o or d_o > d_ate):
            ok = False

        if periodo and o.get("periodo") != periodo:
            ok = False
        if viatura and o.get("viatura") != viatura:
            ok = False
        if cct and o.get("numero_ordem_cct") != cct:
            ok = False
        if pm and o.get("numero_ordem_pm") != pm:
            ok = False
        if tipo and o.get("tipo_ocorrencia") != tipo:
            ok = False
        if matricula and not contains(o.get("matricula", ""), matricula):
            ok = False

        if q:
            blob = " ".join([
                str(o.get("data","")),
                str(o.get("hora","")),
                str(o.get("periodo","")),
                str(o.get("viatura","")),
                str(o.get("numero_ordem_cct","")),
                str(o.get("numero_ordem_pm","")),
                str(o.get("tipo_ocorrencia","")),
                str(o.get("matricula","")),
                str(o.get("morada_completa","")),
                str(o.get("latitude","")),
                str(o.get("longitude","")),
                str(o.get("descricao","")),
            ])
            if not contains(blob, q):
                ok = False

        if ok:
            filtradas.append(o)

    filtradas.sort(key=lambda x: (x.get("data", ""), x.get("hora", "")))

    # listas para dropdown
    tipos = sorted({o.get("tipo_ocorrencia","") for o in ocorrencias if o.get("tipo_ocorrencia")})
    viaturas = sorted({o.get("viatura","") for o in ocorrencias if o.get("viatura")})

    return render_template(
        "admin.html",
        ocorrencias=filtradas,
        tipos=tipos,
        viaturas=viaturas,
        filtros={
            "data_de": data_de,
            "data_ate": data_ate,
            "periodo": periodo,
            "viatura": viatura,
            "cct": cct,
            "pm": pm,
            "tipo": tipo,
            "matricula": matricula,
            "q": q,
        }
    )


@app.route("/fim_servico", methods=["POST"])
def fim_servico():
    dados = carregar_dados()
    registo = dados["registo_principal"]
    ocorrencias = dados.get("ocorrencias", [])

    output = io.StringIO()
    header = [
        "data","hora","periodo","viatura","numero_ordem_cct","numero_ordem_pm",
        "tipo_ocorrencia","matricula","morada_completa","latitude","longitude","descricao"
    ]
    output.write(";".join(header) + "\n")

    for o in ocorrencias:
        morada = (o.get("morada_completa", "") or "").replace("\n", " ").replace(";", ",")
        descricao = (o.get("descricao", "") or "").replace("\n", " ").replace(";", ",")

        linha = [
            o.get("data", ""),
            o.get("hora", ""),
            o.get("periodo", ""),
            o.get("viatura", ""),
            o.get("numero_ordem_cct", ""),
            o.get("numero_ordem_pm", ""),
            o.get("tipo_ocorrencia", ""),
            o.get("matricula", ""),
            morada,
            o.get("latitude", ""),
            o.get("longitude", ""),
            descricao,
        ]
        output.write(";".join(linha) + "\n")

    csv_data = output.getvalue()
    output.close()

    nome_data = registo.get("data", "").replace("/", "-")
    periodo = registo.get("periodo", "")
    cct = registo.get("num_ordem_cct", "")
    filename = f"Vigilantes_{nome_data}_{periodo}_{cct}.csv"

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
