const state={data:null,workspace:'business',view:new URLSearchParams(location.search).get('view')||'atlas',selectedId:'invoice:INV-1007',selectedFinding:'F-ROUTE-001',zoom:1,pan:{x:0,y:0},yaw:-.32,nodes:[],sessionId:`payproof-${Date.now()}`,lastContext:null,demoStep:0,sourceConfig:null,bankPreview:null,activePlaidHandler:null,oauthPoll:null,loadGeneration:0,sourceGeneration:0,workspaceGeneration:0,changeCurrencyByWorkspace:{}};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const riskColor={clear:'#3cf0a5',review:'#ffc64d',high:'#ff5274'};
const money=(cents,currency='USD')=>new Intl.NumberFormat('en-US',{style:'currency',currency}).format(cents/100);
const api=async(url,options={})=>{
  const response=await fetch(url,options);
  let body={};
  try{body=await response.json()}catch{body={error:`The server returned an unreadable response (${response.status}).`}}
  if(!response.ok){const error=new Error(body.error||body.errors?.join(', ')||`Request failed (${response.status})`);error.payload=body;error.status=response.status;throw error}
  return body;
};
const jsonRequest=(method,payload)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});

async function loadData(){
  const workspace=state.workspace,generation=++state.loadGeneration;
  const data=await api(`/api/dashboard?workspace=${encodeURIComponent(workspace)}`);
  if(workspace!==state.workspace||generation!==state.loadGeneration)return false;
  state.data=data;
  if(state.workspace==='business'&&state.data.security?.graph?.nodes?.length)state.data.graph=state.data.security.graph;
  renderWorkspaceOptions();renderMetrics();renderFindings();renderFocus();renderVisual();renderPrism();syncNav();
  $('#updatedAt').textContent=`Updated ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
  return true;
}
function renderWorkspaceOptions(){const el=$('#workspaceSelect'),fragment=document.createDocumentFragment();(state.data?.workspaces||[]).forEach(workspace=>{const option=document.createElement('option');option.value=workspace.id;option.textContent=workspace.name;fragment.append(option)});el.replaceChildren(fragment);el.value=state.workspace}
function renderMetrics(){if(state.workspace==='business'){const s=state.data.security.metrics;$('#metrics').innerHTML=[['Controls assessed',s.controls_assessed,'QUESTIONNAIRE CONTROLS','green'],['Control gaps',s.gaps,'OPERATING FAILURES','red'],['Needs review',s.needs_review,'INCOMPLETE OR CONFLICTING','amber'],['Evidence sources',s.evidence_sources,'CITED RECORDS','']].map(x=>`<article class="metric ${x[3]}"><span>${x[0].toUpperCase()}</span><strong>${x[1]}</strong><small>${x[2]}</small></article>`).join('');return}const m=state.data.metrics;$('#metrics').innerHTML=[
  ['Money in',m.cash_in_label,'RECORDED INCOME','green'],
  ['Money out',m.cash_out_label,`${m.transaction_count} TRANSACTIONS`,'amber'],
  ['Net cash',m.net_cash_label,'INCOME MINUS OUTFLOW',''],
  ['Employee spend',m.employee_spend_label,`${state.data.expenses.length} REPORTS`,'red']
].map(x=>`<article class="metric ${x[3]}"><span>${x[0].toUpperCase()}</span><strong>${x[1]}</strong><small>${x[2]}</small></article>`).join('')}
function renderFindings(){const rail=$('#findingRail');if(state.workspace==='business'){rail.innerHTML=state.data.security.controls.map(c=>`<button class="finding-mini ${c.status==='gap'?'high':''}" data-control="${c.id}"><i></i><span><b>${escapeHtml(c.name)}</b><small>${c.confidence}% confidence</small></span><strong>${c.status.toUpperCase()}</strong></button>`).join('');$$('[data-control]').forEach(b=>b.onclick=()=>selectControl(b.dataset.control));return}rail.innerHTML=state.data.findings.slice(0,4).map(f=>`<button class="finding-mini ${f.severity}" data-finding="${f.id}"><i></i><span><b>${f.title}</b><small>${f.entity_id}</small></span><strong>${f.severity.toUpperCase()}</strong></button>`).join('');$$('[data-finding]').forEach(b=>b.onclick=()=>selectFinding(b.dataset.finding))}
function selectControl(id){const c=state.data.security.controls.find(x=>x.id===id);state.selectedId=`control:${id}`;$('#focusTitle').textContent=`${c.status.toUpperCase()} · ${c.name}`;$('#focusSummary').textContent=`${c.answer} ${c.contradiction}`;$('#comparison').innerHTML=`<div class="compare-value"><span>CONFIDENCE</span><strong>${c.confidence}%</strong></div><div class="compare-value new"><span>EVIDENCE</span><strong>${c.evidence.length}</strong></div>`;drawAtlas();openRecord(state.selectedId)}
function selectFinding(id){state.selectedFinding=id;const f=state.data.findings.find(x=>x.id===id);if(f){state.selectedId=`invoice:${f.entity_id}`;if(f.entity_id.startsWith('TX-'))state.selectedId=`transaction:${f.entity_id}`;renderFocus();renderVisual();addMessage('assistant',`${f.title}: ${f.summary}`,[...f.evidence_ids])}}
function renderFocus(){if(state.workspace==='business'&&state.data.security?.controls?.length){const c=state.data.security.controls.find(x=>`control:${x.id}`===state.selectedId)||state.data.security.controls.find(x=>x.status==='gap');state.selectedId=`control:${c.id}`;$('#focusTitle').textContent=`${c.status.toUpperCase()} · ${c.name}`;$('#focusSummary').textContent=`${c.answer} ${c.contradiction}`;$('#comparison').innerHTML=`<div class="compare-value"><span>CONFIDENCE</span><strong>${c.confidence}%</strong></div><div class="compare-value new"><span>EVIDENCE</span><strong>${c.evidence.length}</strong></div>`;return}const f=state.data.findings.find(x=>x.id===state.selectedFinding)||state.data.findings[0];if(!f){$('#focusTitle').textContent='No findings in this company yet';$('#focusSummary').textContent='Connect a bank, Gmail, or an intake folder to begin building evidence for this company.';$('#comparison').innerHTML='';return}$('#focusTitle').textContent=`${f.severity.toUpperCase()} · ${f.title}`;$('#focusSummary').textContent=`${f.summary} ${f.basis}`;$('#comparison').innerHTML=f.kind==='destination_change'?`<div class="compare-value"><span>VERIFIED</span><strong>****7284</strong></div><div class="compare-value new"><span>PROPOSED</span><strong>****9142</strong></div>`:`<div class="compare-value"><span>RULE BASIS</span><strong>${f.kind.replaceAll('_',' ')}</strong></div>`}
function renderPrism(){const p=state.data.prism,el=$('#prismPill');el.className=`pill ${p.state==='configured'?'good':'muted'}`;el.innerHTML=`<i></i> PRISM ${p.state==='configured'?'CONFIGURED':'NEEDS KEY'}${p.queued?` · ${p.queued} QUEUED`:''}`;const badge=$('.assistant-badges span');if(badge)badge.textContent=state.data.ai.state==='configured'?`LIVE MODEL · ${state.data.ai.model}`:'LOCAL FALLBACK'}

function renderVisual(){
  ['atlasCanvas','changeView','geoView','recordsView'].forEach(id=>$(`#${id}`).classList.add('hidden'));
  const security=state.workspace==='business',titles=security?{atlas:['Security assurance atlas','3D controls and evidence'],change:['Control readiness','Gaps and contradictions'],geo:['Evidence coverage','Systems and stakeholders'],records:['Security evidence','Questionnaire source records']}:{atlas:['Money relationship atlas','Financial relationships'],change:['Explain the change','Period-over-period financial movement'],geo:['Financial geography','Office and vendor locations'],records:['Evidence explorer','Loaded financial records']};
  $('#viewTitle').textContent=titles[state.view][0];$('#panelTitle').textContent=titles[state.view][1];
  $(`#${state.view==='atlas'?'atlasCanvas':state.view+'View'}`).classList.remove('hidden');
  $('.canvas-tools').classList.toggle('hidden',state.view!=='atlas');
  if(state.view==='atlas')drawAtlas();if(state.view==='change')renderChange();if(state.view==='geo')renderGeo();if(state.view==='records')renderRecords();
}
function layoutNodes(width,height){
  const source=state.data.graph.nodes.map(n=>({...n})), center=source.find(n=>n.type==='workspace');center.x=width*.45;center.y=height*.5;
  const vendors=source.filter(n=>n.type==='vendor');vendors.forEach((n,i)=>{const a=(i/vendors.length)*Math.PI*2-.5;n.x=center.x+Math.cos(a)*Math.min(width*.29,240);n.y=center.y+Math.sin(a)*Math.min(height*.35,125);n.z=Math.sin(a)*150});
  const employees=source.filter(n=>n.type==='employee');employees.forEach((n,i)=>{n.x=width*(.28+i*.18);n.y=height*.82;n.z=(i-1)*85});
  const controls=source.filter(n=>n.type==='control');controls.forEach((n,i)=>{const a=(i/controls.length)*Math.PI*2-.7;n.x=center.x+Math.cos(a)*Math.min(width*.28,225);n.y=center.y+Math.sin(a)*Math.min(height*.3,115);n.z=Math.sin(a)*130});
  const extras=source.filter(n=>!['workspace','vendor','employee','control'].includes(n.type));extras.forEach(n=>{const parentEdge=state.data.graph.edges.find(e=>e.target===n.id);const parent=source.find(v=>v.id===parentEdge?.source);const siblings=extras.filter(x=>state.data.graph.edges.find(e=>e.target===x.id)?.source===parentEdge?.source);const siblingIndex=Math.max(0,siblings.findIndex(x=>x.id===n.id));const a=(siblingIndex/Math.max(siblings.length,1))*Math.PI*2+Math.PI/5;n.x=(parent?.x||center.x)+Math.cos(a)*58;n.y=(parent?.y||center.y)+Math.sin(a)*40;n.z=(parent?.z||0)+Math.sin(a)*35});center.z=0;source.forEach(n=>{const dx=n.x-center.x,z=n.z||0,rx=dx*Math.cos(state.yaw)+z*Math.sin(state.yaw),rz=-dx*Math.sin(state.yaw)+z*Math.cos(state.yaw),scale=520/(520-rz);n.x=center.x+rx*scale;n.y=center.y+(n.y-center.y)*scale;n.depth=rz;n.depthScale=Math.max(.68,Math.min(1.35,scale))});return source;
}
function drawAtlas(){requestAnimationFrame(()=>{const c=$('#atlasCanvas'),box=c.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);c.width=box.width*dpr;c.height=box.height*dpr;const ctx=c.getContext('2d');ctx.scale(dpr,dpr);const w=box.width,h=box.height;ctx.clearRect(0,0,w,h);state.nodes=layoutNodes(w,h);const get=id=>state.nodes.find(n=>n.id===id);ctx.save();ctx.translate(state.pan.x,state.pan.y);ctx.scale(state.zoom,state.zoom);
  const t=Date.now()/800;state.data.graph.edges.forEach(e=>{const a=get(e.source),b=get(e.target);if(!a||!b)return;const active=e.risk==='high';ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle=active?'#ff5274':e.risk==='review'?'#ffc64d55':'#3ed8ff38';ctx.lineWidth=active?3:1+(Math.min(e.amount||0,5000000)/5000000)*2;ctx.shadowBlur=active?14:0;ctx.shadowColor=ctx.strokeStyle;ctx.stroke();if(active){const p=(t%1),x=a.x+(b.x-a.x)*p,y=a.y+(b.y-a.y)*p;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fillStyle='#fff';ctx.fill()}});ctx.shadowBlur=0;
  [...state.nodes].sort((a,b)=>(a.depth||0)-(b.depth||0)).forEach(n=>{const selected=n.id===state.selectedId, color=riskColor[n.risk]||'#3ed8ff',r=(n.size||9)*(n.depthScale||1);ctx.beginPath();ctx.arc(n.x,n.y,r+(selected?5:0),0,Math.PI*2);ctx.fillStyle='#061828';ctx.fill();ctx.lineWidth=selected?3:1.5;ctx.strokeStyle=selected?'#fff':color;ctx.shadowColor=color;ctx.shadowBlur=selected?22:10;ctx.stroke();ctx.shadowBlur=0;ctx.fillStyle=color;ctx.globalAlpha=.8;ctx.beginPath();ctx.arc(n.x,n.y,Math.max(3,r*.35),0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;ctx.fillStyle='#cdeeff';ctx.font=`${n.type==='workspace'?'bold 11':'9'}px Segoe UI`;ctx.textAlign='center';ctx.fillText(n.label,n.x,n.y+r+14)});ctx.restore()})}
