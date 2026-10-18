'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dollars = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents / 100);
const signClass = number => number < 0 ? 'neg' : number > 0 ? 'pos' : '';
const steps = ['Data','Timestral','Policy'];
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
  $('#metrics').innerHTML = [['Local simulator equity',dollars(book.total_value)],['Local virtual cash',dollars(book.cash)],['Unrealized P&L',dollars(unrealized)],['Realized P&L',dollars(book.realized)]].map(([label,value])=>`<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('');
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
    <div class="card-decision" data-decision></div><div class="card-plan" data-forecast></div><div class="card-plan" data-plan></div><div class="card-plan" data-live></div>
    <p class="card-note">Manual local simulator · separate from Alpaca</p><div class="trade-bar"><div class="trade-controls"><label for="shares-${esc(ticker)}" class="muted">Shares</label><input type="number" class="trade-input" id="shares-${esc(ticker)}" min="1" max="1000000" step="1" placeholder="1" value="1"><button class="btn-buy" data-action="BUY" data-ticker="${esc(ticker)}">Local buy</button><button class="btn-sell" data-action="SELL" data-ticker="${esc(ticker)}">Local sell</button></div><div class="trade-position" data-position></div></div>
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
    select.innerHTML = items.length ? items.map(i=>`<option value="${esc(i.date+'|'+i.engine)}">${esc(i.date)} · ${esc(i.rating)} · ${esc(i.engine)}</option>`).join('') : '<option value="">No saved reports</option>';
    if (items.some(i=>i.date+'|'+i.engine===old)) select.value = old;
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
    $('#model-info').textContent = `${desk.engine.model} · local CPU · five-session forecasts · no ChatGPT calls. Quantile bands are estimates, not calibrated confidence or guaranteed loss limits.`;
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
      card.querySelector('[data-progress]').textContent = active?.status==='error' ? active.error : running ? `Forecast running · ${active.completed.length}/${steps.length} stages complete` : latest ? `Research complete · ${latest.date}` : 'Ready · click Analyze to start';
      card.querySelector('[data-progress]').classList.toggle('error',active?.status==='error');
      const completed = active?.completed || latest?.completed || [];
      card.querySelector('[data-pills]').innerHTML = steps.map(name=>`<span class="agent-pill${completed.includes(name)?' done':''}">${esc(name)}</span>`).join('');
      const live=card.querySelector('[data-live]');
      const reportVersion=JSON.stringify(active?.reports || {});
      if (live.dataset.version!==reportVersion) {
        const open=live.querySelector('details')?.open || false;
        live.dataset.version=reportVersion;
        live.innerHTML=active?.status==='running' && Object.keys(active.reports || {}).length ? `<details${open?' open':''}><summary>Forecast details</summary>${Object.entries(active.reports).map(([name,text])=>`<h3>${esc(name)}</h3><pre>${esc(text)}</pre>`).join('')}</details>` : '';
      }
      const version = JSON.stringify(latest);
      if (!versions.has(ticker) || versions.get(ticker) !== version) {
        versions.set(ticker,version);
        card.querySelector('[data-decision]').innerHTML = latest ? `<span class="paper-badge">${esc(latest.rating)}</span><p class="decision-reasoning">${esc(latest.decision)}</p>` : '<p class="muted">No completed research decision yet.</p>';
        card.querySelector('[data-plan]').innerHTML = latest?.plan ? `<details><summary>Decision policy</summary><pre>${esc(latest.plan)}</pre></details>` : '';
        const f=latest?.forecast;
        card.querySelector('[data-forecast]').innerHTML=f?`<p class="muted">${f.context_sessions} completed sessions through ${esc(f.last_session)} · inference ${Number(f.inference_ms).toFixed(1)} ms${f.cache_hit?' · frozen forecast reused':''}</p>${table(['Session','q10 estimate','Median','q90 estimate'],f.rows.map(r=>[esc(r.date),dollars(r.q10*100),dollars(r.median*100),dollars(r.q90*100)]))}<p class="muted">Nominal 10th–90th quantiles; historical coverage has not been established.</p>`:'';
        loadHistory(ticker);
      }
      const pos = desk.portfolio.positions.find(p=>p.ticker===ticker);
      card.querySelector('[data-position]').textContent = pos ? `Manual simulator: ${pos.quantity} shares · average cost ${dollars(pos.basis/pos.quantity)}` : 'No manual simulator position';
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
      const [day,engine]=$('#card-'+ticker).querySelector('[data-history]').value.split('|');
      if (!day) throw new Error('Run an analysis to create a report.');
      window.open(`/api/report/${encodeURIComponent(ticker)}/${encodeURIComponent(day)}?engine=${encodeURIComponent(engine)}`,'_blank','noopener');
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

let paperPolling=false, paperState, controlBusy=false;
function renderPerformance(p) {
  const box=$('#paper-performance');
  if (!p?.samples?.length) { box.innerHTML='<p class="muted">Forward performance begins with the first cycle. Strategy and SPY price returns are sampled before and after cycles.</p>'; return; }
  const pct=value=>value==null?'Unavailable':`${value.toFixed(3)}%`;
  const points=p.samples.map(s=>({stamp:s.stamp,strategy:(s.equity/p.initial_equity-1)*100,spy:s.benchmark && p.initial_benchmark ? (s.benchmark/p.initial_benchmark-1)*100 : null}));
  const values=points.flatMap(s=>[s.strategy,s.spy]).filter(v=>v!=null && Number.isFinite(v));
  const low=Math.min(0,...values), span=Math.max(...values)-low || 1;
  const start=new Date(points[0].stamp).getTime(), duration=new Date(points.at(-1).stamp).getTime()-start || 1;
  const x=s=>20+(new Date(s.stamp).getTime()-start)/duration*660, y=v=>140-(v-low)/span*120;
  const line=(field,color)=>{ const usable=points.filter(s=>s[field]!=null); return `<path d="${usable.map((s,i)=>`${i?'L':'M'}${x(s).toFixed(2)},${y(s[field]).toFixed(2)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2"/>`+usable.map(s=>`<circle cx="${x(s).toFixed(2)}" cy="${y(s[field]).toFixed(2)}" r="3" fill="${color}"><title>${esc(new Date(s.stamp).toLocaleString())}: ${pct(s[field])}</title></circle>`).join(''); };
  box.innerHTML=`<h3>Forward performance since ${esc(new Date(p.started).toLocaleString())}</h3><div class="metrics">${[['Sampled P&L since start',dollars(p.pnl)],['Strategy return',pct(p.return_pct)],['SPY price return',pct(p.spy_return_pct)],['Sampled drawdown',pct(p.drawdown_pct)]].map(([label,value])=>`<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('')}</div><svg viewBox="0 0 700 160" style="width:100%;max-height:220px" role="img" aria-label="Strategy and SPY cumulative percentage returns">${line('strategy','#f0a500')}${line('spy','#4dd9c0')}</svg><p class="muted">Amber: strategy · Mint: SPY · ${p.count} samples. SPY uses Yahoo snapshots and excludes dividends. Drawdown is measured only at sampled times; this is not a backtest or proof of outperformance.</p>`;
}
async function refreshPaper() {
  if (paperPolling) return;
  paperPolling=true;
  try {
    paperState=await api('paper/status');
    const p=paperState;
    const local=p.mode==='local', label=local?'Local automatic simulator':'Alpaca paper';
    const failure=p.error || (p.health && !p.health.ok ? p.health.error || 'Research scheduler is unavailable. Check the background service.' : '');
    $('#paper-status').textContent=`${label} ${p.connected?'connected':'unavailable'} · ${p.enabled?'Daily runs enabled':'Daily runs paused'} · ${p.busy?'Cycle running · ':''}${failure || p.message}`;
    $('#paper-cadence').textContent=local?'Local daily runs start at 16:30 New York time when a Yahoo bar exists for that date. Run now can use a partial daily bar. Snapshot fills include 0.05% slippage per side; fees, latency and liquidity are not modeled. This account is separate from Alpaca and the manual ledger.':'Alpaca daily research starts at 10:00 New York on market days, with no new orders in the final 30 minutes. DAY limit orders use fresh IEX quotes with a 0.5% price allowance. Alpaca reports actual paper order statuses and simulated fills. Use a dedicated paper account.';
    $('#paper-status').classList.toggle('error',Boolean(failure));
    if (!p.configured && !local) $('#paper-credentials').open=true;
    if (!controlBusy) $('#paper-mode').value=p.mode;
    $('#paper-mode').disabled=Boolean(p.busy) || controlBusy;
    if (!$('#auto-symbols').dataset.loaded) { $('#auto-symbols').value=p.symbols.join(','); $('#auto-symbols').dataset.loaded='1'; }
    $('#auto-symbols').disabled=Boolean(p.busy);
    for (const id of ['paper-enable','paper-run']) $('#'+id).disabled=controlBusy || !p.connected || p.busy;
    $('#paper-pause').disabled=controlBusy || (!p.enabled && !p.busy);
    const a=p.account;
    const metrics=a?[[`${label} equity`,a.equity],['Cash',a.cash],...(a.last_equity==null?[]:[['Change since prior close',Number(a.equity)-Number(a.last_equity)]])]:[];
    $('#broker-metrics').innerHTML=metrics.map(([name,value])=>`<div class="metric"><span>${name}</span><strong>${dollars(Math.round(Number(value)*100))}</strong></div>`).join('')+(a?`<p class="muted">Account snapshot: ${esc(new Date(p.as_of).toLocaleString())}${local?'':` · ${p.market_open?'Market open':'Market closed'}`}</p>`:'');
    renderPerformance(p.performance);
    $('#broker-positions').innerHTML=table([`${label} symbol`,'Shares','Average cost','Current mark','Unrealized P&L','First fill / exit due'],(p.positions || []).map(pos=>[esc(pos.symbol),esc(pos.qty),dollars(Number(pos.avg_entry_price)*100),dollars(Number(pos.current_price)*100),dollars(Number(pos.unrealized_pl)*100),esc(p.holdings?.[pos.symbol]?.first_day || 'Unverified')+' / '+esc(p.holdings?.[pos.symbol]?.deadline || 'Pending')]));
    $('#paper-orders-title').textContent=local?'Local automatic fills · latest 100':'Alpaca orders · latest 100, including fills and rejections';
    $('#broker-orders').innerHTML=table(['Submitted','Symbol','Side','Shares','Status','Filled shares','Average fill','Limit','Client order ID'],(p.orders || []).map(o=>[esc(o.submitted_at?new Date(o.submitted_at).toLocaleString():'—'),esc(o.symbol),esc(o.side),esc(o.qty),esc(o.status),esc(o.filled_qty),o.filled_avg_price?dollars(Number(o.filled_avg_price)*100):'—',o.limit_price?dollars(Number(o.limit_price)*100):'—',esc(o.client_order_id)]));
    const orderStates=new Map((p.orders || []).map(o=>[o.client_order_id,o.status]));
    $('#paper-journal').innerHTML=table(['Day','Symbol','Rating','Execution','Fill status','Details','Report','Client order ID'],p.runs.map(r=>{
      let intent='';
      try { const i=JSON.parse(r.intent || 'null'); if(i) intent=`<br>${esc(i.side.toUpperCase())} ${esc(i.qty)} ${esc(i.symbol)} · ${local?'simulated price':'limit'} ${dollars(Number(i.limit_price)*100)}`; } catch { intent=''; }
      return [esc(r.day),esc(r.ticker),esc(r.rating || '—'),esc(r.status),esc(orderStates.get(r.client_id) || (r.status==='skipped'?'No order':'—')),esc(r.note)+intent,r.has_report?`<a href="/api/paper/report/${encodeURIComponent(r.client_id)}" target="_blank" rel="noreferrer">Research</a>`:'—',esc(r.client_id)];
    }));
  } catch(error) { $('#paper-status').textContent='Paper status unavailable: '+error.message; }
  finally { paperPolling=false; }
}
$('#paper-connect').addEventListener('submit',async event=>{
  event.preventDefault();
  const form=event.currentTarget, button=form.querySelector('button'); button.disabled=true;
  try {
    await api('paper/connect',{key:form.elements.key.value.trim(),secret:form.elements.secret.value.trim()});
    form.reset(); $('#paper-credentials').open=false;
    toast('Alpaca paper connected. Enable daily runs or run one cycle.');
    await refreshPaper();
  } catch(error) { toast(error.message,true); }
  finally { button.disabled=false; }
});
$('#paper-control').addEventListener('submit',async event=>{
  event.preventDefault();
  if (controlBusy) return;
  controlBusy=true;
  try {
    await api('paper/control',{action:event.submitter.value,mode:$('#paper-mode').value,symbols:$('#auto-symbols').value.split(',').map(s=>s.trim().toUpperCase()).filter(Boolean)});
    toast(event.submitter.value==='pause'?'Paper automation paused. Existing orders remain at Alpaca.':'Paper cycle requested.');
  } catch(error) { toast(error.message,true); }
  finally { controlBusy=false; await refreshPaper(); }
});
$('#paper-mode').addEventListener('change',async event=>{
  controlBusy=true;
  try { await api('paper/control',{action:'select',mode:event.currentTarget.value}); toast('Execution mode selected. Daily runs are paused.'); }
  catch(error) { toast(error.message,true); }
  finally { controlBusy=false; await refreshPaper(); }
});
refreshPaper();
setInterval(refreshPaper,5000);

async function refreshBacktest() {
  try {
    const data=await api('timestral/backtest');
    $('#backtest-summary').innerHTML=data.ready?`<p>${esc(data.plan.start)} – ${esc(data.plan.end)} · completed ${esc(new Date(data.completed_at).toLocaleString())}</p>${table(['Fixed policy','Sessions','Net return','Sampled drawdown','Fills','Mean exposure'],data.arms.map(a=>[esc(a.arm),a.sessions,Number(a.return_pct).toFixed(3)+'%',Number(a.drawdown_pct).toFixed(3)+'%',a.fills,Number(a.average_exposure_pct).toFixed(2)+'%']))}<p class="muted">${esc(data.limits)}</p>`:'<p class="muted">The fixed replay has not completed yet.</p>';
  } catch { $('#backtest-summary').textContent='Saved replay unavailable; check the private run log.'; }
}
refreshBacktest();

async function refreshMarkets() {
  try {
    const data=await api('timestral/markets');
    const n=value=>value==null?'—':Number(value).toFixed(2)+'%';
    $('#markets-summary').innerHTML=data.ready?`<p>${data.aggregates.length}/${data.requested_series} series saved · ${data.failed_series} failed</p>${table(['Series','Market','Resolved windows','Model MAPE','Last-close MAPE','Drift MAPE','Skill vs last close','q10–q90 coverage'],data.aggregates.map(a=>[esc(a.ticker),esc(a.market),a.resolved,n(a.model_mape_pct),n(a.flat_mape_pct),n(a.drift_mape_pct),n(a.skill_vs_flat_pct),n(a.interval_coverage_pct)]))}<p class="muted">${esc(data.limits)}</p>`:'<p class="muted">The fixed comparison has not completed yet.</p>';
  } catch { $('#markets-summary').textContent='Saved cross-market comparison unavailable.'; }
}
refreshMarkets();
