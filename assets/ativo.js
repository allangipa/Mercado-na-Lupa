/* Mercado na Lupa — página de ativo (copiado para assets/ativo.js pelo build).
   Sem biblioteca: gráfico de preço, comparação com índices, simulador, barras de
   dividendos, tabelas com "ver todas" e ordenação, compartilhar e favoritar.
   Os dados vêm de assets/serie/<ativo>.json e assets/serie/_ref.json, sob demanda. */
(function () {
  'use strict';
  var D = 864e5, M = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  var BASE = '../assets/serie/';
  function br(v, c) { return v.toLocaleString('pt-BR', { minimumFractionDigits: c, maximumFractionDigits: c }); }
  function pc(v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + br(Math.abs(v), 1) + '%'; }
  function iso(t) { return new Date(t).toISOString().slice(0, 10); }
  function dbr(t) { var s = iso(t); return s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4); }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
  var cache = {};
  function pega(nome) {
    if (!cache[nome]) cache[nome] = fetch(BASE + nome + '.json').then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    return cache[nome];
  }
  function abre(j) { // {d0, s:[gap, close, ...]} -> [[t, v]]
    var t = Date.parse(j.d0 + 'T00:00:00Z'), out = [];
    for (var i = 0; i < j.s.length; i += 2) { t += j.s[i] * D; out.push([t, j.s[i + 1]]); }
    return out;
  }
  function ajusta(rows, fatores) { // fatores [[iso, f]]: multiplica os preços ANTES de cada data por f
    if (!fatores || !fatores.length) return rows;
    var fs = fatores.map(function (x) { return [Date.parse(x[0] + 'T00:00:00Z'), x[1]]; }).sort(function (a, b) { return a[0] - b[0]; });
    var out = new Array(rows.length), k = fs.length - 1, acc = 1;
    for (var i = rows.length - 1; i >= 0; i--) {
      while (k >= 0 && fs[k][0] > rows[i][0]) { acc *= fs[k][1]; k--; }
      out[i] = [rows[i][0], rows[i][1] * acc];
    }
    return out;
  }
  function passo(a) { if (a <= 0) return 1; var b = a / 4, m = Math.pow(10, Math.floor(Math.log10(b))), k = [1, 2, 2.5, 5, 10]; for (var i = 0; i < k.length; i++) if (b <= k[i] * m) return k[i] * m; return 10 * m; }

  // desenho genérico: linhas [{p:[[t,v]], cl, rot}], fmt do eixo y
  function svg(linhas, fmtY, titulo) {
    var W = 720, H = 330, x0 = 70, x1 = 640, y0 = 16, y1 = 282, t0 = Infinity, t1 = -Infinity, lo = Infinity, hi = -Infinity;
    linhas.forEach(function (l) { l.p.forEach(function (q) { t0 = Math.min(t0, q[0]); t1 = Math.max(t1, q[0]); lo = Math.min(lo, q[1]); hi = Math.max(hi, q[1]); }); });
    if (!isFinite(t0)) return '<p class="sem-js">Sem dados no período.</p>';
    if (t1 === t0) t1 = t0 + D;
    var p = passo(hi - lo), a = Math.floor(lo / p) * p, b = Math.ceil(hi / p) * p; if (b === a) b = a + p;
    var X = function (t) { return x0 + (x1 - x0) * (t - t0) / (t1 - t0); }, Y = function (v) { return y1 - (y1 - y0) * (v - a) / (b - a); };
    var g = [], c = p < 1 ? 2 : (p < 10 && p !== Math.floor(p) ? 1 : 0);
    for (var y = a; y <= b + 1e-9; y += p) { var yy = Y(y).toFixed(1); g.push('<line class="grade-y" x1="' + x0 + '" x2="' + x1 + '" y1="' + yy + '" y2="' + yy + '"/><text x="' + (x0 - 8) + '" y="' + (+yy + 6).toFixed(1) + '" text-anchor="end">' + fmtY(y, c) + '</text>'); }
    var dias = (t1 - t0) / D, xs = [], ult = -1;
    var dt0 = new Date(t0), cur = Date.UTC(dt0.getUTCFullYear(), dt0.getUTCMonth() + 1, 1);
    var salto = dias > 1100 ? 12 : dias > 500 ? 6 : dias > 200 ? 2 : 1;
    if (dias <= 45) { for (var k = 0; k <= 4; k++) { var tt = t0 + (t1 - t0) * k / 4; xs.push([tt, iso(tt).slice(8, 10) + '/' + iso(tt).slice(5, 7)]); } }
    else while (cur <= t1) { var d = new Date(cur), m = d.getUTCMonth(); if (m % salto === 0 || salto === 1) xs.push([cur, salto >= 12 ? String(d.getUTCFullYear()) : M[m] + (m === 0 || salto >= 6 ? '/' + String(d.getUTCFullYear()).slice(2) : '')]); cur = Date.UTC(d.getUTCFullYear(), m + 1, 1); }
    var eixo = xs.map(function (q) { var x = X(q[0]); if (x - ult < 46) return ''; ult = x; return '<text x="' + x.toFixed(1) + '" y="' + (H - 14) + '" text-anchor="middle">' + q[1] + '</text>'; }).join('');
    var corpo = linhas.map(function (l, i) {
      var pts = l.p.map(function (q) { return X(q[0]).toFixed(1) + ',' + Y(q[1]).toFixed(1); }).join(' ');
      var u = l.p[l.p.length - 1], area = (linhas.length === 1) ? '<path class="area" d="M' + X(l.p[0][0]).toFixed(1) + ',' + y1 + ' L' + pts.split(' ').join(' L') + ' L' + X(u[0]).toFixed(1) + ',' + y1 + ' Z"/>' : '';
      return area + '<polyline class="linha ' + l.cl + '" points="' + pts + '"/><circle class="ponto ' + l.cl + '" cx="' + X(u[0]).toFixed(1) + '" cy="' + Y(u[1]).toFixed(1) + '" r="5"/>' +
        (l.rot ? '<text class="rot-fim ' + l.cl + '" x="' + (X(u[0]) + 9).toFixed(1) + '" y="' + (Y(u[1]) + 6).toFixed(1) + '">' + esc(l.rot) + '</text>' : '');
    }).join('');
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(titulo) + '"><title>' + esc(titulo) + '</title>' + g.join('') + corpo + eixo + '</svg>';
  }
  function corte(rows, ini) { var r = rows.filter(function (q) { return q[0] >= ini; }); return r; }
  function inicioPeriodo(fim, per) {
    var d = new Date(fim);
    if (per === '7D') return fim - 7 * D; if (per === '30D') return fim - 30 * D;
    if (per === '6M') return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 6, d.getUTCDate());
    if (per === 'YTD') return Date.UTC(d.getUTCFullYear(), 0, 1);
    var n = parseInt(per, 10); return Date.UTC(d.getUTCFullYear() - n, d.getUTCMonth(), d.getUTCDate());
  }
  function base100(rows) { var b = rows.length ? rows[0][1] : 1; return rows.map(function (q) { return [q[0], q[1] / b * 100]; }); }

  // ---------- gráfico de preço ----------
  function grafico(G) {
    var slug = G.getAttribute('data-slug'), cod = G.getAttribute('data-cod'), area = G.querySelector('.graf-area');
    var est = { per: '1A', aj: false, outro: null };
    pega(slug).then(function (j) {
      var real = abre(j), comSp = ajusta(real, j.sp), ajust = j.aj ? ajusta(comSp, j.aj) : null, fim = real[real.length - 1][0];
      var pers = ['7D', '30D', '6M', 'YTD', '1A', '2A', '3A', '5A'].filter(function (p) { return p.slice(-1) !== 'A' || inicioPeriodo(fim, p) >= real[0][0] - 10 * D; });
      if (pers.indexOf('1A') < 0) est.per = pers[pers.length - 1];
      var bp = G.querySelector('.per');
      bp.innerHTML = pers.map(function (p) { return '<button type="button" data-p="' + p + '" aria-pressed="' + (p === est.per) + '">' + p + '</button>'; }).join('');
      if (ajust) G.querySelector('.aj').hidden = false;
      function desenha() {
        var ini = inicioPeriodo(fim, est.per), base = est.aj ? ajust : real, rs = corte(base, ini);
        if (est.outro) {
          var mine = base100(corte(est.aj ? ajust : comSp, ini));
          var o = est.outro, os = base100(corte(o.rows, Math.max(ini, mine.length ? mine[0][0] : ini)));
          area.innerHTML = svg([{ p: mine, cl: 's0', rot: cod }, { p: os, cl: 's1', rot: o.cod }], function (v, c) { return br(v, c); },
            cod + ' e ' + o.cod + ', base 100 no início do período');
        } else {
          area.innerHTML = svg([{ p: rs, cl: 's0' }], function (v, c) { return br(v, c); },
            cod + ': fechamento diário' + (est.aj ? ' ajustado' : '') + ' de ' + dbr(rs[0][0]) + ' a ' + dbr(rs[rs.length - 1][0]) + ', em reais');
        }
      }
      bp.addEventListener('click', function (ev) { var b = ev.target.closest('button'); if (!b) return; est.per = b.getAttribute('data-p'); bp.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', x === b); }); desenha(); });
      G.querySelector('.aj').addEventListener('click', function (ev) { var b = ev.target.closest('button'); if (!b) return; est.aj = b.getAttribute('data-aj') === '1'; G.querySelectorAll('.aj button').forEach(function (x) { x.setAttribute('aria-pressed', x === b); }); desenha(); });
      var sel = G.querySelector('select');
      pega('_ref').then(function (r) { sel.innerHTML = '<option value="">—</option>' + r.lista.filter(function (x) { return x[0] !== cod; }).map(function (x) { return '<option value="' + x[1] + '">' + x[0] + ' — ' + esc(x[2]) + '</option>'; }).join(''); });
      sel.addEventListener('change', function () {
        if (!sel.value) { est.outro = null; desenha(); return; }
        var c = sel.options[sel.selectedIndex].text.split(' — ')[0];
        pega(sel.value).then(function (o) { var r = ajusta(abre(o), o.sp); if (est.aj && o.aj) r = ajusta(r, o.aj); est.outro = { cod: c, rows: r }; desenha(); });
      });
      desenha();
    }).catch(function () { area.innerHTML = '<p class="sem-js">Não foi possível carregar a série agora.</p>'; });
  }

  // ---------- comparação com índices ----------
  var CORES = ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7'];
  function comparacao(C) {
    var slug = C.getAttribute('data-slug'), cod = C.getAttribute('data-cod'), tipo = C.getAttribute('data-tipo');
    var area = C.querySelector('.comp-area'), leg = C.querySelector('.comp-legenda'), res = C.querySelector('.sim-res'), inp = C.querySelector('#sim-valor');
    Promise.all([pega(slug), pega('_ref')]).then(function (v) {
      var j = v[0], r = v[1];
      var ativo = ajusta(ajusta(abre(j), j.sp), j.aj || []), fim = ativo[ativo.length - 1][0];
      var series = [{ id: 'ativo', rot: cod + (j.aj ? ' (com rendimentos)' : ' (só preço)'), on: true, tipo: 'preco', rows: ativo }];
      if (r.cdi) series.push({ id: 'cdi', rot: 'CDI', on: true, tipo: 'cdi' });
      if (r.ipca) series.push({ id: 'ipca', rot: 'IPCA', on: true, tipo: 'ipca' });
      ['BOVA11', 'SMAL11', 'IVVB11', 'XFIX11', 'DIVO11'].forEach(function (e) {
        if (r.etf[e]) series.push({ id: e, rot: e + ' (ETF, ' + r.nomes[e] + ')', on: e === 'BOVA11' || (e === 'XFIX11' && tipo === 'fii'), tipo: 'preco', rows: abre(r.etf[e]) });
      });
      series.forEach(function (s, i) { s.cl = CORES[i % CORES.length]; });
      var cdi = r.cdi ? r.cdi.d.map(function (d, i) { return [Date.parse(d + 'T00:00:00Z'), r.cdi.v[i]]; }) : [];
      var pers = ['1A', '2A', '5A'].filter(function (p) { return inicioPeriodo(fim, p) >= ativo[0][0] - 10 * D; });
      C.querySelectorAll('[data-p]').forEach(function (b) { if (pers.indexOf(b.getAttribute('data-p')) < 0) b.hidden = true; });
      var per = pers[0] || '1A';
      function acumulada(s, datas, ini) {
        if (s.tipo === 'preco') {
          var rs = s.rows, k = 0, out = [], b = null;
          for (var i = 0; i < datas.length; i++) { while (k + 1 < rs.length && rs[k + 1][0] <= datas[i]) k++; if (rs[k][0] > datas[i]) continue; if (b === null) b = rs[k][1]; out.push([datas[i], (rs[k][1] / b - 1) * 100]); }
          return out;
        }
        if (s.tipo === 'cdi') {
          var f = 1, k2 = 0, o2 = [];
          while (k2 < cdi.length && cdi[k2][0] < datas[0]) k2++; // taxa do dia d rende de d para o dia útil seguinte (como a calculadora do BC)
          for (var i2 = 0; i2 < datas.length; i2++) { while (k2 < cdi.length && cdi[k2][0] < datas[i2]) { f *= 1 + cdi[k2][1] / 100; k2++; } o2.push([datas[i2], (f - 1) * 100]); }
          return o2;
        }
        // IPCA: meses completos depois do mês inicial, só os já divulgados
        var m0 = iso(datas[0]).slice(0, 7), o3 = [];
        for (var i3 = 0; i3 < datas.length; i3++) {
          var lim = iso(datas[i3]).slice(0, 7), f3 = 1;
          for (var q = 0; q < r.ipca.m.length; q++) if (r.ipca.m[q] > m0 && r.ipca.m[q] < lim) f3 *= 1 + r.ipca.v[q] / 100;
          o3.push([datas[i3], (f3 - 1) * 100]);
        }
        return o3;
      }
      function desenha() {
        var ini = inicioPeriodo(fim, per), datas = ativo.filter(function (q) { return q[0] >= ini; }).map(function (q) { return q[0]; });
        if (!datas.length) return;
        var vis = series.filter(function (s) { return s.on; }).map(function (s) { return { p: acumulada(s, datas, ini), cl: s.cl, rot: s.id === 'ativo' ? cod : s.id === 'cdi' ? 'CDI' : s.id === 'ipca' ? 'IPCA' : s.id, s: s }; })
          .filter(function (l) { return l.p.length; });
        area.innerHTML = svg(vis, function (v, c) { return br(v, c) + '%'; }, 'Rentabilidade acumulada de ' + dbr(datas[0]) + ' a ' + dbr(datas[datas.length - 1]));
        C.querySelector('.sim-per').textContent = 'em ' + dbr(datas[0]);
        var valor = parseFloat(String(inp.value).replace(/\./g, '').replace(',', '.')) || 0;
        res.innerHTML = vis.map(function (l) { var u = l.p[l.p.length - 1][1]; return '<li><span class="marca-serie ' + l.cl + '" aria-hidden="true"></span>' + esc(l.s.rot) + ': <strong class="num">R$ ' + br(valor * (1 + u / 100), 2) + '</strong> <span class="num">(' + pc(u) + ')</span></li>'; }).join('');
      }
      leg.innerHTML = series.map(function (s, i) { return '<button type="button" data-i="' + i + '" aria-pressed="' + s.on + '"><span class="marca-serie ' + s.cl + '" aria-hidden="true"></span>' + esc(s.rot) + '</button>'; }).join('');
      leg.addEventListener('click', function (ev) { var b = ev.target.closest('button'); if (!b) return; var s = series[+b.getAttribute('data-i')]; s.on = !s.on; b.setAttribute('aria-pressed', s.on); desenha(); });
      C.querySelector('.graf-ctl .botoes').addEventListener('click', function (ev) { var b = ev.target.closest('button'); if (!b) return; per = b.getAttribute('data-p'); C.querySelectorAll('[data-p]').forEach(function (x) { x.setAttribute('aria-pressed', x === b); }); desenha(); });
      C.querySelectorAll('[data-p]').forEach(function (x) { x.setAttribute('aria-pressed', x.getAttribute('data-p') === per); });
      inp.addEventListener('input', desenha);
      desenha();
    }).catch(function () { area.innerHTML = '<p class="sem-js">Não foi possível carregar as séries agora.</p>'; });
  }

  // ---------- barras de dividendos ----------
  function barras(B) {
    var dados = JSON.parse(B.querySelector('.div-dados').textContent), alvo = B.querySelector('.div-barras'), unid = B.getAttribute('data-unid');
    var est = { med: 'dy', per: 5 };
    function desenha() {
      var xs = dados.slice(), so12 = xs.length && xs[xs.length - 1][0] === 'Últ. 12M' ? xs.pop() : null;
      if (est.per) xs = xs.slice(-est.per); if (so12) xs.push(so12);
      var idx = est.med === 'dy' ? 2 : 1, vals = xs.map(function (x) { return x[idx]; }), mx = Math.max.apply(0, vals.filter(function (v) { return v !== null; }).concat([0]));
      if (!mx) { alvo.innerHTML = '<p class="data-regra">Sem valores para esta medida no período.</p>'; return; }
      var W = 720, H = 260, n = xs.length, bw = Math.min(70, (W - 40) / n * 0.6), out = [];
      xs.forEach(function (x, i) {
        var v = x[idx], cx = 20 + (W - 40) * (i + 0.5) / n;
        out.push('<text x="' + cx.toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">' + esc(x[0]) + '</text>');
        if (v === null) { out.push('<text x="' + cx.toFixed(1) + '" y="' + (H - 40) + '" text-anchor="middle">—</text>'); return; }
        var h = (H - 70) * v / mx, y = H - 28 - h;
        out.push('<rect class="col-div' + (x[0] === 'Últ. 12M' ? ' ult' : '') + '" x="' + (cx - bw / 2).toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="4"/>' +
          '<text x="' + cx.toFixed(1) + '" y="' + (y - 6).toFixed(1) + '" text-anchor="middle">' + (est.med === 'dy' ? br(v, 2) + '%' : br(v, v < 1 ? 3 : 2)) + '</text>');
      });
      alvo.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + (est.med === 'dy' ? 'Dividend yield por ano' : 'Valor por ' + unid + ' por ano, em reais') + '">' + out.join('') + '</svg>';
    }
    B.addEventListener('click', function (ev) {
      var b = ev.target.closest('button'); if (!b) return;
      if (b.hasAttribute('data-med')) { est.med = b.getAttribute('data-med'); B.querySelectorAll('[data-med]').forEach(function (x) { x.setAttribute('aria-pressed', x === b); }); }
      if (b.hasAttribute('data-per')) { est.per = +b.getAttribute('data-per'); B.querySelectorAll('[data-per]').forEach(function (x) { x.setAttribute('aria-pressed', x === b); }); }
      desenha();
    });
    var anos = dados.filter(function (x) { return x[0] !== 'Últ. 12M'; }).length;
    if (anos <= 5) B.querySelectorAll('[data-per="10"],[data-per="0"]').forEach(function (x) { x.hidden = true; });
    else if (anos <= 10) B.querySelectorAll('[data-per="0"]').forEach(function (x) { x.hidden = true; });
    desenha();
  }

  // ---------- tabelas: "ver todas" e ordenação ----------
  function verMais(T) {
    var n = +T.getAttribute('data-mostra'), rows = [].slice.call(T.tBodies[0].rows);
    if (rows.length <= n) return;
    var aberto = false, bt = document.createElement('button');
    bt.type = 'button'; bt.className = 'botao claro ver-todas';
    function aplica() {
      var vis = 0;
      [].slice.call(T.tBodies[0].rows).forEach(function (r) { var mostra = aberto || r.classList.contains('este') || vis < n - (T.querySelector('tr.este') && !r.classList.contains('este') ? 1 : 0); if (mostra && !r.classList.contains('este')) vis++; r.hidden = !mostra; });
      bt.textContent = aberto ? 'Mostrar menos' : 'Ver todas (' + rows.length + ')';
      bt.setAttribute('aria-expanded', aberto);
    }
    bt.addEventListener('click', function () { aberto = !aberto; aplica(); });
    T.closest('.rolagem').insertAdjacentElement('afterend', bt);
    T._aplica = aplica; aplica();
  }
  function ordena(T) {
    var ord = { k: null, d: 1 };
    T.querySelectorAll('th button').forEach(function (bt) {
      bt.addEventListener('click', function () {
        var k = bt.getAttribute('data-ord'), B = T.tBodies[0], rows = [].slice.call(B.rows);
        ord.d = ord.k === k ? -ord.d : (k === 'c' ? 1 : -1); ord.k = k;
        rows.sort(function (a, b) {
          var x = a.getAttribute('data-' + k), y = b.getAttribute('data-' + k);
          if (k === 'c') return ord.d * x.localeCompare(y);
          if (x === '' || x === null) return 1; if (y === '' || y === null) return -1;
          return ord.d * (parseFloat(x) - parseFloat(y));
        });
        rows.forEach(function (r) { B.appendChild(r); });
        T.querySelectorAll('th').forEach(function (th) { th.removeAttribute('aria-sort'); });
        bt.parentNode.setAttribute('aria-sort', ord.d > 0 ? 'ascending' : 'descending');
        if (T._aplica) T._aplica();
      });
    });
  }

  // ---------- compartilhar e favoritar ----------
  function acoes() {
    var c = document.querySelector('.compartilhar');
    if (c) c.addEventListener('click', function () {
      var url = location.href.split('#')[0], t = c.getAttribute('data-titulo'), lab = c.querySelector('span');
      if (navigator.share) { navigator.share({ title: t, url: url }).catch(function () {}); return; }
      var ok = function () { lab.textContent = 'Link copiado'; setTimeout(function () { lab.textContent = 'Compartilhar'; }, 2500); };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(ok, function () { prompt('Copie o link:', url); });
      else prompt('Copie o link:', url);
    });
    var f = document.querySelector('.favoritar'), K = 'ml-favoritos', lista;
    if (!f) return;
    try { lista = JSON.parse(localStorage.getItem(K) || '[]'); localStorage.setItem(K, JSON.stringify(lista)); } catch (e) { return; } // sem armazenamento: o botão fica escondido
    var cod = f.getAttribute('data-cod'), lab = f.querySelector('span');
    function mostra() { var on = lista.indexOf(cod) >= 0; f.setAttribute('aria-pressed', on); lab.textContent = on ? 'Favorito' : 'Favoritar'; }
    f.hidden = false; mostra();
    f.addEventListener('click', function () {
      var i = lista.indexOf(cod); if (i >= 0) lista.splice(i, 1); else lista.push(cod);
      try { localStorage.setItem(K, JSON.stringify(lista)); } catch (e) {}
      mostra();
    });
  }

  document.querySelectorAll('.grafico2').forEach(grafico);
  document.querySelectorAll('.comp').forEach(comparacao);
  document.querySelectorAll('.div-grafico').forEach(barras);
  document.querySelectorAll('table.ver-mais').forEach(verMais);
  document.querySelectorAll('table.pares').forEach(ordena);
  acoes();
})();