function renderChange(){
  if(state.workspace==='business'){
    const controls=state.data.security.controls;
    const bars=controls.map(control=>`<div class="bar-col" style="height:${control.confidence}%"><strong>${control.confidence}%</strong><span>${escapeHtml(control.id.replace('CTRL-',''))}</span></div>`).join('');
    const changes=controls.map(control=>`<button class="change-row" data-control="${escapeHtml(control.id)}"><b>${escapeHtml(control.name)}</b><strong class="${control.status==='gap'?'up':'down'}">${escapeHtml(control.status.toUpperCase())}</strong><small>${escapeHtml(control.contradiction)}</small></button>`).join('');
    $('#changeView').innerHTML=`<div class="period-grid"><div class="chart-card"><h4>Evidence confidence by control</h4><div class="bar-chart">${bars}</div></div><div class="chart-card"><h4>Gaps and contradictions</h4><div class="change-list">${changes}</div></div></div>`;
    $$('#changeView [data-control]').forEach(button=>button.onclick=()=>selectControl(button.dataset.control));
    return;
  }
  const transactions=Array.isArray(state.data.transactions)?state.data.transactions:[],metrics=state.data.metrics||{};
  const metricCurrencies=Object.keys(metrics.recorded_spending_by_currency||{}),transactionCurrencies=transactions.map(item=>String(item.currency||'').trim().toUpperCase()).filter(Boolean);
  const currencies=[...new Set([...transactionCurrencies,...metricCurrencies])].sort();
  const previous=state.changeCurrencyByWorkspace[state.workspace];
  const selectedCurrency=currencies.includes(previous)?previous:(currencies.includes('USD')?'USD':currencies[0]||null);
  if(selectedCurrency)state.changeCurrencyByWorkspace[state.workspace]=selectedCurrency;
  const selectedTransactions=selectedCurrency?transactions.filter(item=>String(item.currency||'').trim().toUpperCase()===selectedCurrency):[];
  const byMonth={};
  selectedTransactions.forEach(transaction=>{
    const month=String(transaction.occurred_on||'').slice(0,7);
    if(/^\d{4}-\d{2}$/.test(month))byMonth[month]=(byMonth[month]||0)+safeCount(transaction.amount_cents);
  });
  const entries=Object.entries(byMonth).sort(([left],[right])=>left.localeCompare(right)).slice(-5),max=Math.max(...entries.map(([,total])=>Math.abs(total)),1);
  const bars=entries.map(([month,total])=>`<div class="bar-col" style="height:${Math.max(8,Math.abs(total)/max*90)}%"><strong>${escapeHtml(safeMoney(total,selectedCurrency))}</strong><span>${escapeHtml(month.slice(5))}</span></div>`).join('');
  const currencyTabs=currencies.map(currency=>`<button class="currency-tab ${currency===selectedCurrency?'active':''}" data-chart-currency="${escapeHtml(currency)}" aria-pressed="${currency===selectedCurrency}">${escapeHtml(currency)}</button>`).join('');
  const metricTotals=metrics.recorded_spending_by_currency||{},selectedTotal=selectedCurrency&&Object.hasOwn(metricTotals,selectedCurrency)?safeCount(metricTotals[selectedCurrency]):selectedTransactions.reduce((total,item)=>total+safeCount(item.amount_cents),0);
  const chartBody=bars||'<p class="empty-chart">No dated transactions are available for this currency.</p>';
  const findings=Array.isArray(state.data.findings)?state.data.findings:[];
  const changes=findings.map(finding=>`<button class="change-row" data-finding="${escapeHtml(finding.id)}"><b>${escapeHtml(finding.title)}</b><strong class="${finding.severity==='high'?'up':'down'}">${escapeHtml(String(finding.severity||'review').toUpperCase())}</strong><small>${escapeHtml(finding.summary)}</small></button>`).join('')||'<p class="empty-state">No changes currently require explanation.</p>';
  $('#changeView').innerHTML=`<div class="period-grid"><div class="chart-card"><div class="chart-title-row"><div><h4>Recorded activity by month${selectedCurrency?` · ${escapeHtml(selectedCurrency)}`:''}</h4><small>${selectedCurrency?`${escapeHtml(safeMoney(selectedTotal,selectedCurrency))} selected total · currencies are never combined`:'No transaction currency is available'}</small></div>${currencyTabs?`<div class="currency-tabs" role="group" aria-label="Chart currency">${currencyTabs}</div>`:''}</div><div class="bar-chart ${bars?'':'empty'}">${chartBody}</div></div><div class="chart-card"><h4>Changes requiring explanation</h4><div class="change-list">${changes}</div></div></div>`;
  $$('#changeView [data-chart-currency]').forEach(button=>button.onclick=()=>{state.changeCurrencyByWorkspace[state.workspace]=button.dataset.chartCurrency;renderChange()});
  $$('#changeView [data-finding]').forEach(button=>button.onclick=()=>selectFinding(button.dataset.finding));
}
function renderGeo(){const vendors=state.data.vendors.filter(v=>v.city),groups={};vendors.forEach(v=>{groups[v.city]=groups[v.city]||[];groups[v.city].push(v)});const positions={'New York':[70,35],'Austin':[46,74],'Chicago':[52,47],'Seattle':[11,22],'San Francisco':[10,57],'San Jose':[12,61],'Boston':[82,28],'Memphis':[57,67],'Atlanta':[70,70]};const points=Object.entries(groups).map(([city,items])=>{const p=positions[city]||[50,50];return `<button class="map-point" style="left:${p[0]}%;top:${p[1]}%" data-city="${city}"><span>${city} · ${items.length}</span></button>`}).join('');const list=Object.entries(groups).map(([city,items])=>`<div class="change-row"><b>${city}</b><strong>${items.length}</strong><small>${items.map(v=>v.name).join(', ')}</small></div>`).join('');$('#geoView').innerHTML=`<div class="geo-grid"><div class="map-stage">${points}</div><div class="chart-card"><h4>Evidence-backed locations</h4><div class="change-list">${list}</div></div></div>`}
function renderRecords(){if(state.workspace==='business'){const rows=state.data.security.evidence.map(e=>`<tr><td><button data-record="security:${e.id}">${e.id}</button></td><td>${escapeHtml(e.type)}</td><td>${escapeHtml(e.title)}</td><td>${escapeHtml(e.source)}</td><td>${e.as_of}</td><td>${escapeHtml(e.statement)}</td></tr>`).join('');$('#recordsView').innerHTML=`<table class="records-table"><thead><tr><th>Evidence</th><th>Type</th><th>Title</th><th>Source</th><th>As of</th><th>Observed statement</th></tr></thead><tbody>${rows}</tbody></table>`;$$('[data-record]').forEach(b=>b.onclick=()=>openRecord(b.dataset.record));return}const rows=state.data.transactions.slice(0,80).map(t=>`<tr><td><button data-record="transaction:${t.id}">${t.id}</button></td><td>${t.merchant_raw}</td><td>${money(t.amount_cents,t.currency)}</td><td>${t.occurred_on}</td><td>${t.office}</td><td>${t.source_id}</td></tr>`).join('');$('#recordsView').innerHTML=`<table class="records-table"><thead><tr><th>Record</th><th>Merchant</th><th>Amount</th><th>Date</th><th>Office</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table>`;$$('[data-record]').forEach(b=>b.onclick=()=>openRecord(b.dataset.record))}

