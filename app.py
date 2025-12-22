{% extends "base.html" %}

{% block title %}Administrador – Sistema de Fiscalização{% endblock %}

{% block content %}

<div class="main-form-card mb-4">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <div class="main-form-title mb-0">Administrador</div>
    <a href="{{ url_for('index') }}" class="btn btn-outline-secondary btn-sm">Voltar</a>
  </div>

  <form method="get" class="row g-3">
    <div class="col-12 col-md-3">
      <label class="section-label mb-1">Data (de)</label>
      <input type="date" class="form-control" name="data_de" value="{{ filtros.data_de }}">
    </div>

    <div class="col-12 col-md-3">
      <label class="section-label mb-1">Data (até)</label>
      <input type="date" class="form-control" name="data_ate" value="{{ filtros.data_ate }}">
    </div>

    <div class="col-12 col-md-2">
      <label class="section-label mb-1">Período</label>
      <select class="form-select" name="periodo">
        <option value="">Todos</option>
        <option value="Manhã" {% if filtros.periodo == "Manhã" %}selected{% endif %}>Manhã</option>
        <option value="Tarde" {% if filtros.periodo == "Tarde" %}selected{% endif %}>Tarde</option>
      </select>
    </div>

    <div class="col-12 col-md-4">
      <label class="section-label mb-1">Viatura</label>
      <select class="form-select" name="viatura">
        <option value="">Todas</option>
        {% for v in viaturas %}
          <option value="{{ v }}" {% if filtros.viatura == v %}selected{% endif %}>{{ v }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="col-12 col-md-3">
      <label class="section-label mb-1">Nº Ordem CCT</label>
      <input type="text" class="form-control" name="cct" value="{{ filtros.cct }}" placeholder="ex: 190497">
    </div>

    <div class="col-12 col-md-3">
      <label class="section-label mb-1">Nº PM</label>
      <input type="text" class="form-control" name="pm" value="{{ filtros.pm }}" placeholder="ex: 123456">
    </div>

    <div class="col-12 col-md-3">
      <label class="section-label mb-1">Tipo de ocorrência</label>
      <select class="form-select" name="tipo">
        <option value="">Todos</option>
        {% for t in tipos %}
          <option value="{{ t }}" {% if filtros.tipo == t %}selected{% endif %}>{{ t }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="col-12 col-md-3">
      <label class="section-label mb-1">Matrícula</label>
      <input type="text" class="form-control" name="matricula" value="{{ filtros.matricula }}" placeholder="contém...">
    </div>

    <div class="col-12">
      <label class="section-label mb-1">Pesquisa livre</label>
      <input type="text" class="form-control" name="q" value="{{ filtros.q }}" placeholder="morada, descrição, matrícula, etc.">
    </div>

    <div class="col-12 d-flex gap-2 justify-content-end">
      <a href="{{ url_for('admin') }}" class="btn btn-outline-secondary">Limpar</a>
      <button type="submit" class="btn btn-guardar">Aplicar filtros</button>
    </div>
  </form>
</div>

<div class="card">
  <div class="card-body">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h5 class="mb-0">Registos</h5>
      <div class="text-muted small">Total: {{ ocorrencias|length }}</div>
    </div>

    {% if ocorrencias %}
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead>
            <tr>
              <th>data</th>
              <th>hora</th>
              <th>periodo</th>
              <th>viatura</th>
              <th>numero_ordem_cct</th>
              <th>numero_ordem_pm</th>
              <th>tipo_ocorrencia</th>
              <th>matricula</th>
              <th>morada_completa</th>
              <th>latitude</th>
              <th>longitude</th>
              <th>descricao</th>
            </tr>
          </thead>
          <tbody>
            {% for o in ocorrencias %}
              <tr>
                <td>{{ o.data }}</td>
                <td>{{ o.hora }}</td>
                <td>{{ o.periodo }}</td>
                <td>{{ o.viatura }}</td>
                <td>{{ o.numero_ordem_cct }}</td>
                <td>{{ o.numero_ordem_pm }}</td>
                <td>{{ o.tipo_ocorrencia }}</td>
                <td>{{ o.matricula }}</td>
                <td style="min-width:240px;">{{ o.morada_completa }}</td>
                <td>{{ o.latitude }}</td>
                <td>{{ o.longitude }}</td>
                <td style="min-width:240px;">{{ o.descricao }}</td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    {% else %}
      <div class="alert alert-secondary mb-0">Sem registos para os filtros actuais.</div>
    {% endif %}
  </div>
</div>

{% endblock %}
