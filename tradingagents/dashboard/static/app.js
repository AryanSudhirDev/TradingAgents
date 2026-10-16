'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dollars = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents / 100);
const signClass = number => number < 0 ? 'neg' : number > 0 ? 'pos' : '';
const steps = ['Market','Sentiment','News','Fundamentals','Bull','Bear','Research manager','Trader','Aggressive','Conservative','Neutral','Portfolio manager'];
const quotes = new Map();
const versions = new Map();
const pendingTrades = new Map();
const busyTrades = new Set();
let desk, polling = false;

function toast(message, error = false) {
  const item = document.createElement('div');
  item.className = 'toast' + (error ? ' error' : '');
  item.textContent = message;
  $('#toast-container').appendChild(item);
  setTimeout(() => item.remove(), 6000);
}

async function api(path, body) {
  const response = await fetch('/api/' + path, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed.');
  return data;
}

function table(headers, rows) {
  if (!rows.length) return '<p class="muted">No entries yet.</p>';
  return `<table><thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>'<tr>'+r.map(v=>`<td>${v}</td>`).join('')+'</tr>').join('')}</tbody></table>`;
}

function renderPortfolio(book) {
  const unrealized = book.positions.reduce((sum,p)=>sum + (p.price == null ? 0 : p.quantity*p.price-p.basis),0);
  $('#metrics').innerHTML = [['Paper equity',dollars(book.total_value)],['Virtual cash',dollars(book.cash)],['Unrealized P&L',dollars(unrealized)],['Realized P&L',dollars(book.realized)]].map(([label,value])=>`<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('');
  $('#positions').innerHTML = table(['Symbol','Shares','Average cost','Mark / as of','Unrealized P&L'],book.positions.map(p=>[
    esc(p.ticker),p.quantity,dollars(p.basis/p.quantity),
    p.price == null ? 'Unavailable' : `${dollars(p.price)} <span class="muted">${esc(p.as_of)}</span>`,
    p.price == null ? 'Unavailable' : `<span class="${signClass(p.quantity*p.price-p.basis)}">${dollars(p.quantity*p.price-p.basis)}</span>`
  ]));
  $('#trades').innerHTML = table(['Time','Symbol','Side','Shares','Paper fill','Quote date','Realized P&L','Research date'],book.trades.map(t=>[
    esc(new Date(t.timestamp).toLocaleString()),esc(t.ticker),esc(t.side),t.quantity,dollars(t.price),esc(t.quote_as_of),
    t.side==='SELL' ? `<span class="${signClass(t.realized)}">${dollars(t.realized)}</span>` : '—',esc(t.analysis_date || 'No analysis')
  ]));
}

function createCard(ticker) {
  const card = document.createElement('article');
  card.id = 'card-' + ticker;
  card.className = 'ticker-card';
  card.innerHTML = `<div class="card-header"><h2 class="card-ticker-name">${esc(ticker)}</h2><div class="card-actions"><button class="btn" data-action="analyze" data-ticker="${esc(ticker)}">Analyze</button><button class="btn-remove" data-action="remove" data-ticker="${esc(ticker)}" aria-label="Remove ${esc(ticker)} from watchlist">×</button></div></div>
    <div class="card-agent-bar" data-progress>Ready for research</div><div class="agent-pills" data-pills></div>
    <div class="chart-container" data-chart><span class="muted">Loading Yahoo price data…</span></div>
    <div class="card-decision" data-decision></div><div class="card-plan" data-plan></div><div class="card-plan" data-live></div>
    <div class="trade-bar"><div class="trade-controls"><label for="shares-${esc(ticker)}" class="muted">Shares</label><input type="number" class="trade-input" id="shares-${esc(ticker)}" min="1" max="1000000" step="1" placeholder="1" value="1"><button class="btn-buy" data-action="BUY" data-ticker="${esc(ticker)}">Paper buy</button><button class="btn-sell" data-action="SELL" data-ticker="${esc(ticker)}">Paper sell</button></div><div class="trade-position" data-position></div></div>
    <div class="report-actions"><label for="history-${esc(ticker)}" class="muted">Reports</label><select id="history-${esc(ticker)}" data-history aria-label="Saved ${esc(ticker)} reports"><option value="">No saved reports</option></select><button class="btn" data-action="report" data-ticker="${esc(ticker)}">Open report</button></div>`;
  $('#grid').appendChild(card);
  loadQuote(ticker);
  loadHistory(ticker);
}

async function loadHistory(ticker) {
  try {
    const items = await api('history/' + encodeURIComponent(ticker));
    const select = $('#card-' + ticker)?.querySelector('[data-history]');
    if (!select) return;
    const old = select.value;
    select.innerHTML = items.length ? items.map(i=>`<option value="${esc(i.date)}">${esc(i.date)} · ${esc(i.rating)}</option>`).join('') : '<option value="">No saved reports</option>';
    if (items.some(i=>i.date===old)) select.value = old;
  } catch (error) { toast(error.message,true); }
}

async function loadQuote(ticker) {
  const container = $('#card-' + ticker)?.querySelector('[data-chart]');
  try {
    const data = await api('market/' + encodeURIComponent(ticker));
    quotes.set(ticker,data);
    if (!container) return;
    const values = data.rows.map(r=>Number(r.close));
    if (!values.length || values.some(v=>!Number.isFinite(v))) throw new Error('Invalid price data.');
    const min = Math.min(...values), span = Math.max(...values)-min || 1;
    const path = values.map((v,i)=>`${i?'L':'M'}${(i*500/Math.max(1,values.length-1)).toFixed(2)},${(90-(v-min)*80/span).toFixed(2)}`).join(' ');
    container.innerHTML = `<div class="price-label">${dollars(Math.round(data.price*100))} · daily bar as of ${esc(data.as_of)}</div><svg viewBox="0 0 500 100" role="img" aria-label="${esc(ticker)} recent price history"><path d="${path}" fill="none" stroke="#f0a500" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
  } catch (error) {
    if (container) { container.textContent = error.message; container.classList.add('muted'); }
  }
}

async function refresh() {
  if (polling) return;
  polling = true;
  try {
    desk = await api('state');
    $('#connection').textContent = 'Local engine connected';
    $('#model-info').textContent = `Provider: ${desk.provider} · Analysts: ${desk.quick_model} · Managers: ${desk.deep_model}. Model calls use the configured provider’s usage allowance.`;
    $('#fred-status').textContent = desk.fred_configured ? 'FRED key configured; availability is reported in each analysis.' : 'FRED is not configured. A separate free FRED key enables economic indicators.';
    renderPortfolio(desk.portfolio);
    const tickers = desk.portfolio.watchlist;
    if (!$('#grid').querySelector('article')) $('#grid').replaceChildren();
    for (const card of $('#grid').querySelectorAll('article')) if (!tickers.includes(card.id.slice(5))) card.remove();
    if (!tickers.length) $('#grid').innerHTML = '<div class="empty-state"><h2 class="empty-title">Your watchlist is empty</h2><p>Add a US stock or ETF above. Research starts when you click Analyze.</p></div>';
    for (const ticker of tickers) {
      if (!$('#card-' + ticker)) { $('#grid').querySelector('.empty-state')?.remove(); createCard(ticker); }
      const card = $('#card-' + ticker), latest = desk.latest[ticker];
      const active = desk.active?.ticker === ticker ? desk.active : null;
      const running = active?.status === 'running';
      card.classList.toggle('analyzing',running);
      card.querySelector('[data-action="analyze"]').disabled = desk.active?.status === 'running';
      card.querySelector('[data-action="remove"]').disabled = running;
      card.querySelector('[data-progress]').textContent = active?.status==='error' ? active.error : running ? `Research running · ${active.completed.length}/12 stages reported · ${active.stats.llm_calls || 0} model calls` : latest ? `Research complete · ${latest.date}` : 'Ready · click Analyze to start';
      card.querySelector('[data-progress]').classList.toggle('error',active?.status==='error');
      const completed = active?.completed || latest?.completed || [];
      card.querySelector('[data-pills]').innerHTML = steps.map(name=>`<span class="agent-pill${completed.includes(name)?' done':''}">${esc(name)}</span>`).join('');
      const live=card.querySelector('[data-live]');
      const reportVersion=JSON.stringify(active?.reports || {});
      if (live.dataset.version!==reportVersion) {
        const open=live.querySelector('details')?.open || false;
        live.dataset.version=reportVersion;
        live.innerHTML=active?.status==='running' && Object.keys(active.reports || {}).length ? `<details${open?' open':''}><summary>Live analyst reports</summary>${Object.entries(active.reports).map(([name,text])=>`<h3>${esc(name)}</h3><pre>${esc(text)}</pre>`).join('')}</details>` : '';
      }
      const version = JSON.stringify(latest);
      if (!versions.has(ticker) || versions.get(ticker) !== version) {
        versions.set(ticker,version);
        card.querySelector('[data-decision]').innerHTML = latest ? `<span class="paper-badge">${esc(latest.rating)}</span><p class="decision-reasoning">${esc(latest.decision)}</p>` : '<p class="muted">No research decision yet. Paper trades are always your choice.</p>';
        card.querySelector('[data-plan]').innerHTML = latest?.plan ? `<details><summary>Trader’s proposed plan</summary><pre>${esc(latest.plan)}</pre></details>` : '';
        loadHistory(ticker);
      }
      const pos = desk.portfolio.positions.find(p=>p.ticker===ticker);
      card.querySelector('[data-position]').textContent = pos ? `Paper holding: ${pos.quantity} shares · average cost ${dollars(pos.basis/pos.quantity)}` : 'No paper position';
      for (const side of ['BUY','SELL']) card.querySelector(`[data-action="${side}"]`).disabled = busyTrades.has(ticker) || (side==='SELL' && !pos);
    }
  } catch (error) { $('#connection').textContent = 'Connection unavailable — retrying'; }
  finally { polling = false; }
}

$('#watch-form').addEventListener('submit',async event=>{
  event.preventDefault();
  try { await api('watch',{ticker:$('#ticker-input').value}); $('#ticker-input').value=''; await refresh(); }
  catch (error) { toast(error.message,true); }
});

$('#refresh-prices').addEventListener('click',async event=>{
  const button=event.currentTarget; button.disabled=true;
  try {
    const symbols = new Set([...(desk?.portfolio.watchlist || []),...(desk?.portfolio.positions || []).map(p=>p.ticker)]);
    await Promise.all([...symbols].map(loadQuote));
    await refresh();
  } finally { button.disabled=false; }
});

$('#grid').addEventListener('click',async event=>{
  const button=event.target.closest('button[data-action]');
  if (!button || button.disabled) return;
  const {action,ticker}=button.dataset;
  try {
    if (action==='remove') { await api('watch',{ticker,remove:true}); versions.delete(ticker); }
    if (action==='analyze') { button.disabled=true; await api('analyze',{ticker}); toast(`${ticker} analysis started.`); }
    if (action==='report') {
      const day=$('#card-'+ticker).querySelector('[data-history]').value;
      if (!day) throw new Error('Run an analysis to create a report.');
      window.open(`/api/report/${encodeURIComponent(ticker)}/${encodeURIComponent(day)}`,'_blank','noopener');
    }
    if (action==='BUY' || action==='SELL') {
      if (busyTrades.has(ticker)) return;
      const quantity=Number($('#shares-'+ticker).value);
      if (!Number.isInteger(quantity) || quantity<=0) throw new Error('Enter a positive whole-share quantity.');
      const previous=pendingTrades.get(ticker);
      const request=previous?.side===action && previous.quantity===quantity ? previous : {ticker,side:action,quantity,request_id:crypto.randomUUID()};
      pendingTrades.set(ticker,request); busyTrades.add(ticker); button.disabled=true;
      try {
        const result=await api('trade',request);
        pendingTrades.delete(ticker);
        toast(`Paper ${result.trade.side}: ${quantity} ${ticker} at ${dollars(result.trade.price)}. No broker order was sent.`);
      } finally { busyTrades.delete(ticker); }
    }
    await refresh();
  } catch (error) { toast(error.message,true); await refresh(); }
});

refresh();
setInterval(refresh,2000);