async function openRecord(id){state.selectedId=id;try{const record=await api(`/api/records/${encodeURIComponent(id)}?workspace=${state.workspace}`);openDrawer('EVIDENCE RECORD',id,detailHtml(record));renderVisual()}catch(e){toast(e.message)}}
function detailHtml(obj){return `<div class="detail-grid">${Object.entries(obj).filter(([k])=>!k.includes('hash')).map(([k,v])=>`<div class="detail-row"><span>${escapeHtml(k.replaceAll('_',' '))}</span><strong>${escapeHtml(String(v??'Unknown'))}</strong></div>`).join('')}</div>`}
function evidenceDrawer(){const f=state.data.findings.find(x=>x.id===state.selectedFinding);if(!f)return;openDrawer('SOURCE EVIDENCE',f.title,`<div class="notice">These are references to loaded synthetic records. PayProof preserves the source rather than rewriting it.</div>${f.evidence_ids.map(e=>`<article class="evidence-card"><b>${escapeHtml(e)}</b><p>Supporting evidence for ${escapeHtml(f.entity_id)}.</p></article>`).join('')}`)}
function contextDrawer(){const c=state.lastContext||{workspace:state.workspace,selected_id:state.selectedId,evidence_ids:[],calculation:'Ask a question to populate this view.'};openDrawer('BOUNDED MODEL CONTEXT','Context used',`<div class="notice">Only the active scope, selected record, retrieved evidence, and deterministic calculation are provided to the assistant.</div>${detailHtml(c)}`)}
function importDrawer(){openDrawer('ADD FINANCIAL EVIDENCE','Import evidence',`<div class="import-zone"><b>Receipt, screenshot, or document picture</b><p>Local OCR reads PNG, JPG, JPEG, or WEBP images. You review and correct every proposed field before import.</p><input id="ocrFile" type="file" accept="image/png,image/jpeg,image/webp"><div class="modal-actions"><button id="previewOcr" class="button primary">Read image</button></div></div><div id="ocrResult"></div><div class="import-zone" style="margin-top:12px"><b>CSV transaction history</b><p>Preview and validate before committing. The example and uploaded files use the same calculation and visualization pipeline.</p><input id="importFile" type="file" accept=".csv,text/csv"><div class="modal-actions"><button id="previewImport" class="button primary">Preview CSV</button><a class="button ghost" href="/api/templates/transactions.csv">Download template</a></div></div><div id="importResult"></div>`);$('#previewImport').onclick=()=>uploadImport(false);$('#previewOcr').onclick=previewOcr}
async function previewOcr(){const file=$('#ocrFile')?.files[0];if(!file){toast('Choose a receipt or screenshot first');return}const form=new FormData();form.append('file',file);$('#ocrResult').innerHTML='<div class="notice">Reading image locally…</div>';try{const r=await api('/api/ocr/preview',{method:'POST',body:form});$('#ocrResult').innerHTML=`<div class="notice">Read ${r.line_count} text lines · average confidence ${Math.round(r.average_confidence*100)}%. Confirm or correct the fields below.</div><article class="evidence-card"><label>Merchant<input id="ocrMerchant" value="${escapeHtml(r.suggested.merchant)}"></label><label>Amount<input id="ocrAmount" value="${escapeHtml(r.suggested.amount)}" placeholder="0.00"></label><label>Currency<input id="ocrCurrency" value="${escapeHtml(r.suggested.currency)}"></label><label>Date<input id="ocrDate" type="date" value="${escapeHtml(r.suggested.date)}"></label><label>Extracted text<textarea rows="8" readonly>${escapeHtml(r.text)}</textarea></label><button id="confirmOcr" class="button primary">Confirm receipt import</button></article>`;$('#confirmOcr').onclick=()=>commitOcr(r.preview_id)}catch(e){$('#ocrResult').innerHTML=`<div class="notice">${escapeHtml(e.message)}</div>`}}
async function commitOcr(previewId){try{const r=await api('/api/ocr/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preview_id:previewId,workspace:state.workspace,merchant:$('#ocrMerchant').value,amount:$('#ocrAmount').value,currency:$('#ocrCurrency').value,date:$('#ocrDate').value})});toast(`Receipt ${r.id} imported from image`);await loadData();importDrawer()}catch(e){toast(e.message)}}
function safeCount(value){const number=Number(value);return Number.isFinite(number)?number:0}
function safeMoney(cents,currency='USD'){try{return money(safeCount(cents),String(currency||'USD'))}catch{return `${(safeCount(cents)/100).toFixed(2)} ${String(currency||'USD')}`}}
function readableTime(value){if(!value)return 'Never';const parsed=new Date(value);return Number.isNaN(parsed.getTime())?String(value):parsed.toLocaleString()}
function noticeHtml(message,tone='info'){return message?`<div class="notice ${tone}" role="status">${escapeHtml(message)}</div>`:''}
function setSourceAction(html){const target=$('#sourceAction');if(target){target.innerHTML=html;if(html)target.scrollIntoView?.({block:'nearest'})}}
function apiErrorHtml(error){
  const payload=error?.payload||{};
  const facts=[];
  if(payload.state)facts.push(`State: ${escapeHtml(payload.state)}`);
  if(typeof payload.upstream_connection_revoked==='boolean')facts.push(`Upstream connection revoked: ${payload.upstream_connection_revoked?'yes':'no'}`);
  if(typeof payload.upstream_authorization_revoked==='boolean')facts.push(`Google authorization revoked: ${payload.upstream_authorization_revoked?'yes':'no'}`);
  if(typeof payload.local_token_deleted==='boolean')facts.push(`Local protected token deleted: ${payload.local_token_deleted?'yes':'no'}`);
  if(payload.retry_local_cleanup===true)facts.push('Local cleanup still needs a retry.');
  if(payload.safe_retry===true)facts.push('The server reports that retrying is safe.');
  const serverErrors=Array.isArray(payload.errors)?payload.errors:[];
  return `<div class="notice error" role="alert"><b>${escapeHtml(error?.message||'Request failed')}</b>${facts.length?`<ul>${facts.map(item=>`<li>${item}</li>`).join('')}</ul>`:''}${serverErrors.length?`<ul>${serverErrors.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`:''}</div>`;
}
function affectedHtml(affected){
  const entries=Object.entries(affected||{});
  return entries.length?`<dl class="impact-list">${entries.map(([key,value])=>`<div><dt>${escapeHtml(key.replaceAll('_',' '))}</dt><dd>${escapeHtml(typeof value==='boolean'?(value?'yes':'no'):value)}</dd></div>`).join('')}</dl>`:'<p class="empty-state">No local records are currently affected.</p>';
}
function bankConnectionHtml(connection){
  const id=escapeHtml(connection.id);
  const masks=Array.isArray(connection.account_masks)&&connection.account_masks.length?connection.account_masks.map(mask=>`ending ${escapeHtml(mask)}`).join(', '):'Account details will appear after sync';
  const connected=connection.state==='connected';
  return `<article class="source-card compact"><div class="source-card-head"><div><b>${escapeHtml(connection.institution||'Connected institution')}</b><span class="status-chip ${connected?'good':'warn'}">${escapeHtml(connection.state||'connected')}</span></div></div><p>${masks}</p><p class="source-meta">Last sync: ${escapeHtml(readableTime(connection.last_synced_at))}</p><div class="modal-actions"><button class="button ghost bank-sync" data-bank-id="${id}" ${connected?'':'disabled'}>Sync now</button><button class="button danger bank-disconnect" data-bank-id="${id}">${connected?'Disconnect':'Finish disconnect'}</button></div></article>`;
}
function reconciliationHtml(reconciliation){
  const summary=reconciliation?.summary||{},rows=Array.isArray(reconciliation?.rows)?reconciliation.rows:[];
  const suggested=rows.filter(row=>Array.isArray(row.matches)&&row.matches.length).slice(0,6);
  const details=suggested.map(row=>{const bank=row.bank_transaction||{},match=row.matches[0]||{};return `<div class="match-row"><span>${escapeHtml(bank.description||bank.id)}</span><strong>${escapeHtml(match.type||'evidence')} · ${escapeHtml(match.evidence_id||'unknown')} · ${safeCount(match.confidence)}%</strong></div>`}).join('');
  return `<details class="reconciliation-box"><summary><span>Evidence matching</span><b>${safeCount(summary.with_suggestions)} suggested · ${safeCount(summary.unmatched)} unmatched</b></summary><p>Bank rows are compared with invoices, receipts, intake expenses, and imported email. Matches are suggestions and are never confirmed automatically.</p>${details||'<p class="empty-state">No suggested evidence matches yet.</p>'}</details>`;
}
function importedSourceHtml(source){
  const id=escapeHtml(source.id),kind=String(source.kind||'source');
  const removalCopy=kind==='gmail'?'Remove imported Gmail evidence from this workspace. This does not disconnect Gmail.':'Remove this imported source and recalculate the workspace.';
  return `<article class="source-card compact"><div class="source-card-head"><b>${escapeHtml(source.label||source.id)}</b><span class="status-chip">${escapeHtml(kind)} · ${safeCount(source.record_count)} records</span></div><p>${removalCopy}</p><button class="button danger remove-source" data-source-id="${id}">Preview removal</button></article>`;
}
function intakeExpenseHtml(expense){
  return `<article class="intake-row"><div><b>${escapeHtml(expense.id)}</b><span>${escapeHtml(expense.merchant)} · ${escapeHtml(safeMoney(expense.amount_cents,expense.currency))}</span><small>${escapeHtml(expense.spent_on)} · ${escapeHtml(expense.receipt_status)} · ${escapeHtml(expense.approval_status)}</small></div><button class="button ghost edit-intake" data-expense-id="${escapeHtml(expense.id)}">Edit & history</button></article>`;
}
function companyManagerHtml(workspaces,current){
  const options=workspaces.map(workspace=>`<option value="${escapeHtml(workspace.id)}" ${workspace.id===state.workspace?'selected':''}>${escapeHtml(workspace.name)}${workspace.is_demo?' · demo':''}</option>`).join('');
  const custom=current?.kind==='company'&&current?.is_demo!==true;
  return `<section class="settings-section company-manager" aria-labelledby="companySettingsTitle">
    <div class="settings-heading"><div><span class="section-label">ACTIVE COMPANY</span><h3 id="companySettingsTitle">Company manager</h3></div><span class="status-chip ${custom?'good':''}">${custom?'custom company':'demo workspace'}</span></div>
    <p>Banks, Gmail authorization, statement imports, and intake folders connect only to the company selected here. Switching companies clears the visible chat context before loading the next company.</p>
    <div class="company-switcher"><label>Selected company<select id="settingsWorkspaceSelect">${options}</select></label><button id="switchSettingsWorkspace" class="button primary" disabled>Switch company</button></div>
    <dl class="company-counts"><div><dt>Bank records</dt><dd>${safeCount(current?.bank_transaction_count)}</dd></div><div><dt>Gmail evidence</dt><dd>${safeCount(current?.gmail_evidence_count)}</dd></div><div><dt>Enabled intake folders</dt><dd>${safeCount(current?.intake_folder_count)}</dd></div></dl>
    ${custom?`<form id="renameCompanyForm" class="inline-settings-form"><label>Company name<input name="name" minlength="2" maxlength="100" required value="${escapeHtml(current.name)}"></label><button class="button ghost" type="submit">Rename</button></form>`:''}
    <details class="add-company"><summary>Add another company</summary><form id="createCompanyForm" class="inline-settings-form"><label>New company name<input name="name" minlength="2" maxlength="100" required placeholder="Example: Northstar Studio"></label><button class="button primary" type="submit">Create & select</button></form></details>
  </section>`;
}
function intakeFolderHtml(folder){
  const id=escapeHtml(folder.id),enabled=folder.enabled===true;
  return `<article class="folder-card ${enabled?'':'disabled-source'}"><div class="source-card-head"><div><b>${escapeHtml(folder.label||'Intake folder')}</b><div class="folder-badges"><span class="status-chip ${enabled?'good':'warn'}">${enabled?'enabled':'paused'}</span><span class="status-chip">${folder.include_subfolders?'includes subfolders':'top folder only'}</span>${folder.is_default?'<span class="status-chip">built in</span>':''}</div></div></div><code class="folder-path">${escapeHtml(folder.path)}</code><div class="modal-actions"><button class="button ghost scan-folder" data-folder-id="${id}" ${enabled?'':'disabled'}>Scan this folder</button><button class="button ghost edit-folder" data-folder-id="${id}">Edit settings</button><button class="button ${enabled?'amber':'primary'} toggle-folder" data-folder-id="${id}">${enabled?'Disable':'Enable'}</button>${folder.is_default?'':`<button class="button danger remove-folder" data-folder-id="${id}">Remove assignment</button>`}</div>${folder.is_default?'<p class="source-meta">The built-in assignment can be disabled, but its path cannot be changed or removed.</p>':''}</article>`;
}
async function sourcesDrawer(message='',tone='success'){
  const workspace=state.workspace,generation=++state.sourceGeneration;
  const [s,workspaceResult,folderResult]=await Promise.all([
    api(`/api/sources?workspace=${encodeURIComponent(workspace)}`),
    api('/api/workspaces'),
    api(`/api/workspaces/${encodeURIComponent(workspace)}/intake-folders`)
  ]);
  if(workspace!==state.workspace||generation!==state.sourceGeneration)return;
  state.bankPreview=null;
  const bank=s.bank||{},gmail=s.gmail||{},connections=Array.isArray(bank.connections)?bank.connections:[];
  const workspaces=Array.isArray(workspaceResult.workspaces)?workspaceResult.workspaces:[],currentWorkspace=workspaces.find(item=>item.id===workspace)||{id:workspace,name:workspace,kind:'company',is_demo:false};
  const folders=Array.isArray(folderResult.folders)?folderResult.folders:[],enabledFolders=folders.filter(folder=>folder.enabled===true);
  state.sourceConfig={...s,workspaces,intakeFolders:folders,currentWorkspace};
  const bankReady=bank.configuration_state==='server_credentials_configured'&&bank.connector_implemented===true&&!bank.connection_store_error;
  const gmailReady=gmail.credentials_available===true&&gmail.secure_token_storage!=='unavailable';
  let bankReadiness=`Plaid ${escapeHtml(bank.environment||'server')} environment is ready. PayProof never asks for or receives your bank password.`;
  if(bank.configuration_state!=='server_credentials_configured')bankReadiness='Live bank connection is not configured on this server. Add Plaid credentials to the server environment; never enter them in this browser.';
  else if(bank.connector_implemented!==true)bankReadiness='Live bank connection is unavailable because OS-protected token storage is not supported on this server.';
  else if(bank.connection_store_error)bankReadiness=`The protected connection store could not be read: ${escapeHtml(bank.connection_store_error)}`;
  const intakeExpenses=(state.data?.expenses||[]).filter(item=>String(item.source_id||'').startsWith('intake:'));
  const imported=Array.isArray(s.imports)&&s.imports.length?s.imports.map(importedSourceHtml).join(''):'<p class="empty-state">No removable imported sources in this workspace.</p>';
  const liveConnections=connections.length?connections.map(bankConnectionHtml).join(''):'<p class="empty-state">No live bank connection is attached to this workspace.</p>';
  const intakeRows=intakeExpenses.length?intakeExpenses.map(intakeExpenseHtml).join(''):'<p class="empty-state">No intake expense records are loaded in this workspace.</p>';
  const folderRows=folders.length?folders.map(intakeFolderHtml).join(''):'<p class="empty-state">No intake folder is assigned to this company yet.</p>';
  openDrawer('CONNECTIONS & AUDIT','Sources & settings',`
    ${noticeHtml(message,tone)}
    <div class="settings-intro"><p>Connect records, review every preview, and manage only <b>${escapeHtml(currentWorkspace.name)}</b>. Credentials and provider tokens stay server-side.</p><button id="refreshSources" class="button ghost">Refresh status</button></div>
    <div id="sourceAction" class="source-action" aria-live="polite"></div>
    ${companyManagerHtml(workspaces,currentWorkspace)}
    <section class="settings-section" aria-labelledby="bankSettingsTitle">
      <div class="settings-heading"><div><span class="section-label">BANK RECORDS</span><h3 id="bankSettingsTitle">Bank connections</h3></div><span class="status-chip ${bankReady?'good':'warn'}">${bankReady?'ready':'not configured'}</span></div>
      <p>${bankReadiness}</p>
      <div class="modal-actions"><button id="connectBank" class="button primary" ${bankReady?'':'disabled'}>${connections.length?'Connect another bank':'Connect bank with Plaid'}</button></div>
      <div class="source-stack">${liveConnections}</div>
      ${reconciliationHtml(state.data?.reconciliation)}
      <div class="settings-subsection">
        <b>Import a local statement</b>
        <p>CSV, OFX, and QFX files are parsed locally by PayProof. Rows and validation errors appear before any records are committed.</p>
        <label class="file-field">Bank statement<input id="bankStatementFile" type="file" accept=".csv,.ofx,.qfx,text/csv,application/x-ofx"></label>
        <div class="modal-actions"><button id="previewBankStatement" class="button ghost">Preview statement</button><a class="button ghost" href="/api/templates/bank.csv">Download CSV template</a></div>
        <div id="bankStatementResult" aria-live="polite"></div>
      </div>
    </section>
    <section class="settings-section" aria-labelledby="gmailSettingsTitle">
      <div class="settings-heading"><div><span class="section-label">EMAIL EVIDENCE</span><h3 id="gmailSettingsTitle">Gmail</h3></div><span class="status-chip ${gmail.connected?'good':gmailReady?'':'warn'}">${gmail.connected?'connected':gmailReady?'ready':'not configured'}</span></div>
      <p>Read-only access imports message metadata and short snippets. PayProof does not import attachments or full message bodies.</p>
      ${gmail.credentials_available?'':noticeHtml('Google OAuth client configuration is missing on the server. Gmail connect is disabled.','warning')}
      ${gmail.credentials_available&&gmail.secure_token_storage==='unavailable'?noticeHtml('Gmail connect is disabled because this server cannot use OS-protected token storage. No plaintext fallback is used.','warning'):''}
      ${gmail.legacy_plaintext_token_detected?noticeHtml('A legacy plaintext Gmail token file was detected. PayProof will not use it; remove it from the runtime folder.','error'):''}
      <label>Search query<input id="gmailQuery" value="newer_than:365d (from:amazon.com OR category:purchases)" ${gmail.connected?'':'disabled'}></label>
      <label>Maximum messages<select id="gmailMaxResults" ${gmail.connected?'':'disabled'}><option>10</option><option selected>20</option><option>50</option></select></label>
      <div class="modal-actions"><button id="gmailConnect" class="button ${gmail.connected?'ghost':'primary'}" ${gmailReady?'':'disabled'}>${gmail.connected?'Reconnect Gmail':'Connect Gmail'}</button><button id="gmailImport" class="button primary" ${gmail.connected?'':'disabled'}>Import matching email</button>${gmail.connected?'<button id="gmailDisconnect" class="button danger">Preview disconnect</button>':''}</div>
    </section>
    <section class="settings-section" aria-labelledby="intakeSettingsTitle">
      <div class="settings-heading"><div><span class="section-label">LOCAL INTAKE</span><h3 id="intakeSettingsTitle">Expense intake</h3></div><span class="status-chip ${enabledFolders.length?'good':'warn'}">${enabledFolders.length} enabled</span></div>
      <p>Assign existing folders on this PayProof computer to <b>${escapeHtml(currentWorkspace.name)}</b>. Each scan imports only that company’s JSON paperwork. Folder removal preserves source files, imported records, and edit history.</p>
      <div class="modal-actions"><button id="scanAllIntake" class="button primary" ${enabledFolders.length?'':'disabled'}>Scan all enabled folders</button><a class="button ghost" href="/api/templates/intake.json">View JSON template</a></div>
      <div class="folder-list">${folderRows}</div>
      <details class="add-folder"><summary>Add intake folder</summary><form id="addIntakeFolderForm" class="compact-form folder-form"><label>Folder path on this computer<input name="path" required maxlength="1000" placeholder="C:\\Company\\Expense intake" autocomplete="off"></label><label>Label <span class="source-meta">optional</span><input name="label" maxlength="100" placeholder="Accounts payable"></label><label class="check-field"><input name="include_subfolders" type="checkbox"> Include JSON files in subfolders</label><button class="button primary" type="submit">Assign folder to this company</button></form></details>
      <div class="settings-subsection"><b>Loaded intake expenses</b><p>Use audited edits for corrections. Originals and all prior versions remain preserved.</p></div>
      <div class="intake-list">${intakeRows}</div>
    </section>
    <section class="settings-section" aria-labelledby="importedSettingsTitle">
      <div class="settings-heading"><div><span class="section-label">DATA LIFECYCLE</span><h3 id="importedSettingsTitle">Imported sources</h3></div></div>
      <p>Removal always shows its local impact first. Removing evidence never deletes data at Gmail or your bank.</p>
      <div class="source-stack">${imported}</div>
    </section>
  `);
  bindSourceActions();
}
function bindSourceActions(){
  $('#refreshSources').onclick=()=>sourcesDrawer('Connection status refreshed.','info').catch(error=>setSourceAction(apiErrorHtml(error)));
  const settingsWorkspace=$('#settingsWorkspaceSelect'),switchWorkspaceButton=$('#switchSettingsWorkspace');
  settingsWorkspace.onchange=()=>{switchWorkspaceButton.disabled=settingsWorkspace.value===state.workspace};
  switchWorkspaceButton.onclick=()=>switchWorkspace(settingsWorkspace.value,settingsWorkspace.selectedOptions[0]?.textContent||settingsWorkspace.value,true);
  const createCompanyForm=$('#createCompanyForm');if(createCompanyForm)createCompanyForm.onsubmit=createCompany;
  const renameCompanyForm=$('#renameCompanyForm');if(renameCompanyForm)renameCompanyForm.onsubmit=renameCompany;
  const connectBank=$('#connectBank');if(connectBank&&!connectBank.disabled)connectBank.onclick=startPlaidConnect;
  $$('.bank-sync').forEach(button=>button.onclick=()=>syncBankConnection(button.dataset.bankId,button));
  $$('.bank-disconnect').forEach(button=>button.onclick=()=>previewBankDisconnect(button.dataset.bankId));
  $('#previewBankStatement').onclick=previewBankStatement;
  const gmailConnect=$('#gmailConnect');if(gmailConnect&&!gmailConnect.disabled)gmailConnect.onclick=openGmailConnect;
  const gmailImport=$('#gmailImport');if(gmailImport&&!gmailImport.disabled)gmailImport.onclick=importGmailEvidence;
  const gmailDisconnect=$('#gmailDisconnect');if(gmailDisconnect)gmailDisconnect.onclick=previewGmailDisconnect;
  const scanAllIntake=$('#scanAllIntake');if(scanAllIntake&&!scanAllIntake.disabled)scanAllIntake.onclick=()=>scanIntakeFolder();
  const addIntakeFolderForm=$('#addIntakeFolderForm');if(addIntakeFolderForm)addIntakeFolderForm.onsubmit=addIntakeFolder;
  $$('.scan-folder').forEach(button=>button.onclick=()=>scanIntakeFolder(button.dataset.folderId));
  $$('.edit-folder').forEach(button=>button.onclick=()=>openIntakeFolderEditor(button.dataset.folderId));
  $$('.toggle-folder').forEach(button=>button.onclick=()=>toggleIntakeFolder(button.dataset.folderId,button));
  $$('.remove-folder').forEach(button=>button.onclick=()=>previewIntakeFolderRemoval(button.dataset.folderId));
  $$('.edit-intake').forEach(button=>button.onclick=()=>openIntakeEditor(button.dataset.expenseId));
  $$('.remove-source').forEach(button=>button.onclick=()=>previewImportedSourceRemoval(button.dataset.sourceId));
}
function cancelActivePlaid(){
  const handler=state.activePlaidHandler;
  if(!handler)return;
  state.activePlaidHandler=null;
  try{handler.exit({force:true})}catch{}
  try{handler.destroy()}catch{}
}
function resetWorkspaceContext(workspace){
  state.selectedFinding=workspace==='business'?'F-ROUTE-001':null;
  state.selectedId=null;
  state.lastContext=null;
  state.bankPreview=null;
  const selection=$('#selectionCard');if(selection){selection.style.display='none';selection.replaceChildren()}
  const chat=$('#chatLog');if(chat)chat.replaceChildren();
}
async function switchWorkspace(workspaceId,label=workspaceId,reopenSources=false,message=''){
  const nextWorkspace=String(workspaceId||'').trim();
  if(!nextWorkspace)return false;
  const companyLabel=String(label||nextWorkspace).replace(/\s+\S+\s+demo\s*$/i,'').trim()||nextWorkspace;
  if(nextWorkspace===state.workspace){
    if(reopenSources){
      try{await sourcesDrawer(message||`${companyLabel} is already selected.`,'info')}catch(error){setSourceAction(apiErrorHtml(error))}
    }
    return true;
  }
  const previousWorkspace=state.workspace,transition=++state.workspaceGeneration;
  cancelActivePlaid();
  state.sourceGeneration+=1;
  state.workspace=nextWorkspace;
  state.sourceConfig=null;
  resetWorkspaceContext(nextWorkspace);
  if(reopenSources)openDrawer('CONNECTIONS & AUDIT','Switching company',noticeHtml(`Loading ${companyLabel} without carrying over the previous company context...`,'info'));
  else closeDrawer();
  try{
    const loaded=await loadData();
    if(!loaded||state.workspace!==nextWorkspace||transition!==state.workspaceGeneration)return false;
  }catch(error){
    if(state.workspace!==nextWorkspace||transition!==state.workspaceGeneration)return false;
    state.workspace=previousWorkspace;
    state.sourceConfig=null;
    resetWorkspaceContext(previousWorkspace);
    try{await loadData()}catch{}
    addMessage('assistant',`I could not switch to ${companyLabel}: ${error.message}. The previous company is active again.`);
    if(reopenSources){
      try{await sourcesDrawer(`Could not switch to ${companyLabel}: ${error.message}`,'error')}catch{openDrawer('CONNECTIONS & AUDIT','Sources & settings',apiErrorHtml(error))}
    }else toast(`Could not switch company: ${error.message}`);
    return false;
  }
  addMessage('assistant',`Switched to ${companyLabel}. I will answer only from this company.`);
  if(reopenSources){
    try{await sourcesDrawer(message||`Now managing sources for ${companyLabel}.`,'success')}catch(error){openDrawer('CONNECTIONS & AUDIT','Sources & settings',apiErrorHtml(error))}
  }else toast(`Switched to ${companyLabel}`);
  return true;
}
async function createCompany(event){
  event.preventDefault();
  const form=event.currentTarget,submit=form.querySelector('[type="submit"]'),originWorkspace=state.workspace;
  const name=String(new FormData(form).get('name')||'').trim();
  if(name.length<2){setSourceAction(noticeHtml('Enter a company name with at least 2 characters.','error'));return}
  submit.disabled=true;setSourceAction(noticeHtml(`Creating ${name} as a separate company...`,'info'));
  try{
    const result=await api('/api/workspaces',jsonRequest('POST',{name}));
    const company=result.workspace||result.company||result;
    if(!company?.id)throw new Error('The server created the company but did not return its identifier.');
    if(state.workspace!==originWorkspace){toast(`${company.name||name} was created. Select it from the company menu when ready.`);return}
    await switchWorkspace(company.id,company.name||name,true,`Created ${company.name||name}. Bank, Gmail, and intake sources can now be attached to this company.`);
  }catch(error){if(state.workspace===originWorkspace)setSourceAction(apiErrorHtml(error));else toast(`Company creation failed: ${error.message}`)}
  finally{if(submit.isConnected)submit.disabled=false}
}
async function renameCompany(event){
  event.preventDefault();
  const form=event.currentTarget,submit=form.querySelector('[type="submit"]'),workspace=state.workspace;
  const current=state.sourceConfig?.currentWorkspace;
  if(!current||current.kind!=='company'||current.is_demo===true){setSourceAction(noticeHtml('Built-in demo workspaces cannot be renamed.','warning'));return}
  const name=String(new FormData(form).get('name')||'').trim();
  if(name.length<2){setSourceAction(noticeHtml('Enter a company name with at least 2 characters.','error'));return}
  if(name===current.name){setSourceAction(noticeHtml('Enter a different company name before saving.','warning'));return}
  submit.disabled=true;setSourceAction(noticeHtml('Renaming this company...','info'));
  try{
    const result=await api(`/api/workspaces/${encodeURIComponent(workspace)}`,jsonRequest('PATCH',{name}));
    if(state.workspace!==workspace){toast(`${result.name||name} was renamed.`);return}
    await loadData();
    if(state.workspace!==workspace)return;
    await sourcesDrawer(`Company renamed to ${result.name||name}. Its connected sources and imported records stayed attached.`,'success');
  }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Company rename failed: ${error.message}`)}
  finally{if(submit.isConnected)submit.disabled=false}
}
function configuredIntakeFolder(folderId){
  return (state.sourceConfig?.intakeFolders||[]).find(folder=>String(folder.id)===String(folderId));
}
async function addIntakeFolder(event){
  event.preventDefault();
  const form=event.currentTarget,submit=form.querySelector('[type="submit"]'),workspace=state.workspace,data=new FormData(form);
  const path=String(data.get('path')||'').trim(),label=String(data.get('label')||'').trim(),includeSubfolders=form.elements.include_subfolders.checked;
  if(!path){setSourceAction(noticeHtml('Enter an existing folder path on this computer.','error'));return}
  submit.disabled=true;setSourceAction(noticeHtml('Checking the folder and assigning it only to this company...','info'));
  try{
    const payload={path,include_subfolders:includeSubfolders};if(label)payload.label=label;
    const result=await api(`/api/workspaces/${encodeURIComponent(workspace)}/intake-folders`,jsonRequest('POST',payload));
    if(state.workspace!==workspace){toast(`The intake folder was assigned to ${workspace}.`);return}
    const folder=result.folder||result;
    await sourcesDrawer(`Assigned ${folder.label||label||'the intake folder'} to this company. No files were moved or deleted.`,'success');
  }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Folder assignment failed: ${error.message}`)}
  finally{if(submit.isConnected)submit.disabled=false}
}
function openIntakeFolderEditor(folderId){
  const folder=configuredIntakeFolder(folderId);
  if(!folder){setSourceAction(noticeHtml('That intake-folder assignment is no longer available. Refresh and try again.','warning'));return}
  setSourceAction(`<div class="confirmation-card"><span class="section-label">INTAKE FOLDER SETTINGS</span><h3>${escapeHtml(folder.label||'Intake folder')}</h3><p class="source-meta">Folder path is shown for reference and is not changed by this form.</p><code class="folder-path">${escapeHtml(folder.path)}</code><form id="editIntakeFolderForm" class="compact-form folder-editor-form"><label>Folder label<input name="label" required maxlength="100" value="${escapeHtml(folder.label||'Intake folder')}"></label><label class="check-field"><input name="include_subfolders" type="checkbox" ${folder.include_subfolders?'checked':''}> Include JSON files in subfolders</label><label class="check-field"><input name="enabled" type="checkbox" ${folder.enabled?'checked':''}> Enable this folder for scans</label>${folder.is_default?'<div class="notice info">This is the built-in assignment. Its label and scan settings can change, but its path cannot be changed or removed.</div>':''}<div class="modal-actions"><button class="button primary" type="submit">Save folder settings</button><button id="cancelFolderEdit" class="button ghost" type="button">Cancel</button></div><div id="folderEditResult" aria-live="polite"></div></form></div>`);
  $('#cancelFolderEdit').onclick=()=>setSourceAction('');
  $('#editIntakeFolderForm').onsubmit=async event=>{
    event.preventDefault();
    const form=event.currentTarget,submit=form.querySelector('[type="submit"]'),resultTarget=$('#folderEditResult'),workspace=state.workspace;
    const label=String(new FormData(form).get('label')||'').trim(),includeSubfolders=form.elements.include_subfolders.checked,enabled=form.elements.enabled.checked,changes={};
    if(!label){resultTarget.innerHTML=noticeHtml('Enter a folder label.','error');return}
    if(label!==String(folder.label||''))changes.label=label;
    if(includeSubfolders!==(folder.include_subfolders===true))changes.include_subfolders=includeSubfolders;
    if(enabled!==(folder.enabled===true))changes.enabled=enabled;
    if(!Object.keys(changes).length){resultTarget.innerHTML=noticeHtml('Change at least one folder setting before saving.','warning');return}
    submit.disabled=true;resultTarget.innerHTML=noticeHtml('Saving folder settings...','info');
    try{
      const saved=await api(`/api/workspaces/${encodeURIComponent(workspace)}/intake-folders/${encodeURIComponent(folder.id)}`,jsonRequest('PATCH',changes));
      if(state.workspace!==workspace){toast(`Folder settings were updated in ${workspace}.`);return}
      await sourcesDrawer(`Saved settings for ${(saved.folder||saved).label||label}. Existing files and imported records were unchanged.`,'success');
    }catch(error){if(state.workspace===workspace){resultTarget.innerHTML=apiErrorHtml(error);submit.disabled=false}else toast(`Folder update failed: ${error.message}`)}
  };
}
async function toggleIntakeFolder(folderId,button){
  const folder=configuredIntakeFolder(folderId),workspace=state.workspace;
  if(!folder){setSourceAction(noticeHtml('That intake-folder assignment is no longer available.','warning'));return}
  button.disabled=true;setSourceAction(noticeHtml(`${folder.enabled?'Disabling':'Enabling'} ${folder.label||'the intake folder'}...`,'info'));
  try{
    await api(`/api/workspaces/${encodeURIComponent(workspace)}/intake-folders/${encodeURIComponent(folder.id)}`,jsonRequest('PATCH',{enabled:folder.enabled!==true}));
    if(state.workspace!==workspace){toast(`Folder scan status changed in ${workspace}.`);return}
    await sourcesDrawer(`${folder.label||'The intake folder'} is now ${folder.enabled?'disabled':'enabled'}. Existing files and imported records were unchanged.`,'success');
  }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Folder update failed: ${error.message}`);if(button.isConnected)button.disabled=false}
}
function previewIntakeFolderRemoval(folderId){
  const folder=configuredIntakeFolder(folderId),workspace=state.workspace;
  if(!folder){setSourceAction(noticeHtml('That intake-folder assignment is no longer available.','warning'));return}
  if(folder.is_default){setSourceAction(noticeHtml('The built-in intake assignment cannot be removed. Disable it instead.','warning'));return}
  setSourceAction(`<div class="confirmation-card"><span class="section-label">REMOVE FOLDER ASSIGNMENT</span><h3>${escapeHtml(folder.label||'Intake folder')}</h3><code class="folder-path">${escapeHtml(folder.path)}</code><div class="notice warning"><b>Only this company-to-folder assignment will be removed.</b> Source files will not be deleted, and already imported records plus their edit history will be preserved.</div><div class="modal-actions"><button id="confirmFolderRemoval" class="button danger">Confirm assignment removal</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
  $('#cancelSourceAction').onclick=()=>setSourceAction('');
  $('#confirmFolderRemoval').onclick=async event=>{
    event.currentTarget.disabled=true;
    try{
      const result=await api(`/api/workspaces/${encodeURIComponent(workspace)}/intake-folders/${encodeURIComponent(folder.id)}`,jsonRequest('DELETE',{confirm:true}));
      if(state.workspace!==workspace){toast(`The folder assignment was removed from ${workspace}.`);return}
      const preserved=result.files_deleted===false&&result.imported_records_preserved===true;
      await sourcesDrawer(preserved?`Removed the ${folder.label||'intake folder'} assignment. Files were not deleted and imported records were preserved.`:'The folder assignment was removed, but the server returned an unexpected preservation status.',preserved?'success':'warning');
    }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Folder removal failed: ${error.message}`)}
  };
}
async function startPlaidConnect(){
  const workspace=state.workspace,sessionId=state.sessionId;
  const button=$('#connectBank');if(button)button.disabled=true;
  setSourceAction(noticeHtml('Preparing a secure Plaid Link session…','info'));
  try{
    if(!window.Plaid||typeof window.Plaid.create!=='function')throw new Error('Plaid Link did not load. Check this computer’s network access and try again.');
    const tokenResult=await api('/api/sources/bank/link-token',jsonRequest('POST',{workspace,session_id:sessionId}));
    if(!tokenResult.link_token)throw new Error('The server did not return a Plaid Link token.');
    let completed=false;
    const handler=window.Plaid.create({
      token:tokenResult.link_token,
      onSuccess:async(publicToken,metadata)=>{
        completed=true;
        if(state.workspace!==workspace){setSourceAction(noticeHtml('The active workspace changed. This Plaid authorization was not exchanged; start again in the intended workspace.','warning'));handler.destroy();return}
        setSourceAction(noticeHtml('Bank authorized. Saving the protected connection and starting the first sync…','info'));
        try{
          const connection=await api('/api/sources/bank/exchange',jsonRequest('POST',{workspace,public_token:publicToken,institution:metadata?.institution?.name||''}));
          try{
            const sync=await api(`/api/sources/bank/${encodeURIComponent(connection.id)}/sync`,jsonRequest('POST',{workspace}));
            if(state.workspace!==workspace){toast(`Bank connected and synced for ${workspace}.`);return}
            await loadData();
            await sourcesDrawer(`Bank connected. Sync added ${safeCount(sync.added)}, updated ${safeCount(sync.updated)}, and removed ${safeCount(sync.removed)} record(s).`,'success');
          }catch(syncError){
            await sourcesDrawer('The bank connection was saved, but its first sync did not fully complete.','warning');
            setSourceAction(apiErrorHtml(syncError));
          }
        }catch(error){setSourceAction(apiErrorHtml(error))}
        finally{handler.destroy();if(state.activePlaidHandler===handler)state.activePlaidHandler=null}
      },
      onExit:(linkError)=>{
        if(!completed)setSourceAction(linkError?`<div class="notice error" role="alert">${escapeHtml(linkError.display_message||linkError.error_message||'Plaid Link closed with an error.')}</div>`:noticeHtml('Bank connection canceled. No connection was added.','info'));
        handler.destroy();if(state.activePlaidHandler===handler)state.activePlaidHandler=null;
        if(button)button.disabled=false;
      }
    });
    state.activePlaidHandler=handler;
    handler.open();
  }catch(error){setSourceAction(apiErrorHtml(error));if(button)button.disabled=false}
}
async function syncBankConnection(connectionId,button){
  const workspace=state.workspace;
  button.disabled=true;setSourceAction(noticeHtml('Syncing bank transactions…','info'));
  try{
    const result=await api(`/api/sources/bank/${encodeURIComponent(connectionId)}/sync`,jsonRequest('POST',{workspace}));
    if(state.workspace!==workspace){toast(`Bank sync finished for ${workspace}.`);return}
    await loadData();
    await sourcesDrawer(`Bank sync finished: ${safeCount(result.added)} added, ${safeCount(result.updated)} updated, ${safeCount(result.removed)} removed, and ${safeCount(result.pending_skipped)} pending skipped.`,'success');
  }catch(error){setSourceAction(apiErrorHtml(error));button.disabled=false}
}
async function previewBankDisconnect(connectionId){
  const workspace=state.workspace,sessionId=state.sessionId;
  setSourceAction(noticeHtml('Calculating disconnect impact…','info'));
  try{
    const params=new URLSearchParams({workspace,session_id:sessionId});
    const preview=await api(`/api/sources/bank/${encodeURIComponent(connectionId)}/disconnect-preview?${params}`);
    if(state.workspace!==workspace)return;
    setSourceAction(`<div class="confirmation-card"><span class="section-label">DISCONNECT PREVIEW</span><h3>${escapeHtml(preview.connection?.institution||'Bank connection')}</h3>${affectedHtml(preview.affected)}<div class="notice warning">Confirming revokes the upstream Plaid connection and deletes PayProof’s protected local token. Imported bank records and reconciliation links remain preserved.</div><div class="modal-actions"><button id="confirmBankDisconnect" class="button danger">Confirm disconnect</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
    $('#cancelSourceAction').onclick=()=>setSourceAction('');
    $('#confirmBankDisconnect').onclick=async event=>{
      event.currentTarget.disabled=true;
      try{
        const result=await api(`/api/sources/bank/${encodeURIComponent(connectionId)}`,jsonRequest('DELETE',{workspace,session_id:sessionId,preview_id:preview.preview_id,confirm:true}));
        if(state.workspace!==workspace){toast(`Bank disconnect finished for ${workspace}.`);return}
        await sourcesDrawer(result.disconnected?'Bank disconnected. Imported records were preserved.':'The server did not confirm that the bank was disconnected.',result.disconnected?'success':'warning');
      }catch(error){
        if(error.payload?.upstream_connection_revoked){await sourcesDrawer('Plaid revoked the upstream connection, but local cleanup is incomplete. Retry the disconnect to finish cleanup.','warning')}
        setSourceAction(apiErrorHtml(error));
      }
    };
  }catch(error){setSourceAction(apiErrorHtml(error))}
}
function bankPreviewRows(result){
  const accepted=Array.isArray(result?.accepted)?result.accepted:[],rejected=Array.isArray(result?.rejected)?result.rejected:[],errors=Array.isArray(result?.errors)?result.errors:[];
  const allErrors=[...errors.map(item=>String(item)),...rejected.map(item=>`Line ${safeCount(item.line)}: ${String(item.reason||'Rejected row')}`)],errorList=allErrors.slice(0,20);
  const rows=accepted.slice(0,30).map(item=>`<tr><td>${safeCount(item.line)}</td><td>${escapeHtml(item.posted_on)}</td><td>${escapeHtml(item.description)}</td><td>${escapeHtml(safeMoney(item.amount_cents,item.currency))}</td><td>${escapeHtml(item.direction)}</td><td>${Array.isArray(item.matches)&&item.matches.length?`${item.matches.length} suggested`:'unmatched'}</td></tr>`).join('');
  return `<div class="preview-summary"><b>${accepted.length} valid row(s)</b><span>${rejected.length} rejected · ${errors.length} file error(s)</span></div>${errorList.length?`<div class="notice error"><ul>${errorList.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>${allErrors.length>20?`<p>Showing 20 of ${allErrors.length} issues.</p>`:''}</div>`:''}${accepted.length?`<div class="table-scroll"><table class="preview-table"><thead><tr><th>Line</th><th>Date</th><th>Description</th><th>Amount</th><th>Direction</th><th>Evidence match</th></tr></thead><tbody>${rows}</tbody></table></div>${accepted.length>30?`<p class="source-meta">Showing 30 of ${accepted.length} valid rows.</p>`:''}`:'<p class="empty-state">No valid rows are available to import.</p>'}`;
}
async function previewBankStatement(){
  const file=$('#bankStatementFile')?.files[0],resultTarget=$('#bankStatementResult');
  if(!file){toast('Choose a CSV, OFX, or QFX bank statement first');return}
  const workspace=state.workspace;
  state.bankPreview=null;resultTarget.innerHTML=noticeHtml('Reading and validating the statement…','info');
  const form=new FormData();form.append('file',file);form.append('workspace',workspace);
  try{
    const result=await api('/api/import/bank/preview',{method:'POST',body:form});
    if(state.workspace!==workspace)return;
    state.bankPreview={previewId:result.preview_id,workspace,filename:file.name};
    resultTarget.innerHTML=`${bankPreviewRows(result)}${result.preview_id&&result.accepted?.length?'<div class="notice warning">Nothing has been imported yet. Confirm only after reviewing the rows and rejected-line messages above.</div><button id="commitBankStatement" class="button primary">Confirm statement import</button>':''}`;
    const commit=$('#commitBankStatement');if(commit)commit.onclick=commitBankStatement;
  }catch(error){resultTarget.innerHTML=`${apiErrorHtml(error)}${bankPreviewRows(error.payload||{})}`}
}
async function commitBankStatement(){
  const preview=state.bankPreview,button=$('#commitBankStatement');
  if(!preview||preview.workspace!==state.workspace){toast('Preview the statement again for this workspace');return}
  button.disabled=true;
  try{
    const result=await api('/api/import/bank/commit',jsonRequest('POST',{preview_id:preview.previewId,workspace:preview.workspace}));
    state.bankPreview=null;if(state.workspace!==preview.workspace){toast(`Statement imported into ${preview.workspace}.`);return}await loadData();
    await sourcesDrawer(`Imported ${safeCount(result.accepted)} bank transaction(s). Suggested evidence matches remain unconfirmed until reviewed.`,'success');
  }catch(error){state.bankPreview=null;$('#bankStatementResult').innerHTML=`${apiErrorHtml(error)}${noticeHtml('This preview can no longer be confirmed. Choose the statement and preview it again.','warning')}`}
}
async function openGmailConnect(){
  const workspace=state.workspace,sessionId=state.sessionId;
  const popup=window.open('about:blank','payproof-google','width=620,height=760');
  if(!popup){setSourceAction(apiErrorHtml(new Error('The browser blocked the Gmail authorization window. Allow pop-ups for PayProof and try again.')));return}
  try{
    popup.document.title='PayProof Gmail connection';popup.document.body.textContent='Preparing Google authorization…';
    const params=new URLSearchParams({workspace,session_id:sessionId});
    const result=await api(`/api/sources/gmail/connect?${params}`);
    const authorizationUrl=new URL(result.authorization_url,location.origin);
    if(authorizationUrl.protocol!=='https:'||authorizationUrl.hostname!=='accounts.google.com')throw new Error('The server returned an unsafe Gmail authorization URL.');
    popup.location.replace(authorizationUrl.href);
    setSourceAction(noticeHtml('Finish read-only Gmail authorization in the new window. This page will refresh when it closes.','info'));
    monitorOAuthPopup(popup,workspace);
  }catch(error){popup.close();setSourceAction(apiErrorHtml(error))}
}
function monitorOAuthPopup(popup,workspace){
  if(state.oauthPoll)clearInterval(state.oauthPoll);
  let checks=0;
  state.oauthPoll=setInterval(async()=>{
    checks+=1;
    if(popup.closed){
      clearInterval(state.oauthPoll);state.oauthPoll=null;
      if(state.workspace!==workspace)toast(`Gmail authorization finished for ${workspace}.`);
      else if(!$('#drawer').classList.contains('hidden')){try{await sourcesDrawer('Gmail authorization window closed; connection status refreshed.','info')}catch(error){setSourceAction(apiErrorHtml(error))}}
      else toast('Gmail authorization finished. Open Sources to refresh status.');
    }else if(checks>=375){clearInterval(state.oauthPoll);state.oauthPoll=null}
  },800);
}
async function importGmailEvidence(){
  const workspace=state.workspace;
  const button=$('#gmailImport'),query=$('#gmailQuery').value.trim(),maxResults=safeCount($('#gmailMaxResults').value)||20;
  button.disabled=true;setSourceAction(noticeHtml('Importing read-only Gmail metadata and snippets…','info'));
  try{
    const result=await api('/api/sources/gmail/import',jsonRequest('POST',{workspace,query,max_results:maxResults}));
    if(state.workspace!==workspace){toast(`Gmail evidence imported into ${workspace}.`);return}
    await loadData();
    await sourcesDrawer(`Gmail import finished: ${safeCount(result.accepted)} added and ${safeCount(result.skipped)} already present or skipped.`,'success');
  }catch(error){setSourceAction(apiErrorHtml(error));button.disabled=false}
}
async function previewGmailDisconnect(){
  const workspace=state.workspace,sessionId=state.sessionId;
  setSourceAction(noticeHtml('Calculating Gmail disconnect impact…','info'));
  try{
    const preview=await api('/api/sources/gmail/disconnect-preview',jsonRequest('POST',{workspace,session_id:sessionId}));
    if(state.workspace!==workspace)return;
    setSourceAction(`<div class="confirmation-card"><span class="section-label">GMAIL DISCONNECT PREVIEW</span><h3>Revoke Gmail authorization?</h3>${affectedHtml(preview.impact)}<div class="notice warning">Confirming first asks Google to revoke this authorization, then deletes PayProof’s encrypted local token. Imported evidence remains. Gmail messages are never deleted. The same Google grant used in another workspace may also be affected.</div><div class="modal-actions"><button id="confirmGmailDisconnect" class="button danger">Confirm Gmail disconnect</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
    $('#cancelSourceAction').onclick=()=>setSourceAction('');
    $('#confirmGmailDisconnect').onclick=async event=>{
      event.currentTarget.disabled=true;
      try{
        const result=await api('/api/sources/gmail/disconnect',jsonRequest('POST',{workspace,session_id:sessionId,preview_id:preview.preview_id,confirm:true}));
        if(state.workspace!==workspace){toast(`Gmail disconnected from ${workspace}.`);return}
        await sourcesDrawer(result.notice||'Gmail authorization revoked and the encrypted local token removed. Imported evidence was preserved.','success');
      }catch(error){setSourceAction(apiErrorHtml(error))}
    };
  }catch(error){setSourceAction(apiErrorHtml(error))}
}
async function scanIntakeFolder(folderId=null){
  const workspace=state.workspace,folder=folderId?configuredIntakeFolder(folderId):null;
  if(folderId&&!folder){setSourceAction(noticeHtml('That intake-folder assignment is no longer available. Refresh and try again.','warning'));return}
  if(folder&&folder.enabled!==true){setSourceAction(noticeHtml('Enable this intake folder before scanning it.','warning'));return}
  const scopeLabel=folder?.label||'all enabled intake folders';
  setSourceAction(noticeHtml(`Scanning ${scopeLabel} for this company...`,'info'));
  try{
    const payload={workspace};if(folderId)payload.folder_id=folderId;
    const result=await api('/api/sources/intake/scan',jsonRequest('POST',payload));
    if(state.workspace!==workspace){toast(`Intake scan finished for ${workspace}. Open that company to review it.`);return}
    await loadData();
    if(state.workspace!==workspace)return;
    const folders=Array.isArray(result.folders)?result.folders:[],errors=Array.isArray(result.errors)?result.errors:[];
    const found=folders.reduce((total,item)=>total+safeCount(item.files_found),0);
    await sourcesDrawer(`Scanned ${safeCount(result.folders_scanned)} folder(s) and found ${found} file(s): ${safeCount(result.accepted)} new, ${safeCount(result.skipped)} unchanged or skipped.`,errors.length?'warning':'success');
    if(state.workspace!==workspace)return;
    if(errors.length)setSourceAction(`<div class="notice error" role="alert"><b>${errors.length} intake file(s) need attention.</b><ul>${errors.map(item=>`<li>${escapeHtml(item.filename||'Unknown file')}: ${escapeHtml(item.reason||'Scan failed')}</li>`).join('')}</ul></div>`);
  }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Intake scan failed for ${workspace}: ${error.message}`)}
}
async function previewImportedSourceRemoval(sourceId){
  const workspace=state.workspace;
  setSourceAction(noticeHtml('Calculating which local records would be removed…','info'));
  try{
    const params=new URLSearchParams({workspace});
    const preview=await api(`/api/sources/${encodeURIComponent(sourceId)}/removal-preview?${params}`);
    if(state.workspace!==workspace)return;
    setSourceAction(`<div class="confirmation-card"><span class="section-label">SOURCE REMOVAL PREVIEW</span><h3>${escapeHtml(preview.filename||preview.source_id)}</h3>${affectedHtml(preview.affected)}<div class="notice warning">Only these local PayProof records will be removed. Provider data and connection permissions are unchanged.</div><div class="modal-actions"><button id="confirmSourceRemoval" class="button danger">Confirm removal</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
    $('#cancelSourceAction').onclick=()=>setSourceAction('');
    $('#confirmSourceRemoval').onclick=async event=>{
      event.currentTarget.disabled=true;
      try{
        const params=new URLSearchParams({workspace,preview_id:preview.preview_id,confirm:'true'});
        const result=await api(`/api/sources/${encodeURIComponent(sourceId)}?${params}`,{method:'DELETE'});
        if(state.workspace!==workspace){toast(`Source removed from ${workspace}.`);return}
        await loadData();await sourcesDrawer(`Removed ${safeCount(result.removed)} local record(s). Upstream provider data was not changed.`,'success');
      }catch(error){setSourceAction(apiErrorHtml(error))}
    };
  }catch(error){setSourceAction(apiErrorHtml(error))}
}
function intakeEditableValues(expense){return {merchant:String(expense.merchant||''),amount:(safeCount(expense.amount_cents)/100).toFixed(2),currency:String(expense.currency||'USD'),date:String(expense.spent_on||expense.date||''),category:String(expense.category||''),purpose:String(expense.purpose||''),receipt_status:String(expense.receipt_status||'missing'),approval_status:String(expense.approval_status||'needs_review')}}
function selectOptions(values,current){return values.map(value=>`<option value="${escapeHtml(value)}" ${value===current?'selected':''}>${escapeHtml(value.replaceAll('_',' '))}</option>`).join('')}
function intakeHistoryHtml(history){
  const versions=Array.isArray(history?.versions)?history.versions:[];
  if(!versions.length)return '<p class="empty-state">No version history is available.</p>';
  return versions.slice().reverse().map(version=>{const snapshot=version.snapshot||{};return `<details class="history-version" ${version===versions.at(-1)?'open':''}><summary><b>Version ${safeCount(version.version)}</b><span>${escapeHtml(readableTime(version.created_at))}</span></summary><p><b>Reason:</b> ${escapeHtml(version.reason||'No reason recorded')}</p><p><b>Changed:</b> ${Array.isArray(version.changed_fields)&&version.changed_fields.length?version.changed_fields.map(field=>escapeHtml(field.replaceAll('_',' '))).join(', '):'original import'}</p><div class="history-snapshot"><span>${escapeHtml(snapshot.merchant||'Unknown merchant')}</span><strong>${escapeHtml(safeMoney(snapshot.amount_cents,snapshot.currency))}</strong><small>${escapeHtml(snapshot.date||'Unknown date')} · ${escapeHtml(snapshot.receipt_status||'unknown')} · ${escapeHtml(snapshot.approval_status||'unknown')}</small></div></details>`}).join('');
}
async function openIntakeEditor(expenseId,message=''){
  const workspace=state.workspace;
  const expense=(state.data?.expenses||[]).find(item=>item.id===expenseId&&String(item.source_id||'').startsWith('intake:'));
  if(!expense){toast('That intake expense is no longer available');return}
  const values=intakeEditableValues(expense);
  openDrawer('AUDITED INTAKE EDIT',expense.id,`
    <button id="backToSources" class="link-button back-link">← Sources & settings</button>
    ${noticeHtml(message,'success')}
    <div class="notice info">Corrections update the active record used for matching. The original intake file and every prior version remain preserved.</div>
    <form id="intakeEditForm" class="compact-form">
      <div class="form-grid"><label>Merchant<input name="merchant" required maxlength="160" value="${escapeHtml(values.merchant)}"></label><label>Amount<input name="amount" type="number" min="0.01" step="0.01" required value="${escapeHtml(values.amount)}"></label><label>Currency<input name="currency" required minlength="3" maxlength="3" value="${escapeHtml(values.currency)}"></label><label>Date<input name="date" type="date" required value="${escapeHtml(values.date)}"></label><label>Category<input name="category" required maxlength="100" value="${escapeHtml(values.category)}"></label><label>Receipt status<select name="receipt_status">${selectOptions(['matched','missing','not_required','submitted'],values.receipt_status)}</select></label><label>Approval status<select name="approval_status">${selectOptions(['approved','needs_review','submitted','rejected'],values.approval_status)}</select></label></div>
      <label>Business purpose<textarea name="purpose" rows="3" required maxlength="500">${escapeHtml(values.purpose)}</textarea></label>
      <label>Reason for correction <span class="required-mark">required for audit</span><textarea name="reason" rows="2" required minlength="3" maxlength="500" placeholder="Explain why this record is changing"></textarea></label>
      <div class="modal-actions"><button class="button primary" type="submit">Save audited correction</button><button id="cancelIntakeEdit" class="button ghost" type="button">Cancel</button></div>
      <div id="intakeEditResult" aria-live="polite"></div>
    </form>
    <section class="history-section"><div class="settings-heading"><div><span class="section-label">IMMUTABLE AUDIT TRAIL</span><h3>Version history</h3></div></div><div id="intakeHistory">${noticeHtml('Loading version history…','info')}</div></section>
  `);
  $('#backToSources').onclick=()=>sourcesDrawer();$('#cancelIntakeEdit').onclick=()=>sourcesDrawer();
  $('#intakeEditForm').onsubmit=event=>saveIntakeCorrection(event,expense,values);
  try{const history=await api(`/api/intake/expenses/${encodeURIComponent(expenseId)}/history?workspace=${encodeURIComponent(workspace)}`);if(state.workspace===workspace&&$('#intakeHistory'))$('#intakeHistory').innerHTML=intakeHistoryHtml(history)}
  catch(error){if(state.workspace===workspace&&$('#intakeHistory'))$('#intakeHistory').innerHTML=apiErrorHtml(error)}
}
async function saveIntakeCorrection(event,expense,original){
  event.preventDefault();const form=event.currentTarget,submit=form.querySelector('[type="submit"]'),result=$('#intakeEditResult');
  const workspace=state.workspace;
  const data=new FormData(form),changes={};
  ['merchant','amount','currency','date','category','purpose','receipt_status','approval_status'].forEach(field=>{const value=String(data.get(field)||'').trim();if(value!==original[field])changes[field]=value});
  const reason=String(data.get('reason')||'').trim();
  if(reason.length<3){result.innerHTML=noticeHtml('Enter a correction reason of at least 3 characters.','error');form.elements.reason.focus();return}
  if(!Object.keys(changes).length){result.innerHTML=noticeHtml('Change at least one expense field before saving.','warning');return}
  submit.disabled=true;result.innerHTML=noticeHtml('Saving the correction and immutable audit version…','info');
  try{
    const saved=await api(`/api/intake/expenses/${encodeURIComponent(expense.id)}`,jsonRequest('PATCH',{workspace,changes,reason}));
    if(state.workspace!==workspace){toast(`Expense ${expense.id} was updated in ${workspace}.`);return}
    await loadData();await openIntakeEditor(expense.id,`Saved version ${safeCount(saved.version)}. Original record preserved; audit entry ${safeCount(saved.audit_id)} recorded.`);
  }catch(error){result.innerHTML=apiErrorHtml(error);submit.disabled=false}
}
async function uploadImport(commit){const file=$('#importFile')?.files[0];if(!file){toast('Choose a CSV file first');return}const form=new FormData();form.append('file',file);form.append('workspace',state.workspace);form.append('commit',String(commit));try{const r=await api('/api/import/transactions',{method:'POST',body:form});$('#importResult').innerHTML=`<div class="notice">${r.accepted.length} accepted · ${r.rejected.length} rejected</div>${r.rejected.map(x=>`<p>Line ${x.line}: ${escapeHtml(x.reason)}</p>`).join('')}<div class="detail-grid">${r.accepted.slice(0,8).map(x=>`<div class="detail-row"><span>${x.id}</span><strong>${escapeHtml(x.merchant)} · ${money(x.amount_cents,x.currency)}</strong></div>`).join('')}</div>${!r.committed&&r.accepted.length&&!r.rejected.length?'<button id="commitImport" class="button primary">Confirm import</button>':''}`;const commitBtn=$('#commitImport');if(commitBtn)commitBtn.onclick=()=>uploadImport(true);if(r.committed){toast('Import completed');await loadData()}}catch(e){$('#importResult').innerHTML=`<div class="notice">${escapeHtml(e.message)}</div>`}}

function addMessage(role,text,evidence=[]){const el=document.createElement('div');el.className=`message ${role}-message`;el.innerHTML=`<span class="message-label">${role==='user'?'OPERATOR':'PAYPROOF'}</span>${escapeHtml(text)}${evidence.length?`<div class="evidence-links">Evidence: ${evidence.slice(0,6).map(e=>`<button>${escapeHtml(e)}</button>`).join(', ')}${evidence.length>6?` +${evidence.length-6} more`:''}</div>`:''}`;$('#chatLog').append(el);$('#chatLog').scrollTop=$('#chatLog').scrollHeight}
async function ask(question){const q=(question||$('#chatInput').value).trim();if(!q)return;$('#chatInput').value='';addMessage('user',q);$('#chatSend').disabled=true;try{const r=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,workspace:state.workspace,selected_id:state.selectedId,session_id:state.sessionId})});addMessage('assistant',r.answer,r.evidence_ids);state.lastContext=r.context;$('#traceStatus').textContent=`${r.model.state==='live_model'?'AI':'Fallback'} · Trace: ${r.trace.state}`;if(r.focus_ids?.length){state.selectedId=r.focus_ids[0];renderVisual()}}catch(e){addMessage('assistant',`I could not complete that request: ${e.message}`)}finally{$('#chatSend').disabled=false;$('#chatInput').focus()}}
async function takeAction(action){const reason=action==='dismissed'?prompt('Reason for dismissal:')||'':'';try{const r=await api('/api/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace:state.workspace,finding_id:state.selectedFinding,action,reason})});toast(`Simulated action recorded: ${r.status}`);await loadData()}catch(e){toast(e.message)}}
function openDrawer(label,title,html){$('#drawerLabel').textContent=label;$('#drawerTitle').textContent=title;$('#drawerContent').innerHTML=html;$('#drawer').classList.remove('hidden');$('#drawerBackdrop').classList.remove('hidden')}
function closeDrawer(){$('#drawer').classList.add('hidden');$('#drawerBackdrop').classList.add('hidden')}
function toast(message){const t=document.createElement('div');t.className='toast';t.textContent=message;document.body.append(t);setTimeout(()=>t.remove(),2600)}
function escapeHtml(value){return String(value??'').replace(/[&<>'"]/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]))}

function startDemo(){const steps=[()=>{state.view='atlas';syncNav();renderVisual();state.selectedFinding='F-ROUTE-001';renderFocus();toast('Step 1 · Follow the red proposed payment route')},()=>ask('What changed on this invoice?'),()=>{state.view='change';syncNav();renderVisual();toast('Step 3 · Explain changes across periods')},()=>evidenceDrawer()];steps[state.demoStep%steps.length]();state.demoStep++;$('#tourButton').textContent=state.demoStep%steps.length?`Next demo step ${state.demoStep+1}/${steps.length}`:'▶ Guided demo'}
function syncNav(){$$('#viewNav button').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view))}

$('#workspaceSelect').onchange=event=>switchWorkspace(event.target.value,event.target.selectedOptions[0]?.textContent||event.target.value);
$$('#viewNav button').forEach(b=>b.onclick=()=>{state.view=b.dataset.view;syncNav();renderVisual()});
$('#refreshButton').onclick=loadData;$('#resetButton').onclick=async()=>{if(confirm('Reset only the built-in synthetic example?')){await api('/api/reset',{method:'POST'});state.selectedFinding='F-ROUTE-001';state.selectedId='invoice:INV-1007';await loadData();toast('Synthetic example reset')}};
$('#importOpen').onclick=importDrawer;$('#sourcesOpen').onclick=()=>sourcesDrawer().catch(e=>toast(e.message));$('#tourButton').onclick=startDemo;$('#evidenceButton').onclick=evidenceDrawer;$('#contextOpen').onclick=contextDrawer;$('#chatContextButton').onclick=contextDrawer;
$('#drawerClose').onclick=closeDrawer;$('#drawerBackdrop').onclick=closeDrawer;$('#chatSend').onclick=()=>ask();$('#chatInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask()}};
$$('#suggestions button').forEach(b=>b.onclick=()=>ask(b.textContent));$$('[data-action]').forEach(b=>b.onclick=()=>takeAction(b.dataset.action));
$('#zoomIn').onclick=()=>{state.zoom=Math.min(2,state.zoom+.15);drawAtlas()};$('#zoomOut').onclick=()=>{state.zoom=Math.max(.65,state.zoom-.15);drawAtlas()};$('#zoomReset').onclick=()=>{state.zoom=1;state.pan={x:0,y:0};drawAtlas()};
$('#atlasCanvas').onclick=e=>{const box=e.currentTarget.getBoundingClientRect(),x=(e.clientX-box.left-state.pan.x)/state.zoom,y=(e.clientY-box.top-state.pan.y)/state.zoom;let hit=null,best=999;state.nodes.forEach(n=>{const d=Math.hypot(n.x-x,n.y-y);if(d<Math.max(18,n.size+8)&&d<best){hit=n;best=d}});if(hit){state.selectedId=hit.id;$('#selectionCard').style.display='block';$('#selectionCard').innerHTML=`<b>${escapeHtml(hit.label)}</b><small>${hit.type.toUpperCase()} · ${escapeHtml(hit.source||'loaded evidence')} · click details or ask a question</small>`;if(['vendor','invoice','transaction','receipt','email'].includes(hit.type))openRecord(hit.id);drawAtlas()}};
let rotateStart=null;$('#atlasCanvas').onpointerdown=e=>{rotateStart={x:e.clientX,yaw:state.yaw};e.currentTarget.setPointerCapture(e.pointerId)};$('#atlasCanvas').onpointermove=e=>{if(!rotateStart)return;state.yaw=rotateStart.yaw+(e.clientX-rotateStart.x)/240;drawAtlas()};$('#atlasCanvas').onpointerup=()=>{rotateStart=null};
window.addEventListener('resize',()=>state.view==='atlas'&&drawAtlas());
addMessage('assistant','I am ready. Ask me to complete the security questionnaire, investigate a control, explain conflicting evidence, identify what is unknown, or show the source behind any answer.');
loadData().catch(e=>addMessage('assistant',`The application could not load: ${e.message}`));
