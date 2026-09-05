const state={data:null,workspace:'business',view:new URLSearchParams(location.search).get('view')||'overview',selectedId:'invoice:INV-1007',selectedFinding:'F-ROUTE-001',zoom:1,pan:{x:0,y:0},yaw:-.32,nodes:[],sessionId:(()=>{try{const saved=sessionStorage.getItem('payproof-chat-session');if(saved)return saved;const created=`payproof-${crypto.randomUUID?.()||Date.now()}`;sessionStorage.setItem('payproof-chat-session',created);return created}catch{return `payproof-${Date.now()}`}})(),lastContext:null,demoStep:0,sourceConfig:null,connectionStatus:null,bankPreview:null,activePlaidHandler:null,oauthPoll:null,loadGeneration:0,sourceGeneration:0,workspaceGeneration:0,chatPending:false,refreshInProgress:false,lastUpdatedAt:null,lastRefreshSummary:'',networkProblem:false,refreshAfterReconnect:false,metricValuesByWorkspace:{},autoRefreshMinutes:readAutoRefreshMinutes(),nextAutoRefreshAt:null,autoRefreshTimer:null,autoRefreshRunning:false,readinessFilter:null,changeCurrencyByWorkspace:{},outsideResearchQueryByWorkspace:{},outsideResearchResultsByWorkspace:{},recordFilter:null,assistantSpotlight:null,voice:{recognition:null,inputAvailable:false,micState:'off',spokenReplies:false,replyVoice:null,statusMessage:'',voicesBound:false}};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const riskColor={clear:'#3cf0a5',review:'#ffc64d',high:'#ff5274'};
const money=(cents,currency='USD')=>new Intl.NumberFormat('en-US',{style:'currency',currency}).format(cents/100);
const api=async(url,options={})=>{
  let response;
  try{response=await fetch(url,options)}catch(error){markNetworkProblem();throw error}
  if(state.networkProblem&&navigator.onLine)markConnectionRestored();
  let body={};
  try{body=await response.json()}catch{body={error:`The server returned an unreadable response (${response.status}).`}}
  if(!response.ok){const error=new Error(body.error||body.errors?.join(', ')||`Request failed (${response.status})`);error.payload=body;error.status=response.status;throw error}
  return body;
};
const jsonRequest=(method,payload)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
function readAutoRefreshMinutes(){try{const value=Number.parseInt(localStorage.getItem('payproof-auto-refresh-minutes')||'5',10);return [5,10].includes(value)?value:5}catch{return 5}}

function workspaceInitials(name){
  const words=String(name||'Company').trim().split(/\s+/).filter(Boolean);
  return (words.length>1?`${Array.from(words[0])[0]||''}${Array.from(words.at(-1))[0]||''}`:Array.from(words[0]||'CO').slice(0,2).join('')).toUpperCase();
}
function safeWebsiteUrl(value){
  const raw=String(value||'').trim();
  if(!raw)return null;
  try{
    const candidate=/^[a-z][a-z0-9+.-]*:/i.test(raw)?raw:`https://${raw}`;
    const url=new URL(candidate);
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password)return null;
    return url.href;
  }catch{return null}
}
function safeResearchUrl(value){
  const raw=String(value||'').trim();
  if(!/^https?:\/\//i.test(raw))return null;
  try{
    const url=new URL(raw);
    const host=url.hostname.replace(/^\[|\]$/g,'').toLowerCase();
    const localName=!host.includes('.')||host==='localhost'||/\.(?:localhost|local|internal|lan|home|corp|test|invalid|onion)$/.test(host);
    const localIp=/^(?:127\.|10\.|0\.|169\.254\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/.test(host)||host==='::1';
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password||localName||localIp)return null;
    return url.href;
  }catch{return null}
}
function outsideResearchItems(data=state.data,workspace=state.workspace){
  const saved=Array.isArray(data?.web_evidence)?data.web_evidence:[];
  const recent=Array.isArray(state.outsideResearchResultsByWorkspace[workspace])?state.outsideResearchResultsByWorkspace[workspace]:[];
  const seen=new Set();
  return [...saved,...recent].filter(item=>{
    if(!item||typeof item!=='object')return false;
    const key=String(item.id||item.url||`${item.title||''}|${item.retrieved_at||''}`);
    if(seen.has(key))return false;
    seen.add(key);
    return true;
  });
}
function outsideResearchNodeId(item,index){
  const raw=String(item?.id||`lead-${index+1}`);
  return raw.startsWith('web:')?raw:`web:${raw}`;
}
function outsideResearchExcerpt(item){return String(item?.content??item?.snippet??'')}
function addOutsideResearchToGraph(data){
  const graph=data?.graph,items=outsideResearchItems(data);
  if(!graph||!Array.isArray(graph.nodes)||!Array.isArray(graph.edges)||!items.length)return;
  const workspaceNode=graph.nodes.find(node=>node.type==='workspace');
  if(!workspaceNode)return;
  items.slice(0,12).forEach((item,index)=>{
    const id=outsideResearchNodeId(item,index);
    if(!graph.nodes.some(node=>String(node.id)===id)){
      const safeUrl=safeResearchUrl(item.url),host=safeUrl?new URL(safeUrl).hostname.replace(/^www\./i,''):'';
      graph.nodes.push({id,type:'web',label:String(item.title||host||'Outside research lead').slice(0,46),risk:'review',size:7,source:item.source_label||'Tavily · outside research'});
    }
    if(!graph.edges.some(edge=>String(edge.target)===id))graph.edges.push({source:workspaceNode.id,target:id,risk:'review'});
  });
}
function findOutsideResearch(ref){
  const wanted=String(ref||'');
  return outsideResearchItems().find((item,index)=>String(item.id||'')===wanted||outsideResearchNodeId(item,index)===wanted)||null;
}
function outsideResearchDefaultQuery(currentWorkspace){
  const vendors=Array.isArray(state.data?.vendors)?state.data.vendors:[],invoices=Array.isArray(state.data?.invoices)?state.data.invoices:[],findings=Array.isArray(state.data?.findings)?state.data.findings:[];
  const selectedPart=String(state.selectedId||'').split(':').slice(1).join(':');
  const finding=findings.find(item=>String(item.id)===String(state.selectedFinding));
  const candidateIds=[selectedPart,finding?.entity_id].filter(Boolean).map(value=>String(value).toLowerCase());
  let vendor=vendors.find(item=>candidateIds.includes(String(item.id||'').toLowerCase())||candidateIds.includes(String(item.name||'').toLowerCase()));
  if(!vendor){
    const invoice=invoices.find(item=>candidateIds.includes(String(item.id||'').toLowerCase()));
    if(invoice)vendor=vendors.find(item=>String(item.id||'').toLowerCase()===String(invoice.vendor_id||'').toLowerCase());
  }
  const subject=String(vendor?.name||currentWorkspace?.name||'').trim();
  return subject?`${subject} company registration`:'';
}
function outsideResearchCardHtml(item){
  const safeUrl=safeResearchUrl(item.url),title=String(item.title||'Untitled outside result'),source=String(item.source_label||'Tavily · outside research');
  const host=safeUrl?new URL(safeUrl).hostname.replace(/^www\./i,''):'Link unavailable';
  const titleHtml=safeUrl?`<a class="research-lead-link" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer nofollow">${escapeHtml(title)} <span aria-hidden="true">↗</span></a>`:`<strong class="research-lead-title">${escapeHtml(title)}</strong>`;
  return `<article class="research-lead"><div class="research-lead-head"><span class="status-chip warn">unverified lead</span><span>${escapeHtml(host)}</span></div>${titleHtml}${safeUrl?'':'<p class="unsafe-link-note">The link was hidden because it was not a safe public web address.</p>'}<details class="research-lead-details"><summary>View excerpt and search details</summary><div><p>${escapeHtml(outsideResearchExcerpt(item)||'No excerpt was returned.')}</p><dl><div><dt>Search used</dt><dd>${escapeHtml(item.query||'Not recorded')}</dd></div><div><dt>Found</dt><dd>${escapeHtml(readableTime(item.retrieved_at))}</dd></div><div><dt>Source</dt><dd>${escapeHtml(source)}</dd></div></dl><small>Outside page text is treated as untrusted. Check the original page and an authoritative record before relying on it.</small></div></details></article>`;
}
function outsideResearchCardsHtml(items){
  if(!items.length)return '<p class="empty-state">No outside research has been saved for this company.</p>';
  return items.slice(0,30).map(outsideResearchCardHtml).join('');
}
function safeCompanyLogoUrl(value,workspaceId){
  const raw=String(value||'').trim();
  if(!raw||!workspaceId)return null;
  try{
    const url=new URL(raw,location.origin),expectedPath=`/api/workspaces/${encodeURIComponent(workspaceId)}/logo`;
    if(url.origin!==location.origin||url.pathname!==expectedPath||!['http:','https:'].includes(url.protocol))return null;
    return url.href;
  }catch{return null}
}
function safeTransferFilename(header,fallback='payproof-transfer.zip'){
  const raw=String(header||'');
  let candidate='';
  const encoded=raw.match(/filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i);
  const plain=raw.match(/filename\s*=\s*("[^"]*"|[^;]+)/i);
  if(encoded){
    candidate=encoded[1].trim().replace(/^"|"$/g,'');
    try{candidate=decodeURIComponent(candidate)}catch{}
  }else if(plain){candidate=plain[1].trim().replace(/^"|"$/g,'')}
  candidate=(candidate||fallback).split(/[\\/]/).at(-1).replace(/[<>:"/\\|?*\u0000-\u001f\u007f]+/g,'_').trim().replace(/[. ]+$/g,'');
  if(!candidate)candidate=fallback;
  if(!/\.zip$/i.test(candidate))candidate=`${candidate}.zip`;
  return candidate.length>180?`${candidate.slice(0,176)}.zip`:candidate;
}
function renderActiveCompanyBranding(){
  const workspace=(state.data?.workspaces||[]).find(item=>item.id===state.workspace)||state.sourceConfig?.currentWorkspace||{id:state.workspace,name:state.workspace,is_demo:false};
  const name=String(workspace.name||state.workspace),initials=workspaceInitials(name),logoUrl=safeCompanyLogoUrl(workspace.logo_url,workspace.id),websiteUrl=safeWebsiteUrl(workspace.website);
  const logo=$('#activeCompanyLogo'),fallback=$('#activeCompanyInitials');
  $('#activeCompanyName').textContent=name;
  $('#activeCompanyContext').textContent=name.toUpperCase();
  fallback.textContent=initials;fallback.hidden=false;
  logo.hidden=true;logo.removeAttribute('src');logo.alt=`${name} logo`;
  if(logoUrl){
    logo.onload=()=>{if(state.workspace===workspace.id){logo.hidden=false;fallback.hidden=true}};
    logo.onerror=()=>{logo.hidden=true;fallback.hidden=false;logo.removeAttribute('src')};
    logo.src=logoUrl;
  }
  const website=$('#activeCompanyWebsite');
  website.hidden=!websiteUrl;website.textContent='';
  if(websiteUrl){const parsed=new URL(websiteUrl);website.textContent=parsed.hostname.replace(/^www\./i,'')}
  const typePill=$('#workspaceTypePill');
  typePill.textContent=workspace.is_demo?'SYNTHETIC EXAMPLE':'CUSTOM COMPANY';
  typePill.className=`pill ${workspace.is_demo?'cyan':'good'}`;
  document.title=`PayProof Atlas · ${name}`;
}

function setRefreshStatus(message,tone=''){
  const label=$('#updatedAt');if(!label)return;
  const dot=document.createElement('i');dot.setAttribute('aria-hidden','true');
  label.replaceChildren(dot,document.createTextNode(` ${message}`));label.className=`live-update ${tone}`.trim();
}
function markNetworkProblem(){
  state.networkProblem=true;const indicator=$('#offlineStatus');
  if(indicator){indicator.classList.remove('hidden','restored');indicator.innerHTML='<i aria-hidden="true"></i> OFFLINE · ONLINE REFRESH PAUSED'}
  setRefreshStatus('Offline · bank and Gmail refresh are paused','error');
}
function markConnectionRestored(){
  const wasDown=state.networkProblem;state.networkProblem=false;
  const indicator=$('#offlineStatus');if(indicator){indicator.classList.remove('hidden');indicator.classList.add('restored');indicator.innerHTML='<i aria-hidden="true"></i> ONLINE · REFRESHING NOW'}
  if(wasDown)state.refreshAfterReconnect=true;
  setTimeout(()=>{if(!state.networkProblem)indicator?.classList.add('hidden')},5000);
}
function updateElapsedLabel(){
  if(state.networkProblem){setRefreshStatus(`Offline · ${state.lastRefreshSummary||'bank and Gmail refresh are paused'}`,'error');return}
  if(!state.lastUpdatedAt||state.refreshInProgress)return;
  const elapsed=Math.max(0,Math.floor((Date.now()-state.lastUpdatedAt)/1000));
  const updated=elapsed<15?'Updated just now':elapsed<60?`Updated ${elapsed} seconds ago`:`Updated ${Math.floor(elapsed/60)} minute${elapsed<120?'':'s'} ago`;
  const until=state.nextAutoRefreshAt?Math.max(0,Math.ceil((state.nextAutoRefreshAt-Date.now())/1000)):null;
  const next=`next in ${Math.floor((until??0)/60)}:${String((until??0)%60).padStart(2,'0')}`;
  setRefreshStatus(`${updated}${state.lastRefreshSummary?` · ${state.lastRefreshSummary}`:''} · ${next}`,state.lastRefreshSummary.includes('attention')?'error':'fresh');
}
async function loadData(activity='Refreshing…'){
  const workspace=state.workspace,generation=++state.loadGeneration,refreshButton=$('#refreshButton');
  state.refreshInProgress=true;
  setRefreshStatus(typeof activity==='string'?activity:'Refreshing…','refreshing');
  if(refreshButton){refreshButton.disabled=true;refreshButton.classList.add('refreshing')}
  try{
    const [data,sourceConfig]=await Promise.all([
      api(`/api/dashboard?workspace=${encodeURIComponent(workspace)}`),
      api(`/api/sources?workspace=${encodeURIComponent(workspace)}`).catch(()=>null),
    ]);
    if(workspace!==state.workspace||generation!==state.loadGeneration)return false;
    state.data=data;state.connectionStatus=sourceConfig;if(sourceConfig)state.sourceConfig=sourceConfig;
    addOutsideResearchToGraph(state.data);
    renderWorkspaceOptions();renderCompanyQuickList();renderActiveCompanyBranding();renderConnectionStatus();renderMetrics();renderFindings();renderFocus();renderVisual();renderPrism();syncNav();
    if(state.lastRefreshSummary==='refresh needs attention')state.lastRefreshSummary='';
    state.lastUpdatedAt=Date.now();scheduleNextAutoRefresh();updateElapsedLabel();
    return true;
  }catch(error){
    if(workspace===state.workspace&&generation===state.loadGeneration){state.lastRefreshSummary='refresh needs attention';setRefreshStatus('Refresh needs attention','error')}
    throw error;
  }finally{
    if(generation===state.loadGeneration){state.refreshInProgress=false;if(refreshButton){refreshButton.disabled=false;refreshButton.classList.remove('refreshing')}updateElapsedLabel()}
  }
}
function scheduleNextAutoRefresh(delayMs=null){
  state.nextAutoRefreshAt=Date.now()+(delayMs??state.autoRefreshMinutes*60000);
}
function autoRefreshBlocked(){return document.hidden||!$('#drawer')?.classList.contains('hidden')||state.chatPending||state.activePlaidHandler||state.voice.recognition}
async function runAutoRefresh(force=false){
  if(state.autoRefreshRunning||state.refreshInProgress)return;
  if(!navigator.onLine){
    markNetworkProblem();if(autoRefreshBlocked()){scheduleNextAutoRefresh(30000);return}
    const workspace=state.workspace;state.autoRefreshRunning=true;
    try{const intake=await api('/api/sources/intake/scan',jsonRequest('POST',{workspace}));const intakeErrors=Array.isArray(intake.errors)?intake.errors.length:0;if(intakeErrors)throw new Error(`${intakeErrors} intake folder error${intakeErrors===1?'':'s'}`);if(workspace===state.workspace){state.lastRefreshSummary='local folders refreshed · online sources paused';await loadData('Refreshing local folder records…');setRefreshStatus('Offline · local folders refreshed; bank and Gmail are paused','error')}}catch{setRefreshStatus('Offline · online sources paused; local folder refresh needs attention','error')}finally{state.autoRefreshRunning=false;scheduleNextAutoRefresh()}
    return;
  }
  if(autoRefreshBlocked()){if(force)state.refreshAfterReconnect=true;if(state.autoRefreshMinutes)scheduleNextAutoRefresh(30000);setRefreshStatus('Auto refresh is waiting while you finish this task','waiting');return}
  const workspace=state.workspace;state.autoRefreshRunning=true;state.refreshInProgress=true;setRefreshStatus('Auto refreshing this company…','refreshing');
  const tasks=[];
  try{
    const sources=await api(`/api/sources?workspace=${encodeURIComponent(workspace)}`),bank=sources.bank||{},gmail=sources.gmail||{};
    (bank.connections||[]).filter(connection=>connection.state==='connected').forEach(connection=>tasks.push({label:`${connection.institution||'Bank'} sync`,run:()=>api(`/api/sources/bank/${encodeURIComponent(connection.id)}/sync`,jsonRequest('POST',{workspace}))}));
    if(gmail.connected)tasks.push({label:'Gmail import',run:()=>api('/api/sources/gmail/import',jsonRequest('POST',{workspace,query:'newer_than:365d (from:amazon.com OR category:purchases)',max_results:20}))});
    tasks.push({label:'Intake scan',run:()=>api('/api/sources/intake/scan',jsonRequest('POST',{workspace}))});
    const settled=await Promise.allSettled(tasks.map(task=>task.run()));
    if(workspace!==state.workspace)return;
    const succeeded=settled.filter(result=>result.status==='fulfilled'&&!(Array.isArray(result.value?.errors)&&result.value.errors.length)).length,failed=settled.length-succeeded;
    state.lastRefreshSummary=`${succeeded} source${succeeded===1?'':'s'} refreshed${failed?` · ${failed} need attention`:''}`;
    state.refreshInProgress=false;await loadData('Updating the dashboard…');state.refreshAfterReconnect=false;
  }catch(error){
    if(workspace===state.workspace){state.lastRefreshSummary='source refresh needs attention';state.refreshInProgress=false;if(state.networkProblem){state.refreshAfterReconnect=false;scheduleNextAutoRefresh(30000)}else{try{await loadData('Reloading saved records…')}catch{}}setRefreshStatus(state.networkProblem?'Offline · bank and Gmail refresh are paused':`Auto refresh needs attention: ${error.message}`,'error')}
  }finally{state.autoRefreshRunning=false;state.refreshInProgress=false;if(!state.nextAutoRefreshAt)scheduleNextAutoRefresh();updateElapsedLabel()}
}
function setupAutoRefresh(){
  const select=$('#autoRefreshSelect');select.value=String(state.autoRefreshMinutes);
  select.onchange=()=>{const minutes=Number.parseInt(select.value,10);state.autoRefreshMinutes=[5,10].includes(minutes)?minutes:5;try{localStorage.setItem('payproof-auto-refresh-minutes',String(state.autoRefreshMinutes))}catch{}state.lastRefreshSummary='';scheduleNextAutoRefresh();updateElapsedLabel()};
  scheduleNextAutoRefresh();state.autoRefreshTimer=setInterval(()=>{if(state.refreshAfterReconnect&&!autoRefreshBlocked()&&navigator.onLine)runAutoRefresh(true);else if(state.nextAutoRefreshAt&&Date.now()>=state.nextAutoRefreshAt)runAutoRefresh();else updateElapsedLabel()},1000);
}
function setupConnectivity(){
  if(!navigator.onLine)markNetworkProblem();
  window.addEventListener('offline',markNetworkProblem);
  window.addEventListener('online',()=>{markConnectionRestored();if(autoRefreshBlocked())state.refreshAfterReconnect=true;else runAutoRefresh(true)});
}
function renderWorkspaceOptions(){const el=$('#workspaceSelect');if(!el)return;const fragment=document.createDocumentFragment();(state.data?.workspaces||[]).forEach(workspace=>{const option=document.createElement('option');option.value=workspace.id;option.textContent=workspace.name;fragment.append(option)});el.replaceChildren(fragment);el.value=state.workspace}
function renderCompanyQuickList(){
  const target=$('#companyQuickList');if(!target)return;
  target.innerHTML=(state.data?.workspaces||[]).map(workspace=>`<button class="company-quick-item ${workspace.id===state.workspace?'active':''}" data-company-id="${escapeHtml(workspace.id)}"><span class="company-mini-logo">${escapeHtml(workspaceInitials(workspace.name))}</span><span><b>${escapeHtml(workspace.name)}</b><small>${workspace.is_demo?'Demo company':'Company workspace'}</small></span><i>${workspace.id===state.workspace?'Active':'Open'}</i></button>`).join('');
  $$('#companyQuickList [data-company-id]').forEach(button=>button.onclick=()=>{closeCompanyMenu();switchWorkspace(button.dataset.companyId,button.querySelector('b')?.textContent||button.dataset.companyId)});
}
function setConnectionButton(id,label,connected,detail){const button=$(id);if(!button)return;button.classList.toggle('connected',connected);button.classList.toggle('attention',!connected);button.querySelector('span').textContent=label;button.querySelector('b').textContent=detail;}
function renderConnectionStatus(){
  const sources=state.connectionStatus||{},bankConnections=Array.isArray(sources.bank?.connections)?sources.bank.connections:[],connectedBanks=bankConnections.filter(item=>item.state==='connected').length;
  setConnectionButton('#bankHeaderStatus','Bank',connectedBanks>0,connectedBanks?`${connectedBanks} connected`:'Add bank');
  setConnectionButton('#emailHeaderStatus','Email',Boolean(sources.gmail?.connected),sources.gmail?.connected?'Connected':'Add email');
  const folders=Array.isArray(sources.intake_folder?.folders)?sources.intake_folder.folders.filter(item=>item.enabled!==false):[];
  setConnectionButton('#intakeHeaderStatus','Intake',folders.length>0,folders.length?`${folders.length} folder${folders.length===1?'':'s'}`:'Add folder');
}
function metricButtonHtml(label,value,note,tone,action,changed=false){return `<button type="button" class="metric ${tone} ${changed?'value-changed':''}" data-metric-action="${action}" aria-label="${escapeHtml(label)}: ${escapeHtml(value)}"><span>${escapeHtml(label.toUpperCase())}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small><i aria-hidden="true">View →</i></button>`}
function bindMetricActions(){$$('[data-metric-action]').forEach(button=>button.onclick=()=>activateMetric(button.dataset.metricAction))}
function renderMetricItems(items){
  const previous=state.metricValuesByWorkspace[state.workspace]||{},next={};
  $('#metrics').innerHTML=items.map(item=>{const [label,value]=item,key=label.toLowerCase().replaceAll(' ','_');next[key]=String(value);return metricButtonHtml(...item,previous[key]!==undefined&&previous[key]!==String(value))}).join('');
  state.metricValuesByWorkspace[state.workspace]=next;
}
function budgetSnapshot(){
  const budgets=Array.isArray(state.data?.employee_budgets)?state.data.employee_budgets:[],expenses=Array.isArray(state.data?.expenses)?state.data.expenses:[];
  const period=budgets.map(item=>String(item.period||'')).sort().at(-1)||null,current=budgets.filter(item=>item.period===period),employees=state.data?.employees||[];
  const rows=current.map(budget=>{const employee=employees.find(item=>String(item.id)===String(budget.employee_id))||{id:budget.employee_id,name:'Employee'};const reports=expenses.filter(item=>String(item.employee_id)===String(budget.employee_id)&&String(item.spent_on||'').startsWith(period)&&String(item.currency||'').toUpperCase()===String(budget.currency||'').toUpperCase());const spent=reports.reduce((sum,item)=>sum+safeCount(item.amount_cents),0),limit=safeCount(budget.budget_cents),percent=limit?Math.round(spent/limit*100):0,status=spent>limit?'over':spent<limit*.5?'low':'track';return {employee,budget,reports,spent,limit,percent,status}});
  const currencies=[...new Set(rows.map(item=>item.budget.currency))],totalBudget=rows.reduce((sum,item)=>sum+item.limit,0),totalSpent=rows.reduce((sum,item)=>sum+item.spent,0),percent=currencies.length===1&&totalBudget?Math.round(totalSpent/totalBudget*100):null;
  return {period,rows,totalBudget,totalSpent,percent,currency:currencies.length===1?currencies[0]:null,over:rows.filter(item=>item.status==='over').length,low:rows.filter(item=>item.status==='low').length};
}
function renderMetrics(){
  const m=state.data.metrics||{},budget=budgetSnapshot(),open=(state.data.findings||[]).filter(item=>['open','held','review'].includes(item.status)).length;
  renderMetricItems([
    ['Money in',m.cash_in_label||'No income','Recorded income','green','overview'],
    ['Money out',m.cash_out_label||'No outflow',`${safeCount(m.transaction_count)} ledger records`,'amber','change'],
    ['Budget used',budget.percent===null?'Not set':`${budget.percent}%`,budget.period?`${budget.over} over budget · ${budget.period}`:'Add employee budgets',budget.over?'red':'green','people'],
    ['Needs review',String(open),open?'Open warning signals':'Nothing waiting',open?'red':'green','records'],
  ]);
  bindMetricActions();
}
function activateMetric(action){state.view=['overview','change','people','records','geo','atlas'].includes(action)?action:'overview';syncNav();renderVisual()}
function renderFindings(){const rail=$('#findingRail'),findings=(state.data.findings||[]).filter(item=>['open','held','review'].includes(item.status)).slice(0,4);rail.innerHTML=findings.map(f=>`<button class="finding-mini ${f.severity==='high'?'high':''}" data-finding="${escapeHtml(f.id)}"><i></i><span><b>${escapeHtml(f.title)}</b><small>${escapeHtml(f.entity_id)} · ${escapeHtml(f.status)}</small></span><strong>${escapeHtml(f.severity.toUpperCase())}</strong></button>`).join('')||'<p class="empty-state">Nothing needs attention.</p>';$$('[data-finding]').forEach(b=>b.onclick=()=>selectFinding(b.dataset.finding))}
function selectControl(id){const c=state.data.security.controls.find(x=>x.id===id);state.selectedId=`control:${id}`;$('#focusTitle').textContent=`${c.status.toUpperCase()} · ${c.name}`;$('#focusSummary').textContent=`${c.answer} ${c.contradiction}`;$('#comparison').innerHTML=`<div class="compare-value"><span>CONFIDENCE</span><strong>${c.confidence}%</strong></div><div class="compare-value new"><span>EVIDENCE</span><strong>${c.evidence.length}</strong></div>`;drawAtlas();openRecord(state.selectedId)}
function selectFinding(id){state.selectedFinding=id;const f=state.data.findings.find(x=>x.id===id);if(f){state.selectedId=findingRecordRef(f)||state.selectedId;state.view='records';syncNav();renderFocus();renderVisual();addMessage('assistant',`${f.title}: ${f.summary}`,[...f.evidence_ids])}}
function renderFocus(){const selectedControl=state.selectedId?.startsWith('control:')?(state.data.security?.controls||[]).find(item=>`control:${item.id}`===state.selectedId):null;if(selectedControl){$('#focusTitle').textContent=`${selectedControl.status.toUpperCase()} · ${selectedControl.name}`;$('#focusSummary').textContent=`${selectedControl.answer} ${selectedControl.contradiction}`;$('#comparison').innerHTML=`<div class="compare-value"><span>CONFIDENCE</span><strong>${selectedControl.confidence}%</strong></div><div class="compare-value new"><span>EVIDENCE</span><strong>${selectedControl.evidence.length}</strong></div>`;return}const f=(state.data.findings||[]).find(x=>x.id===state.selectedFinding)||(state.data.findings||[])[0];if(!f){$('#focusTitle').textContent='Nothing selected';$('#focusSummary').textContent='Choose a dashboard card, employee, transaction, or review item to see more.';$('#comparison').innerHTML='';return}$('#focusTitle').textContent=`${f.severity.toUpperCase()} · ${f.title}`;$('#focusSummary').textContent=`${f.summary} ${f.basis}`;$('#comparison').innerHTML=f.kind==='destination_change'?`<div class="compare-value"><span>VERIFIED</span><strong>****7284</strong></div><div class="compare-value new"><span>PROPOSED</span><strong>****9142</strong></div>`:`<div class="compare-value"><span>STATUS</span><strong>${escapeHtml(f.status)}</strong></div><div class="compare-value"><span>SOURCES</span><strong>${(f.evidence_ids||[]).length}</strong></div>`}
function renderPrism(){const p=state.data.prism,el=$('#prismPill');el.className=`pill ${p.state==='configured'?'good':'muted'}`;el.innerHTML=`<i></i> PRISM ${p.state==='configured'?'CONFIGURED':'NEEDS KEY'}${p.queued?` · ${p.queued} QUEUED`:''}`;const badge=$('.assistant-badges span');if(badge)badge.textContent=state.data.ai.state==='configured'?`LIVE MODEL · ${state.data.ai.model}`:'LOCAL FALLBACK'}

function renderVisual(){
  ['overviewView','atlasCanvas','changeView','geoView','peopleView','recordsView'].forEach(id=>$(`#${id}`).classList.add('hidden'));
  const titles={overview:['Business dashboard','Money, budgets, connections, and risk'],atlas:['Evidence links','Optional record relationship view'],change:['Money & trends','Income and spending over time'],geo:['Connections','Banks, email, and intake folders'],people:['People & budgets','Employee spending against plan'],records:['Risk & documents','Review queue and saved records']};if(!titles[state.view])state.view='overview';
  $('#viewTitle').textContent=titles[state.view][0];$('#panelTitle').textContent=titles[state.view][1];
  $(`#${state.view==='atlas'?'atlasCanvas':state.view+'View'}`).classList.remove('hidden');
  $('.canvas-tools').classList.toggle('hidden',state.view!=='atlas');
  $('.command-center').classList.toggle('expanded-view',['overview','people','geo'].includes(state.view));$('#focusPanel').classList.toggle('hidden',['overview','people','geo'].includes(state.view));
  const hints={overview:'Choose a card to see the records behind the number.',change:'Select a transaction or review signal for more detail.',people:'Choose an employee to review spending or update a budget.',records:'Open only the detail you need; evidence stays collapsed.',geo:'Manage each company connection from one place.',atlas:'This optional view shows how saved evidence relates.'};$('#visualHint').textContent=hints[state.view];
  if(state.view==='overview')renderOverview();if(state.view==='atlas')drawAtlas();if(state.view==='change')renderChange();if(state.view==='geo')renderConnectionsView();if(state.view==='people')renderPeopleBudget();if(state.view==='records')renderRecordsModern();
}
function monthlyMoneySnapshot(){
  const months={};(state.data.transactions||[]).forEach(item=>{const period=String(item.occurred_on||'').slice(0,7);if(!/^\d{4}-\d{2}$/.test(period)||String(item.currency||'USD').toUpperCase()!=='USD')return;const row=months[period]||(months[period]={income:0,out:0});if(item.kind==='income')row.income+=safeCount(item.amount_cents);else if(['payment','purchase','expense','debit'].includes(item.kind)&&safeCount(item.amount_cents)>0)row.out+=safeCount(item.amount_cents)});return Object.entries(months).sort(([left],[right])=>left.localeCompare(right)).slice(-6).map(([period,values])=>({period,...values}))
}
function renderOverview(){
  const m=state.data.metrics||{},monthly=monthlyMoneySnapshot(),max=Math.max(1,...monthly.flatMap(item=>[item.income,item.out]));
  const bars=monthly.map(item=>`<div class="money-month"><div class="money-columns"><i class="income" style="--height:${Math.max(5,Math.round(item.income/max*100))}%" title="${escapeHtml(safeMoney(item.income,'USD'))} in"></i><i class="out" style="--height:${Math.max(5,Math.round(item.out/max*100))}%" title="${escapeHtml(safeMoney(item.out,'USD'))} out"></i></div><span>${escapeHtml(item.period.slice(5))}</span></div>`).join('')||'<p class="empty-state">No monthly activity yet.</p>';
  const latest=monthly.at(-1),prior=monthly.at(-2),change=latest&&prior&&prior.income?Math.round((latest.income-prior.income)/Math.abs(prior.income)*100):null,trend=change===null?'Need another month':change>0?`Up ${change}%`:change<0?`Down ${Math.abs(change)}%`:'No change';
  const budget=budgetSnapshot(),budgetLabel=budget.currency?safeMoney(budget.totalSpent,budget.currency):'Not set',budgetLimit=budget.currency?safeMoney(budget.totalBudget,budget.currency):'Add budgets';
  const findings=(state.data.findings||[]).filter(item=>['open','held','review'].includes(item.status)),riskRows=findings.slice(0,3).map(item=>`<button data-overview-finding="${escapeHtml(item.id)}"><i class="risk-dot ${item.severity==='high'?'high':'review'}"></i><span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.summary)}</small></span><strong>${escapeHtml(item.severity)}</strong></button>`).join('')||'<p class="empty-state">Nothing is waiting for review.</p>';
  const bank=(state.connectionStatus?.bank?.connections||[]).filter(item=>item.state==='connected').length,email=Boolean(state.connectionStatus?.gmail?.connected),folders=(state.connectionStatus?.intake_folder?.folders||[]).filter(item=>item.enabled!==false).length;
  const recent=[...(state.data.bank_transactions||[]).map(item=>({date:item.posted_on,id:`bank:${item.id}`,merchant:item.description,amount:item.amount_cents,currency:item.currency,direction:item.direction})),...(state.data.transactions||[]).map(item=>({date:item.occurred_on,id:`transaction:${item.id}`,merchant:item.merchant_raw,amount:item.amount_cents,currency:item.currency,direction:item.kind==='income'?'credit':'debit'}))].sort((a,b)=>String(b.date).localeCompare(String(a.date))).slice(0,4);
  const recentRows=recent.map(item=>`<button data-overview-record="${escapeHtml(item.id)}"><span><b>${escapeHtml(item.merchant)}</b><small>${escapeHtml(item.date)} · ${escapeHtml(item.direction)}</small></span><strong class="${item.direction==='credit'?'positive':''}">${item.direction==='credit'?'+':'−'}${escapeHtml(safeMoney(Math.abs(item.amount),item.currency))}</strong></button>`).join('')||'<p class="empty-state">Connect a bank or import a statement.</p>';
  $('#overviewView').innerHTML=`<div class="overview-grid">
    <section class="overview-card cash-overview"><header><div><span class="section-label">CASH MOVEMENT</span><h4>Money in and out</h4></div><button data-overview-view="change">Explore trends →</button></header><div class="cash-summary"><div><span>Money in</span><b>${escapeHtml(m.cash_in_label||'No income')}</b></div><div><span>Money out</span><b>${escapeHtml(m.cash_out_label||'No outflow')}</b></div><div class="net"><span>Net cash</span><b>${escapeHtml(m.net_cash_label||'Unknown')}</b></div></div><div class="money-chart" aria-label="Six month income and outflow chart">${bars}</div><div class="chart-key"><span><i class="income"></i>Income</span><span><i class="out"></i>Outflow</span><b>Revenue ${escapeHtml(trend)}</b></div></section>
    <section class="overview-card budget-overview"><header><div><span class="section-label">TEAM BUDGET</span><h4>${escapeHtml(budget.period||'No budget period')}</h4></div><button data-overview-view="people">People →</button></header><div class="budget-visual"><div class="budget-ring" style="--budget-percent:${Math.min(100,budget.percent||0)}"><span><b>${budget.percent===null?'—':`${budget.percent}%`}</b><small>used</small></span></div><div><b>${escapeHtml(budgetLabel)}</b><span>of ${escapeHtml(budgetLimit)}</span><small class="${budget.over?'danger-text':''}">${budget.over} over budget · ${budget.low} below 50% used</small></div></div><p>Low use is a signal to check timing, not automatically a success or problem.</p></section>
    <section class="overview-card risk-overview"><header><div><span class="section-label">NEEDS ATTENTION</span><h4>${findings.length} review item${findings.length===1?'':'s'}</h4></div><button data-overview-view="records">Review all →</button></header><div class="risk-list">${riskRows}</div></section>
    <section class="overview-card connection-overview"><header><div><span class="section-label">LIVE INPUTS</span><h4>Connected records</h4></div><button data-open-connections>Manage →</button></header><div class="connection-grid"><button data-open-connections class="${bank?'ready':'missing'}"><i></i><span><b>Bank</b><small>${bank?`${bank} connected`:'Ready to connect'}</small></span></button><button data-open-connections class="${email?'ready':'missing'}"><i></i><span><b>Email</b><small>${email?'Connected':'Ready to connect'}</small></span></button><button data-open-connections class="${folders?'ready':'missing'}"><i></i><span><b>Intake folders</b><small>${folders?`${folders} active`:'Add a folder'}</small></span></button></div><small class="refresh-note">Refreshes every ${state.autoRefreshMinutes} minutes. Online sources pause when offline.</small></section>
    <section class="overview-card recent-overview"><header><div><span class="section-label">LATEST ACTIVITY</span><h4>Recent transactions</h4></div><button data-overview-view="change">See all →</button></header><div class="recent-list">${recentRows}</div></section>
  </div>`;
  $$('#overviewView [data-overview-view]').forEach(button=>button.onclick=()=>activateMetric(button.dataset.overviewView));$$('#overviewView [data-overview-finding]').forEach(button=>button.onclick=()=>selectFinding(button.dataset.overviewFinding));$$('#overviewView [data-overview-record]').forEach(button=>button.onclick=()=>openRecord(button.dataset.overviewRecord));$$('#overviewView [data-open-connections]').forEach(button=>button.onclick=()=>sourcesDrawer());
}
function renderConnectionsView(){
  const sources=state.connectionStatus||{},banks=Array.isArray(sources.bank?.connections)?sources.bank.connections:[],gmail=sources.gmail||{},folders=Array.isArray(sources.intake_folder?.folders)?sources.intake_folder.folders:[],imports=Array.isArray(sources.imports)?sources.imports:[],tavily=sources.tavily||{};
  const bankRows=banks.map(item=>`<div class="connection-detail"><span><b>${escapeHtml(item.institution||'Bank account')}</b><small>${escapeHtml((item.account_masks||[]).map(mask=>`ending ${mask}`).join(', ')||'Account details available after sync')}</small></span><i class="${item.state==='connected'?'ready':'missing'}">${escapeHtml(item.state||'unknown')}</i></div>`).join('')||'<p class="empty-state">No live bank is connected. The synthetic statement still demonstrates matching.</p>';
  const folderRows=folders.map(item=>`<div class="connection-detail"><span><b>${escapeHtml(item.name||item.id||'Intake folder')}</b><small>${escapeHtml(item.path||'Folder path saved locally')}</small></span><i class="${item.enabled===false?'missing':'ready'}">${item.enabled===false?'paused':'active'}</i></div>`).join('')||'<p class="empty-state">No intake folder is configured.</p>';
  $('#geoView').innerHTML=`<div class="connections-dashboard"><section class="connection-flow"><div class="flow-source"><span>🏦</span><b>Bank</b><small>Transactions</small></div><i>→</i><div class="flow-source"><span>✉</span><b>Email</b><small>Receipts &amp; invoices</small></div><i>→</i><div class="flow-source"><span>▣</span><b>Intake</b><small>Employee paperwork</small></div><i>→</i><div class="flow-core"><span>P</span><b>PayProof</b><small>Match · explain · review</small></div></section><div class="connection-card-grid">
    <article class="connection-card"><header><span class="connection-icon">🏦</span><div><h4>Bank accounts</h4><p>${banks.filter(item=>item.state==='connected').length} connected to this company</p></div><button data-manage-connections>Manage</button></header><details open><summary>Show accounts</summary><div>${bankRows}</div></details></article>
    <article class="connection-card"><header><span class="connection-icon">✉</span><div><h4>Email</h4><p>${gmail.connected?'Mailbox connected':'Ready to connect Gmail'}</p></div><button data-manage-connections>Manage</button></header><details open><summary>What PayProof reads</summary><p>Read-only purchase emails, invoice details, dates, amounts, and item descriptions for matching. Your login stays with Google.</p></details></article>
    <article class="connection-card"><header><span class="connection-icon">▣</span><div><h4>Intake folders</h4><p>${folders.filter(item=>item.enabled!==false).length} active for this company</p></div><button data-manage-connections>Manage</button></header><details open><summary>Show folders</summary><div>${folderRows}</div></details></article>
    <article class="connection-card"><header><span class="connection-icon">↥</span><div><h4>Imports &amp; research</h4><p>${imports.length} imported source${imports.length===1?'':'s'}</p></div><button data-manage-connections>Manage</button></header><details><summary>More details</summary><p>CSV, OFX/QFX, images, and optional outside research. Tavily is ${tavily.configured?'ready':'not configured'}; web results stay unverified until a person checks them.</p></details></article>
  </div></div>`;
  $$('#geoView [data-manage-connections]').forEach(button=>button.onclick=()=>sourcesDrawer());
}
function renderPeopleBudget(){
  const employees=state.data.employees||[],snapshot=budgetSnapshot(),period=snapshot.period||(state.data.expenses||[]).map(item=>String(item.spent_on||'').slice(0,7)).sort().at(-1)||new Date().toISOString().slice(0,7);
  const rows=employees.map(employee=>{const budgetRow=snapshot.rows.find(item=>String(item.employee.id)===String(employee.id));const reports=(state.data.expenses||[]).filter(item=>String(item.employee_id)===String(employee.id)&&String(item.spent_on||'').startsWith(period));const spent=budgetRow?budgetRow.spent:reports.reduce((sum,item)=>sum+safeCount(item.amount_cents),0),currency=budgetRow?.budget.currency||reports[0]?.currency||'USD',limit=budgetRow?.limit||0,percent=limit?Math.round(spent/limit*100):null,status=!limit?'unset':spent>limit?'over':spent<limit*.5?'low':'track';return {employee,reports,spent,currency,limit,percent,status}});
  const cards=rows.map(item=>{const statusLabel={over:'Over budget',low:'Below 50% used',track:'Within budget',unset:'Budget not set'}[item.status],barWidth=item.percent===null?0:Math.min(100,item.percent);return `<article class="budget-person ${item.status}" data-employee-card="${escapeHtml(item.employee.id)}"><header><span class="person-avatar">${escapeHtml(workspaceInitials(item.employee.name))}</span><div><h4>${escapeHtml(item.employee.name)}</h4><p>${escapeHtml(item.employee.department||'Team')} · ${escapeHtml(item.employee.office||'Office not saved')}</p></div><span class="budget-status">${statusLabel}</span></header><div class="budget-amount"><div><span>Spent</span><b>${escapeHtml(safeMoney(item.spent,item.currency))}</b></div><div><span>Budget</span><b>${item.limit?escapeHtml(safeMoney(item.limit,item.currency)):'Not set'}</b></div><div><span>Reports</span><b>${item.reports.length}</b></div></div><div class="budget-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${item.percent||0}"><i style="width:${barWidth}%"></i></div><div class="budget-person-actions"><button data-person-record="${escapeHtml(item.employee.id)}">View spending</button><button data-edit-budget="${escapeHtml(item.employee.id)}">${item.limit?'Change':'Set'} budget</button></div></article>`}).join('');
  $('#peopleView').innerHTML=`<div class="budget-dashboard"><section class="budget-summary"><div><span class="section-label">${escapeHtml(period)} TEAM PLAN</span><h4>${snapshot.percent===null?'Add team budgets':`${snapshot.percent}% of budget used`}</h4><p>See who may need help, who is over plan, and where planned work may not have happened yet.</p></div><div class="budget-summary-stats"><span><b>${snapshot.over}</b> over budget</span><span><b>${snapshot.low}</b> below 50% used</span><span><b>${employees.length}</b> employees</span></div></section><section class="budget-people-grid">${cards||'<p class="empty-state">No employees are loaded for this company.</p>'}</section></div>`;
  $$('#peopleView [data-person-record]').forEach(button=>button.onclick=()=>openPersonDetails(button.dataset.personRecord));$$('#peopleView [data-edit-budget]').forEach(button=>button.onclick=event=>{event.stopPropagation();openBudgetEditor(button.dataset.editBudget,period)});
  if(state.assistantSpotlight?.type==='employee'){const card=$(`[data-employee-card="${CSS.escape(state.assistantSpotlight.id)}"]`);card?.classList.add('assistant-highlight');card?.scrollIntoView({block:'nearest'});state.assistantSpotlight=null}
}
function openBudgetEditor(employeeId,period){
  const employee=(state.data.employees||[]).find(item=>String(item.id)===String(employeeId));if(!employee)return;const current=(state.data.employee_budgets||[]).find(item=>String(item.employee_id)===String(employeeId)&&item.period===period);
  openDrawer('PEOPLE & BUDGETS',`Budget for ${employee.name}`,`<div class="notice">Set a monthly spending plan for this company. PayProof records this change in the audit history.</div><form id="budgetForm" class="compact-form"><label>Month<input name="period" type="month" value="${escapeHtml(period)}" required></label><label>Budget amount<input name="amount" type="number" min="0.01" step="0.01" value="${current?(safeCount(current.budget_cents)/100).toFixed(2):''}" placeholder="1500.00" required></label><label>Currency<input name="currency" value="${escapeHtml(current?.currency||'USD')}" minlength="3" maxlength="3" required></label><button class="button primary" type="submit">Save budget</button></form>`);
  $('#budgetForm').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.currentTarget);try{await api(`/api/employees/${encodeURIComponent(employeeId)}/budget`,jsonRequest('PUT',{workspace:state.workspace,period:form.get('period'),amount:form.get('amount'),currency:form.get('currency')}));closeDrawer();await loadData('Updating the budget…');state.view='people';renderVisual();toast(`Budget saved for ${employee.name}`)}catch(error){toast(error.message)}};
}
function renderRecordsModern(){
  const filter=String(state.recordFilter||'').toLowerCase(),documents=state.data.documents||[],security=state.data.security||{controls:[],evidence:[]};
  const allTransactions=[...(state.data.bank_transactions||[]).map(item=>({id:`bank:${item.id}`,date:item.posted_on,merchant:item.description,amount:item.amount_cents,currency:item.currency,type:'Bank',source:item.source_id})),...(state.data.transactions||[]).map(item=>({id:`transaction:${item.id}`,date:item.occurred_on,merchant:item.merchant_raw,amount:item.amount_cents,currency:item.currency,type:'Ledger',source:item.source_id}))].sort((a,b)=>String(b.date).localeCompare(String(a.date)));
  const transactions=filter?allTransactions.filter(item=>`${item.merchant} ${item.id} ${item.source}`.toLowerCase().includes(filter)):allTransactions;
  const filterBar=filter?`<div class="active-filter"><span>Showing records matching <b>${escapeHtml(filter)}</b></span><button data-clear-record-filter>Show everything</button></div>`:'';
  const txRows=transactions.slice(0,40).map(item=>`<button class="record-list-row" data-record="${escapeHtml(item.id)}"><span><b>${escapeHtml(item.merchant)}</b><small>${escapeHtml(item.date)} · ${escapeHtml(item.type)} · ${escapeHtml(item.source)}</small></span><strong>${escapeHtml(safeMoney(item.amount,item.currency))}</strong></button>`).join('')||'<p class="empty-state">No matching transaction was found.</p>';
  const documentRows=documents.map(item=>`<button class="document-list-row" data-record="document:${escapeHtml(item.id)}"><span class="doc-icon">▤</span><span><b>${escapeHtml(item.filename)}</b><small>${escapeHtml(String(item.document_type||'document').replaceAll('_',' '))} · ${escapeHtml(item.status||'saved')}</small></span><i>${item.is_synthetic?'Synthetic demo':'Company file'}</i></button>`).join('')||'<p class="empty-state">No intake documents are loaded.</p>';
  const controls=(security.controls||[]).map(item=>`<button class="record-list-row" data-control="${escapeHtml(item.id)}"><span><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.answer)}</small></span><strong class="${item.status==='gap'?'danger-text':''}">${escapeHtml(item.status)}</strong></button>`).join('')||'<p class="empty-state">No security questionnaire is loaded.</p>';
  $('#recordsView').innerHTML=`${filterBar}${reviewQueueHtml()}<div class="records-sections"><details open><summary><span><b>Transactions</b><small>${transactions.length} matching record${transactions.length===1?'':'s'}</small></span><i>Expand / collapse</i></summary><div class="record-list">${txRows}</div></details><details><summary><span><b>Intake paperwork</b><small>${documents.length} saved document${documents.length===1?'':'s'}</small></span><i>Expand / collapse</i></summary><div class="document-list">${documentRows}</div></details><details><summary><span><b>Security questionnaire</b><small>${security.metrics?.controls_assessed||0} controls assessed</small></span><i>Expand / collapse</i></summary><div class="record-list">${controls}</div></details>${outsideResearchRecordsHtml()}</div>`;
  bindRecordActions();$$('#recordsView [data-control]').forEach(button=>button.onclick=()=>selectControl(button.dataset.control));const clear=$('#recordsView [data-clear-record-filter]');if(clear)clear.onclick=()=>{state.recordFilter=null;renderRecordsModern()};
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
  if(state.view==='security-readiness'){
    const allControls=state.data.security.controls;
    const controls=state.readinessFilter==='gap'?allControls.filter(control=>control.status==='gap'):state.readinessFilter==='review'?allControls.filter(control=>['partial','review'].includes(control.status)):allControls;
    const filterLabel=state.readinessFilter==='gap'?'Control gaps':state.readinessFilter==='review'?'Needs review':'All controls';
    const bars=controls.map(control=>`<div class="bar-col" style="height:${control.confidence}%"><strong>${control.confidence}%</strong><span>${escapeHtml(control.id.replace('CTRL-',''))}</span></div>`).join('');
    const changes=controls.map(control=>`<button class="change-row" data-control="${escapeHtml(control.id)}"><b>${escapeHtml(control.name)}</b><strong class="${control.status==='gap'?'up':'down'}">${escapeHtml(control.status.toUpperCase())}</strong><small>${escapeHtml(control.contradiction)}</small></button>`).join('');
    $('#changeView').innerHTML=`<div class="readiness-filter-row"><b>${filterLabel}</b>${state.readinessFilter?'<button id="showAllReadiness" class="button ghost">Show all controls</button>':''}</div><div class="period-grid"><div class="chart-card depth-card"><h4>Evidence confidence by control</h4><div class="bar-chart depth-bars">${bars||'<p class="empty-chart">No controls match this view.</p>'}</div></div><div class="chart-card depth-card"><h4>${filterLabel}</h4><div class="change-list">${changes||'<p class="empty-state">Nothing matches this view.</p>'}</div></div></div>`;
    const showAll=$('#showAllReadiness');if(showAll)showAll.onclick=()=>{state.readinessFilter=null;renderChange()};
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
function renderGeo(){
  const vendors=(state.data.vendors||[]).filter(vendor=>vendor.city),groups={};
  vendors.forEach(vendor=>{groups[vendor.city]=groups[vendor.city]||[];groups[vendor.city].push(vendor)});
  const positions={'New York':[83,39],'Austin':[48,75],'Chicago':[61,38],'Seattle':[17,26],'San Francisco':[13,56],'San Jose':[14,60],'Boston':[88,31],'Memphis':[61,62],'Atlanta':[72,67]};
  const entries=Object.entries(groups),arcs=entries.map(([city])=>{const [x,y]=positions[city]||[50,50],px=x*9,py=y*5.2;return `<path class="coverage-arc" d="M450 280 Q ${Math.round((450+px)/2)} ${Math.max(70,Math.round(py-90))} ${px} ${py}"/><circle class="coverage-pulse" cx="${px}" cy="${py}" r="5"/>`}).join('');
  const points=entries.map(([city,items])=>{const [x,y]=positions[city]||[50,50];return `<button class="map-point" style="left:${x}%;top:${y}%" data-city="${escapeHtml(city)}" aria-label="Show ${escapeHtml(city)}, ${items.length} vendor${items.length===1?'':'s'}"><span>${escapeHtml(city)} · ${items.length}</span></button>`}).join('');
  const cards=entries.map(([city,items])=>`<details class="coverage-location" data-city-card="${escapeHtml(city)}"><summary><span><b>${escapeHtml(city)}</b><small>${items.length} vendor${items.length===1?'':'s'} with a saved location</small></span><strong>${items.length}</strong></summary><div>${items.map(vendor=>`<button class="coverage-vendor" data-vendor-record="vendor:${escapeHtml(vendor.id)}"><span>${escapeHtml(vendor.name)}</span><small>Open saved vendor details</small></button>`).join('')}</div></details>`).join('');
  $('#geoView').innerHTML=`<div class="geo-grid"><div class="map-stage coverage-map"><svg class="coverage-land" viewBox="0 0 900 520" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="landGlow" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#164d69"/><stop offset="1" stop-color="#071a2b"/></linearGradient><filter id="softGlow"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs><path class="coverage-shadow" d="M74 75 L230 38 342 73 430 61 516 96 655 102 810 173 848 248 796 306 712 331 657 390 550 419 475 386 385 411 305 366 213 339 153 271 92 222 42 142Z"/><path class="coverage-continent" d="M66 62 L224 28 338 64 426 52 515 88 659 94 821 165 861 239 806 299 718 323 662 385 548 411 473 377 382 403 298 357 207 331 145 263 82 214 31 132Z"/><path class="coverage-topo" d="M100 119 C230 70 337 133 451 103 S678 135 787 193 M88 178 C219 131 326 193 438 164 S653 174 803 238 M143 247 C252 208 349 258 455 230 S651 239 744 294 M221 312 C340 285 418 328 531 300 S654 301 695 341"/>${arcs}</svg>${points}<div class="map-depth-label"><span>PUBLIC LOCATION VIEW</span><b>Saved cities and connections</b><small>Open a city, then inspect the vendor record.</small></div></div><section class="coverage-list"><div class="coverage-list-head"><span class="section-label">SAVED LOCATIONS</span><h4>${entries.length} cit${entries.length===1?'y':'ies'}</h4></div>${cards||'<p class="empty-state">No vendor locations are saved for this company.</p>'}</section></div>`;
  $$('.map-point').forEach(button=>button.onclick=()=>{const card=$$('[data-city-card]').find(item=>item.dataset.cityCard===button.dataset.city);if(card){card.open=true;card.scrollIntoView({block:'nearest'});card.classList.add('highlight');setTimeout(()=>card.classList.remove('highlight'),900)}});
  $$('.coverage-vendor').forEach(button=>button.onclick=()=>openRecord(button.dataset.vendorRecord));
}
function expenseTotalsLabel(expenses){
  const totals={};
  expenses.forEach(expense=>{const currency=String(expense.currency||'USD').toUpperCase();totals[currency]=(totals[currency]||0)+safeCount(expense.amount_cents)});
  const entries=Object.entries(totals).sort(([left],[right])=>left.localeCompare(right));
  return entries.length?entries.map(([currency,total])=>safeMoney(total,currency)).join(' + '):'No spending';
}
function employeeSpendingSummary(employee){
  const reports=(state.data.expenses||[]).filter(expense=>String(expense.employee_id)===String(employee.id));
  return {employee,reports,total:expenseTotalsLabel(reports),missing:reports.filter(expense=>expense.receipt_status==='missing').length,review:reports.filter(expense=>expense.approval_status==='needs_review').length};
}
function renderPeople(){
  const employees=state.data.employees||[],summaries=employees.map(employeeSpendingSummary),allReports=state.data.expenses||[];
  const missing=allReports.filter(expense=>expense.receipt_status==='missing').length,review=allReports.filter(expense=>expense.approval_status==='needs_review').length,maxReports=Math.max(1,...summaries.map(item=>item.reports.length));
  const reviewShare=allReports.length?Math.round(review/allReports.length*100):0;
  const bars=summaries.map(item=>`<button class="people-bar-button" data-person-record="${escapeHtml(item.employee.id)}" aria-label="Open ${escapeHtml(item.employee.name)}, ${item.reports.length} reports"><span class="people-bar" style="--bar-height:${Math.max(18,Math.round(item.reports.length/maxReports*100))}%"><i></i></span><b>${escapeHtml(item.employee.name)}</b><small>${item.reports.length} report${item.reports.length===1?'':'s'}</small></button>`).join('');
  const cards=summaries.map(item=>`<article class="person-card ${item.missing||item.review?'needs-attention':''}"><button class="person-card-main" data-person-record="${escapeHtml(item.employee.id)}"><span><small>${escapeHtml([item.employee.department,item.employee.office].filter(Boolean).join(' · ')||'Employee')}</small><b>${escapeHtml(item.employee.name)}</b></span><strong>${escapeHtml(item.total)}</strong><i>Open person →</i></button><div class="person-stats"><span><b>${item.reports.length}</b> reports</span><span class="${item.missing?'warn':''}"><b>${item.missing}</b> missing receipts</span><span class="${item.review?'warn':''}"><b>${item.review}</b> need review</span></div><details class="person-reports"><summary>Show report list</summary><div>${item.reports.map(expense=>`<button data-expense-record="expense:${escapeHtml(expense.id)}"><span><b>${escapeHtml(expense.merchant||'Expense report')}</b><small>${escapeHtml(expense.spent_on||expense.date||'Date not saved')} · ${escapeHtml(String(expense.receipt_status||'unknown').replaceAll('_',' '))}</small></span><strong>${escapeHtml(safeMoney(expense.amount_cents,expense.currency))}</strong></button>`).join('')||'<p class="empty-state">No reports are attached to this person.</p>'}</div></details></article>`).join('');
  $('#peopleView').innerHTML=`<div class="people-dashboard"><section class="people-overview depth-card"><div class="people-overview-copy"><span class="section-label">COMPANY-SCOPED VIEW</span><h4>${employees.length} people · ${allReports.length} reports</h4><p>Spending stays with the company selected above. Amounts in different currencies are kept separate.</p><div class="people-totals"><div><b>${escapeHtml(expenseTotalsLabel(allReports))}</b><span>Total employee spend</span></div><div><b>${missing}</b><span>Missing receipts</span></div><div><b>${review}</b><span>Need review</span></div></div></div><div class="review-dial" style="--review-share:${reviewShare}" role="img" aria-label="${reviewShare}% of reports need review"><div><b>${reviewShare}%</b><span>need review</span></div></div></section><section class="people-depth-chart depth-card" aria-label="Reports by employee"><div class="people-chart-head"><div><span class="section-label">REPORT VOLUME</span><h4>People at a glance</h4></div><small>Choose a name to open details</small></div><div class="people-bars">${bars||'<p class="empty-state">No employees are loaded for this company.</p>'}</div></section><section class="people-card-grid">${cards||'<p class="empty-state">No employee spending records are loaded for this company.</p>'}</section></div>`;
  $$('#peopleView [data-person-record]').forEach(button=>button.onclick=()=>openPersonDetails(button.dataset.personRecord));
  $$('#peopleView [data-expense-record]').forEach(button=>button.onclick=event=>{event.stopPropagation();openRecord(button.dataset.expenseRecord)});
}
function openPersonDetails(employeeId){
  const employee=(state.data.employees||[]).find(item=>String(item.id)===String(employeeId));
  if(!employee){toast('That person is no longer available in this company.');return}
  const summary=employeeSpendingSummary(employee),reports=summary.reports.map(expense=>`<button class="person-drawer-report" data-expense-record="expense:${escapeHtml(expense.id)}"><span><b>${escapeHtml(expense.merchant||'Expense report')}</b><small>${escapeHtml(expense.spent_on||expense.date||'Date not saved')} · ${escapeHtml(String(expense.approval_status||'unknown').replaceAll('_',' '))}</small></span><strong>${escapeHtml(safeMoney(expense.amount_cents,expense.currency))}</strong></button>`).join('');
  openDrawer('PEOPLE & SPENDING',employee.name,`<div class="person-drawer-summary"><strong>${escapeHtml(summary.total)}</strong><span>across ${summary.reports.length} report${summary.reports.length===1?'':'s'}</span></div><div class="person-stats"><span><b>${summary.missing}</b> missing receipts</span><span><b>${summary.review}</b> need review</span></div><details class="plain-details" open><summary>Show expense reports</summary><div class="person-drawer-reports">${reports||'<p class="empty-state">No reports are attached to this person.</p>'}</div></details><details class="plain-details"><summary>Show saved employee details</summary>${detailHtml(employee)}</details>`);
  $$('#drawerContent [data-expense-record]').forEach(button=>button.onclick=()=>openRecord(button.dataset.expenseRecord));
}
function outsideResearchRecordsHtml(){
  const items=outsideResearchItems();
  if(!items.length)return '';
  const rows=items.slice(0,80).map((item,index)=>{
    const ref=outsideResearchNodeId(item,index),safeUrl=safeResearchUrl(item.url),host=safeUrl?new URL(safeUrl).hostname.replace(/^www\./i,''):'Link hidden';
    const site=safeUrl?`<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer nofollow">${escapeHtml(host)} ↗</a>`:escapeHtml(host);
    return `<tr class="unverified-web-row"><td><button data-research-record="${escapeHtml(ref)}">${escapeHtml(item.id||`Lead ${index+1}`)}</button></td><td>${escapeHtml(item.title||'Untitled outside result')}</td><td>${site}</td><td>${escapeHtml(item.source_label||'Tavily · outside research')}</td><td>${escapeHtml(readableTime(item.retrieved_at))}</td><td><span class="status-chip warn">unverified</span></td></tr>`;
  }).join('');
  return `<section class="web-records" aria-labelledby="webRecordsTitle"><div class="web-records-heading"><div><span class="section-label">OUTSIDE RESEARCH</span><h4 id="webRecordsTitle">Unverified leads</h4></div><p>These links may help a reviewer know where to look. They are not proof and do not close a finding.</p></div><div class="table-scroll"><table class="records-table"><thead><tr><th>Lead</th><th>Title</th><th>Site</th><th>Source</th><th>Found</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
function findingRecordRef(finding){
  const id=String(finding?.entity_id||'');
  if(id.startsWith('INV-'))return `invoice:${id}`;if(id.startsWith('TX-'))return `transaction:${id}`;if(id.startsWith('EMAIL-'))return `email:${id}`;if(id.startsWith('EXP-'))return `expense:${id}`;return null;
}
function reviewQueueHtml(){
  const findings=Array.isArray(state.data?.findings)?state.data.findings.filter(item=>item.status==='open'):[];
  const cards=findings.slice(0,8).map(finding=>{const ref=findingRecordRef(finding),urgent=finding.severity==='high';return `<article class="review-document ${urgent?'urgent':''}"><div class="review-document-head"><span class="status-chip warn">possible fraud - review</span><span>not proof</span></div><h5>${escapeHtml(finding.title)}</h5><p>${escapeHtml(finding.summary)}</p><details><summary>Why PayProof raised this</summary><p>${escapeHtml(finding.basis||'The saved records contain a pattern that needs a person to check.')}</p><small>Evidence references: ${escapeHtml((finding.evidence_ids||[]).join(', ')||'None recorded')}</small></details><div class="review-document-actions"><button class="button primary review-why" data-review-finding="${escapeHtml(finding.id)}">Ask why</button>${ref?`<button class="button ghost review-open" data-review-record="${escapeHtml(ref)}">Open record</button>`:''}</div></article>`}).join('');
  return `<section class="review-queue" aria-labelledby="reviewQueueTitle"><div class="review-queue-heading"><div><span class="section-label">DOCUMENT REVIEW LIST</span><h4 id="reviewQueueTitle">Possible fraud? Check first.</h4></div><span>${findings.length} open item${findings.length===1?'':'s'}</span></div><p class="review-guardrail">These are warning patterns, not fraud findings. Duplicate paperwork, missing receipts, new vendors, changed payment details, and suspicious instructions can have innocent explanations. A person must check the original records.</p><div class="review-document-grid">${cards||'<p class="empty-state">No saved records are currently in the possible-fraud review list.</p>'}</div></section>`;
}
function explainReviewFinding(findingId){
  const finding=(state.data.findings||[]).find(item=>String(item.id)===String(findingId));if(!finding)return;
  state.selectedFinding=finding.id;state.selectedId=findingRecordRef(finding)||state.selectedId;
  ask(`Why does ${finding.title} need review?`);
}
function bindRecordActions(){
  $$('[data-record]').forEach(button=>button.onclick=()=>openRecord(button.dataset.record));
  $$('[data-research-record]').forEach(button=>button.onclick=()=>openOutsideResearch(button.dataset.researchRecord));
  $$('.review-open').forEach(button=>button.onclick=()=>openRecord(button.dataset.reviewRecord));
  $$('.review-why').forEach(button=>button.onclick=()=>explainReviewFinding(button.dataset.reviewFinding));
}
function renderRecords(){
  const webRecords=outsideResearchRecordsHtml(),reviewQueue=reviewQueueHtml();
  if(state.workspace==='business'){
    const rows=state.data.security.evidence.map(e=>`<tr><td><button data-record="security:${escapeHtml(e.id)}">${escapeHtml(e.id)}</button></td><td>${escapeHtml(e.type)}</td><td>${escapeHtml(e.title)}</td><td>${escapeHtml(e.source)}</td><td>${escapeHtml(e.as_of)}</td><td>${escapeHtml(e.statement)}</td></tr>`).join('');
    $('#recordsView').innerHTML=`${reviewQueue}<section class="record-table-section"><h4>Saved assurance evidence</h4><table class="records-table"><thead><tr><th>Evidence</th><th>Type</th><th>Title</th><th>Source</th><th>As of</th><th>Observed statement</th></tr></thead><tbody>${rows}</tbody></table></section>${webRecords}`;
    bindRecordActions();return;
  }
  const rows=state.data.transactions.slice(0,80).map(t=>`<tr><td><button data-record="transaction:${escapeHtml(t.id)}">${escapeHtml(t.id)}</button></td><td>${escapeHtml(t.merchant_raw)}</td><td>${escapeHtml(safeMoney(t.amount_cents,t.currency))}</td><td>${escapeHtml(t.occurred_on)}</td><td>${escapeHtml(t.office)}</td><td>${escapeHtml(t.source_id)}</td></tr>`).join('');
  $('#recordsView').innerHTML=`${reviewQueue}<section class="record-table-section"><h4>Saved financial records</h4><table class="records-table"><thead><tr><th>Record</th><th>Merchant</th><th>Amount</th><th>Date</th><th>Office</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table></section>${webRecords}`;
  bindRecordActions();
}

async function openRecord(id){state.selectedId=id;try{const record=await api(`/api/records/${encodeURIComponent(id)}?workspace=${state.workspace}`);openDrawer('EVIDENCE RECORD',id,detailHtml(record));renderVisual()}catch(e){toast(e.message)}}
function openOutsideResearch(ref){
  const item=findOutsideResearch(ref);
  if(!item){toast('That outside research lead is no longer available.');return}
  const safeUrl=safeResearchUrl(item.url),title=String(item.title||'Outside research lead');
  const link=safeUrl?`<a class="button ghost" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer nofollow">Open original page ↗</a>`:'<p class="unsafe-link-note">The link was hidden because it was not a safe public web address.</p>';
  openDrawer('UNVERIFIED OUTSIDE LEAD',title,`<div class="notice warning"><b>This is a lead, not proof.</b> It does not verify the company, payment details, or finding. The finding stays open until a person checks an authoritative source.</div><div class="research-record-copy"><p>${escapeHtml(outsideResearchExcerpt(item)||'No excerpt was returned.')}</p>${link}</div><div class="detail-grid"><div class="detail-row"><span>Search used</span><strong>${escapeHtml(item.query||'Not recorded')}</strong></div><div class="detail-row"><span>Found</span><strong>${escapeHtml(readableTime(item.retrieved_at))}</strong></div><div class="detail-row"><span>Source</span><strong>${escapeHtml(item.source_label||'Tavily · outside research')}</strong></div><div class="detail-row"><span>Handling</span><strong>Outside page text is untrusted</strong></div></div>`);
}
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
function reconciliationMatchHtml(row,match){
  const bank=row.bank_transaction||{},context=match.context||{},items=Array.isArray(context.itemization)?context.itemization.filter(item=>String(item||'').trim()).slice(0,12):[];
  const emailFacts=[context.sender?`From ${context.sender}`:'',context.subject?`Subject: ${context.subject}`:'',context.received_at?`Received ${context.received_at}`:''].filter(Boolean);
  const stateLabel=String(row.match_state||'suggested').replaceAll('_',' ');
  return `<details class="match-detail"><summary><span><b>${escapeHtml(bank.description||bank.id||'Bank transaction')}</b><small>${escapeHtml(bank.posted_on||'')} ${bank.amount_cents!=null?`· ${escapeHtml(safeMoney(bank.amount_cents,bank.currency))}`:''}</small></span><span class="match-labels"><i>Suggested</i><i class="review">Review required</i>${row.ambiguous?'<i class="ambiguous">Ambiguous</i>':''}</span></summary><div class="match-context"><div class="match-source"><span>${escapeHtml(match.type||'evidence')}</span><b>${escapeHtml(match.evidence_id||'unknown')}</b><strong>${safeCount(match.confidence)}% · ${escapeHtml(stateLabel)}</strong></div>${emailFacts.length?`<p>${emailFacts.map(escapeHtml).join(' · ')}</p>`:''}${items.length?`<p class="itemization"><b>Items:</b> ${items.map(escapeHtml).join(' · ')}${Array.isArray(context.itemization)&&context.itemization.length>items.length?` · +${context.itemization.length-items.length} more`:''}</p>`:''}${context.untrusted_document_text?'<p class="untrusted-note">Email text is treated as untrusted evidence. The message snippet is intentionally hidden.</p>':''}</div></details>`;
}
function reconciliationHtml(reconciliation){
  const summary=reconciliation?.summary||{},rows=Array.isArray(reconciliation?.rows)?reconciliation.rows:[];
  const matches=rows.filter(row=>Array.isArray(row.matches)&&row.matches.length).flatMap(row=>row.matches.slice(0,3).map(match=>reconciliationMatchHtml(row,match))).slice(0,8).join('');
  return `<details class="reconciliation-box"><summary><span>Evidence matching</span><b>${safeCount(summary.with_suggestions)} suggested · ${safeCount(summary.unmatched)} unmatched</b></summary><p>Bank rows are compared with invoices, receipts, intake expenses, and imported email. Every match is a suggestion and requires review; none is confirmed automatically.</p><div class="match-list">${matches||'<p class="empty-state">No suggested evidence matches yet.</p>'}</div></details>`;
}
function importedSourceHtml(source){
  const id=escapeHtml(source.id),kind=String(source.kind||'source');
  const webResearch=kind==='web'||kind==='tavily'||String(source.id||'').startsWith('web:');
  const removalCopy=kind==='gmail'?'Remove imported Gmail evidence from this workspace. This does not disconnect Gmail.':webResearch?'Remove this saved outside research from PayProof. This removes only the local research copy; it does not change Tavily or any web page.':'Remove this imported source and recalculate the workspace.';
  return `<article class="source-card compact"><div class="source-card-head"><b>${escapeHtml(source.label||source.id)}</b><span class="status-chip">${escapeHtml(kind)} · ${safeCount(source.record_count)} records</span></div><p>${removalCopy}</p><button class="button danger remove-source" data-source-id="${id}">Preview removal</button></article>`;
}
function outsideResearchSectionHtml(tavily,currentWorkspace){
  const ready=tavily?.configured===true,items=outsideResearchItems();
  const query=state.outsideResearchQueryByWorkspace[state.workspace]??outsideResearchDefaultQuery(currentWorkspace);
  return `<section class="settings-section research-section" aria-labelledby="outsideResearchTitle">
    <div class="settings-heading"><div><span class="section-label">OUTSIDE RESEARCH</span><h3 id="outsideResearchTitle">Public web leads</h3></div><span class="status-chip ${ready?'':'warn'}">${ready?'ready':'off'}</span></div>
    <p>Search can point a reviewer toward public pages. Results are relevance-ranked, unverified leads—not proof of identity, registration, ownership, or payment details. Any related finding stays open.</p>
    <div class="research-privacy"><b>Keep the search public.</b> Your search words are sent to Tavily. Use only public company or vendor terms, never account numbers, amounts, private email addresses, or other confidential details.</div>
    ${ready?'':noticeHtml('Outside research is off because this server does not have a Tavily key. Add the key on the server to enable searching.','info')}
    <form id="outsideResearchForm" class="research-form">
      <label>What should I look for?<input id="outsideResearchQuery" name="query" maxlength="240" autocomplete="off" spellcheck="false" value="${escapeHtml(query)}" ${ready?'':'disabled'}></label>
      <label>Number of leads<select id="outsideResearchMaxResults" name="max_results" ${ready?'':'disabled'}><option>3</option><option selected>5</option><option>10</option></select></label>
      <button id="outsideResearchSearch" class="button primary" type="submit" ${ready?'':'disabled'}>Find public leads</button>
    </form>
    <div id="outsideResearchStatus" aria-live="polite"></div>
    <div class="research-results-heading"><b>Saved for ${escapeHtml(currentWorkspace?.name||state.workspace)}</b><span>${items.length} unverified lead${items.length===1?'':'s'}</span></div>
    <div class="research-results">${outsideResearchCardsHtml(items)}</div>
  </section>`;
}
function intakeExpenseHtml(expense){
  return `<article class="intake-row"><div><b>${escapeHtml(expense.id)}</b><span>${escapeHtml(expense.merchant)} · ${escapeHtml(safeMoney(expense.amount_cents,expense.currency))}</span><small>${escapeHtml(expense.spent_on)} · ${escapeHtml(expense.receipt_status)} · ${escapeHtml(expense.approval_status)}</small></div><button class="button ghost edit-intake" data-expense-id="${escapeHtml(expense.id)}">Edit & history</button></article>`;
}
function companyIdentityHtml(current){
  const name=String(current?.name||state.workspace),logoUrl=safeCompanyLogoUrl(current?.logo_url,current?.id),websiteUrl=safeWebsiteUrl(current?.website),initials=workspaceInitials(name);
  return `<div class="company-profile-summary"><div class="company-profile-logo"><img id="companyProfileLogo" src="${logoUrl?escapeHtml(logoUrl):''}" alt="${escapeHtml(name)} logo" ${logoUrl?'':'hidden'}><span id="companyProfileInitials" ${logoUrl?'hidden':''}>${escapeHtml(initials)}</span></div><div class="company-profile-copy"><strong>${escapeHtml(name)}</strong>${websiteUrl?`<a href="${escapeHtml(websiteUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(new URL(websiteUrl).hostname.replace(/^www\./i,''))} ↗</a>`:'<span>No company website saved</span>'}</div></div>`;
}
function archivedCompanyHtml(company){
  const websiteUrl=safeWebsiteUrl(company.website);
  return `<article class="archived-company"><div><b>${escapeHtml(company.name)}</b><span>Removed ${escapeHtml(readableTime(company.archived_at))}</span>${websiteUrl?`<a href="${escapeHtml(websiteUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(new URL(websiteUrl).hostname.replace(/^www\./i,''))} ↗</a>`:''}</div><button class="button ghost restore-company" data-workspace-id="${escapeHtml(company.id)}">Restore</button></article>`;
}
function companyManagerHtml(workspaces,current,archivedWorkspaces=[]){
  const options=workspaces.map(workspace=>`<option value="${escapeHtml(workspace.id)}" ${workspace.id===state.workspace?'selected':''}>${escapeHtml(workspace.name)}${workspace.is_demo?' · demo':''}</option>`).join('');
  const custom=current?.kind==='company'&&current?.is_demo!==true;
  return `<section class="settings-section company-manager" aria-labelledby="companySettingsTitle">
    <div class="settings-heading"><div><span class="section-label">ACTIVE COMPANY</span><h3 id="companySettingsTitle">Company manager</h3></div><span class="status-chip ${custom?'good':''}">${custom?'custom company':'demo workspace'}</span></div>
    <p>Banks, Gmail authorization, statement imports, and intake folders connect only to the company selected here. Switching companies clears the visible chat context before loading the next company.</p>
    ${companyIdentityHtml(current)}
    <div class="company-switcher"><label>Selected company<select id="settingsWorkspaceSelect">${options}</select></label><button id="switchSettingsWorkspace" class="button primary" disabled>Switch company</button></div>
    <dl class="company-counts"><div><dt>Bank records</dt><dd>${safeCount(current?.bank_transaction_count)}</dd></div><div><dt>Gmail evidence</dt><dd>${safeCount(current?.gmail_evidence_count)}</dd></div><div><dt>Enabled intake folders</dt><dd>${safeCount(current?.intake_folder_count)}</dd></div></dl>
    ${custom?`<div class="company-profile-settings"><form id="renameCompanyForm" class="company-profile-form"><label>Company name<input name="name" minlength="2" maxlength="100" required value="${escapeHtml(current.name)}"></label><label>Website <span class="source-meta">optional</span><input name="website" type="url" inputmode="url" maxlength="500" placeholder="https://example.com" value="${escapeHtml(current.website||'')}"></label><button class="button ghost" type="submit">Save profile</button></form><div class="company-logo-controls"><label class="file-field">Company logo <span class="source-meta">PNG, JPEG, or WebP · 2 MB maximum</span><input id="companyLogoFile" type="file" accept="image/png,image/jpeg,image/webp"></label><div class="modal-actions"><button id="uploadCompanyLogo" class="button ghost" type="button">Upload logo</button>${current.logo_url?'<button id="removeCompanyLogo" class="button danger" type="button">Remove logo</button>':''}</div></div><div class="company-transfer"><div><b>Transfer financial records</b><p>Download a portable, independently readable package for a buyer, accountant, or successor team.</p></div><button id="transferCompanyRecords" class="button ghost" type="button">Transfer financial records</button></div><div class="company-lifecycle"><div><b>Remove this company</b><p>Removal archives the company from active use. All records, source connections, intake assignments, and history stay preserved for restoration.</p></div><button id="archiveCompany" class="button danger" type="button">Remove company</button></div></div>`:'<p class="source-meta">Demo workspace branding is built in. Create a custom company to add its website and logo. Demo workspaces cannot be removed.</p>'}
    <details class="add-company"><summary>Add another company</summary><form id="createCompanyForm" class="company-create-form"><label>New company name<input name="name" minlength="2" maxlength="100" required placeholder="Example: Northstar Studio"></label><label>Website <span class="source-meta">optional</span><input name="website" type="url" inputmode="url" maxlength="500" placeholder="https://northstar.example"></label><button class="button primary" type="submit">Create & select</button></form></details>
    ${archivedWorkspaces.length?`<details class="archived-companies"><summary>Archived companies (${archivedWorkspaces.length})</summary><p>Restore a company to return it to the active selector with its preserved records and connections.</p><div class="archived-company-list">${archivedWorkspaces.map(archivedCompanyHtml).join('')}</div></details>`:''}
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
    api('/api/workspaces?include_archived=true'),
    api(`/api/workspaces/${encodeURIComponent(workspace)}/intake-folders`)
  ]);
  if(workspace!==state.workspace||generation!==state.sourceGeneration)return;
  state.bankPreview=null;
  const bank=s.bank||{},gmail=s.gmail||{},tavily=s.tavily||{},connections=Array.isArray(bank.connections)?bank.connections:[];
  const allWorkspaces=Array.isArray(workspaceResult.workspaces)?workspaceResult.workspaces:[],workspaces=allWorkspaces.filter(item=>item.is_archived!==true),archivedWorkspaces=allWorkspaces.filter(item=>item.is_archived===true),currentWorkspace=workspaces.find(item=>item.id===workspace)||{id:workspace,name:workspace,kind:'company',is_demo:false};
  const folders=Array.isArray(folderResult.folders)?folderResult.folders:[],enabledFolders=folders.filter(folder=>folder.enabled===true);
  state.sourceConfig={...s,workspaces,archivedWorkspaces,intakeFolders:folders,currentWorkspace};
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
    ${companyManagerHtml(workspaces,currentWorkspace,archivedWorkspaces)}
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
    ${outsideResearchSectionHtml(tavily,currentWorkspace)}
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
  const profileLogo=$('#companyProfileLogo'),profileInitials=$('#companyProfileInitials');
  if(profileLogo){const showLogo=visible=>{profileLogo.hidden=!visible;if(profileInitials)profileInitials.hidden=visible};profileLogo.onload=()=>showLogo(true);profileLogo.onerror=()=>{showLogo(false);profileLogo.removeAttribute('src')};if(profileLogo.complete)showLogo(profileLogo.naturalWidth>0)}
  const settingsWorkspace=$('#settingsWorkspaceSelect'),switchWorkspaceButton=$('#switchSettingsWorkspace');
  settingsWorkspace.onchange=()=>{switchWorkspaceButton.disabled=settingsWorkspace.value===state.workspace};
  switchWorkspaceButton.onclick=()=>switchWorkspace(settingsWorkspace.value,settingsWorkspace.selectedOptions[0]?.textContent||settingsWorkspace.value,true);
  const createCompanyForm=$('#createCompanyForm');if(createCompanyForm)createCompanyForm.onsubmit=createCompany;
  const renameCompanyForm=$('#renameCompanyForm');if(renameCompanyForm)renameCompanyForm.onsubmit=renameCompany;
  const uploadCompanyLogoButton=$('#uploadCompanyLogo');if(uploadCompanyLogoButton)uploadCompanyLogoButton.onclick=uploadCompanyLogo;
  const removeCompanyLogoButton=$('#removeCompanyLogo');if(removeCompanyLogoButton)removeCompanyLogoButton.onclick=previewCompanyLogoRemoval;
  const transferCompanyButton=$('#transferCompanyRecords');if(transferCompanyButton)transferCompanyButton.onclick=previewCompanyTransfer;
  const archiveCompanyButton=$('#archiveCompany');if(archiveCompanyButton)archiveCompanyButton.onclick=previewCompanyArchive;
  $$('.restore-company').forEach(button=>button.onclick=()=>previewCompanyRestore(button.dataset.workspaceId));
  const connectBank=$('#connectBank');if(connectBank&&!connectBank.disabled)connectBank.onclick=startPlaidConnect;
  $$('.bank-sync').forEach(button=>button.onclick=()=>syncBankConnection(button.dataset.bankId,button));
  $$('.bank-disconnect').forEach(button=>button.onclick=()=>previewBankDisconnect(button.dataset.bankId));
  $('#previewBankStatement').onclick=previewBankStatement;
  const gmailConnect=$('#gmailConnect');if(gmailConnect&&!gmailConnect.disabled)gmailConnect.onclick=openGmailConnect;
  const gmailImport=$('#gmailImport');if(gmailImport&&!gmailImport.disabled)gmailImport.onclick=importGmailEvidence;
  const gmailDisconnect=$('#gmailDisconnect');if(gmailDisconnect)gmailDisconnect.onclick=previewGmailDisconnect;
  const outsideResearchForm=$('#outsideResearchForm'),outsideResearchQuery=$('#outsideResearchQuery');
  if(outsideResearchQuery)outsideResearchQuery.oninput=()=>{state.outsideResearchQueryByWorkspace[state.workspace]=outsideResearchQuery.value};
  if(outsideResearchForm&&!$('#outsideResearchSearch')?.disabled)outsideResearchForm.onsubmit=searchOutsideResearch;
  const scanAllIntake=$('#scanAllIntake');if(scanAllIntake&&!scanAllIntake.disabled)scanAllIntake.onclick=()=>scanIntakeFolder();
  const addIntakeFolderForm=$('#addIntakeFolderForm');if(addIntakeFolderForm)addIntakeFolderForm.onsubmit=addIntakeFolder;
  $$('.scan-folder').forEach(button=>button.onclick=()=>scanIntakeFolder(button.dataset.folderId));
  $$('.edit-folder').forEach(button=>button.onclick=()=>openIntakeFolderEditor(button.dataset.folderId));
  $$('.toggle-folder').forEach(button=>button.onclick=()=>toggleIntakeFolder(button.dataset.folderId,button));
  $$('.remove-folder').forEach(button=>button.onclick=()=>previewIntakeFolderRemoval(button.dataset.folderId));
  $$('.edit-intake').forEach(button=>button.onclick=()=>openIntakeEditor(button.dataset.expenseId));
  $$('.remove-source').forEach(button=>button.onclick=()=>previewImportedSourceRemoval(button.dataset.sourceId));
}
async function searchOutsideResearch(event){
  event.preventDefault();
  const workspace=state.workspace,form=event.currentTarget,button=$('#outsideResearchSearch'),status=$('#outsideResearchStatus');
  const data=new FormData(form),query=String(data.get('query')||'').trim(),maxResults=Math.max(1,Math.min(10,Number.parseInt(data.get('max_results'),10)||5));
  state.outsideResearchQueryByWorkspace[workspace]=query;
  if(query.length<3){if(status)status.innerHTML=noticeHtml('Use at least three characters so the search has a clear public subject.','warning');return}
  if(button){button.disabled=true;button.textContent='Looking for public leads…'}
  if(status)status.innerHTML=noticeHtml('Searching the public web. No finding will be closed by these results.','info');
  let result;
  try{
    result=await api('/api/sources/tavily/search',jsonRequest('POST',{workspace,query,max_results:maxResults}));
  }catch(error){
    if(workspace===state.workspace&&status)status.innerHTML=apiErrorHtml(error);
    if(button){button.disabled=false;button.textContent='Find public leads'}
    return;
  }
  if(workspace!==state.workspace){toast(`Outside research was saved to ${workspace}.`);return}
  const returned=Array.isArray(result.results)?result.results:Array.isArray(result.web_evidence)?result.web_evidence:[];
  if(returned.length)state.outsideResearchResultsByWorkspace[workspace]=returned;
  const reportedCount=safeCount(result.added||result.accepted||result.saved_count),count=reportedCount||returned.length;
  const countText=count?`${count} unverified lead${count===1?' was':'s were'} saved.`:'The search finished with no new leads.';
  try{
    await loadData();
    await sourcesDrawer(`${countText} Nothing was verified, and the finding is still open.`,count?'success':'info');
  }catch(error){
    if(status)status.innerHTML=`${noticeHtml(`${countText} The page could not refresh yet, but no finding was closed.`,'warning')}${apiErrorHtml(error)}`;
    if(button){button.disabled=false;button.textContent='Find public leads'}
  }
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
  state.view='overview';state.recordFilter=null;state.assistantSpotlight=null;
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
  if(state.voice.recognition||state.voice.micState!=='off')cancelVoiceCapture('Microphone stopped when the active company changed.');
  window.speechSynthesis?.cancel?.();
  state.sourceGeneration+=1;
  state.workspace=nextWorkspace;
  state.sourceConfig=null;
  resetWorkspaceContext(nextWorkspace);
  if(reopenSources)openDrawer('CONNECTIONS & AUDIT','Switching company',noticeHtml(`Loading ${companyLabel} without carrying over the previous company context...`,'info'));
  else closeDrawer();
  try{
    const loaded=await loadData('Switching company…');
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
  const form=event.currentTarget,submit=form.querySelector('[type="submit"]'),originWorkspace=state.workspace,data=new FormData(form);
  const name=String(data.get('name')||'').trim(),websiteInput=String(data.get('website')||'').trim(),website=safeWebsiteUrl(websiteInput);
  if(name.length<2){setSourceAction(noticeHtml('Enter a company name with at least 2 characters.','error'));return}
  if(websiteInput&&!website){setSourceAction(noticeHtml('Enter a valid company website using http:// or https://.','error'));return}
  submit.disabled=true;setSourceAction(noticeHtml(`Creating ${name} as a separate company...`,'info'));
  try{
    const payload={name};if(website)payload.website=website;
    const result=await api('/api/workspaces',jsonRequest('POST',payload));
    const company=result.workspace||result.company||result;
    if(!company?.id)throw new Error('The server created the company but did not return its identifier.');
    if(state.workspace!==originWorkspace){toast(`${company.name||name} was created. Select it from the company menu when ready.`);return}
    await switchWorkspace(company.id,company.name||name,true,`Created ${company.name||name}. Bank, Gmail, and intake sources can now be attached to this company.`);
  }catch(error){if(state.workspace===originWorkspace)setSourceAction(apiErrorHtml(error));else toast(`Company creation failed: ${error.message}`)}
  finally{if(submit.isConnected)submit.disabled=false}
}
async function renameCompany(event){
  event.preventDefault();
  const form=event.currentTarget,submit=form.querySelector('[type="submit"]'),workspace=state.workspace,data=new FormData(form);
  const current=state.sourceConfig?.currentWorkspace;
  if(!current||current.kind!=='company'||current.is_demo===true){setSourceAction(noticeHtml('Built-in demo workspace profiles cannot be changed.','warning'));return}
  const name=String(data.get('name')||'').trim(),websiteInput=String(data.get('website')||'').trim(),website=safeWebsiteUrl(websiteInput);
  if(name.length<2){setSourceAction(noticeHtml('Enter a company name with at least 2 characters.','error'));return}
  if(websiteInput&&!website){setSourceAction(noticeHtml('Enter a valid company website using http:// or https://.','error'));return}
  const changes={},currentWebsite=safeWebsiteUrl(current.website)||'';
  if(name!==current.name)changes.name=name;
  if((website||'')!==currentWebsite)changes.website=website||'';
  if(!Object.keys(changes).length){setSourceAction(noticeHtml('Change the company name or website before saving.','warning'));return}
  submit.disabled=true;setSourceAction(noticeHtml('Saving this company profile...','info'));
  try{
    const result=await api(`/api/workspaces/${encodeURIComponent(workspace)}`,jsonRequest('PATCH',changes));
    if(state.workspace!==workspace){toast(`${result.name||name} profile was updated.`);return}
    await loadData();
    if(state.workspace!==workspace)return;
    await sourcesDrawer(`Updated the ${result.name||name} profile. Its connected sources and imported records stayed attached.`,'success');
  }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Company profile update failed: ${error.message}`)}
  finally{if(submit.isConnected)submit.disabled=false}
}
async function uploadCompanyLogo(event){
  const button=event.currentTarget,input=$('#companyLogoFile'),file=input?.files?.[0],workspace=state.workspace,current=state.sourceConfig?.currentWorkspace;
  if(!current||current.kind!=='company'||current.is_demo===true){setSourceAction(noticeHtml('Only a custom company can upload a logo.','warning'));return}
  if(!file){setSourceAction(noticeHtml('Choose a PNG, JPEG, or WebP logo first.','warning'));return}
  const allowed=new Set(['image/png','image/jpeg','image/webp']);
  if(file.type&&!allowed.has(file.type.toLowerCase())){setSourceAction(noticeHtml('Logo files must be PNG, JPEG, or WebP.','error'));return}
  if(file.size>2*1024*1024){setSourceAction(noticeHtml('Company logos must be 2 MB or smaller.','error'));return}
  button.disabled=true;setSourceAction(noticeHtml('Uploading this logo to the active company profile...','info'));
  const form=new FormData();form.append('logo',file,file.name);
  try{
    await api(`/api/workspaces/${encodeURIComponent(workspace)}/logo`,{method:'POST',body:form});
    if(state.workspace!==workspace){toast(`The logo was updated for ${current.name}.`);return}
    await loadData();
    if(state.workspace!==workspace)return;
    await sourcesDrawer(`Updated the ${current.name} logo. Only this company uses it.`,'success');
  }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Logo upload failed: ${error.message}`)}
  finally{if(button.isConnected)button.disabled=false}
}
function previewCompanyLogoRemoval(){
  const workspace=state.workspace,current=state.sourceConfig?.currentWorkspace;
  if(!current||current.kind!=='company'||current.is_demo===true){setSourceAction(noticeHtml('Only a custom company logo can be removed.','warning'));return}
  if(!current.logo_url){setSourceAction(noticeHtml('This company does not have a stored logo.','info'));return}
  setSourceAction(`<div class="confirmation-card"><span class="section-label">REMOVE COMPANY LOGO</span><h3>${escapeHtml(current.name)}</h3><div class="notice warning">Confirming removes only PayProof's stored logo for this company. The company, its website, connected sources, and imported records are unchanged.</div><div class="modal-actions"><button id="confirmCompanyLogoRemoval" class="button danger">Confirm logo removal</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
  $('#cancelSourceAction').onclick=()=>setSourceAction('');
  $('#confirmCompanyLogoRemoval').onclick=async event=>{
    event.currentTarget.disabled=true;
    try{
      const result=await api(`/api/workspaces/${encodeURIComponent(workspace)}/logo`,jsonRequest('DELETE',{confirm:true}));
      if(state.workspace!==workspace){toast(`The logo was removed from ${current.name}.`);return}
      await loadData();
      if(state.workspace!==workspace)return;
      const message=result.logo_removed?`Removed the ${current.name} logo. Its company data and sources were unchanged.`:`${current.name} no longer has a stored logo.`;
      await sourcesDrawer(message,result.file_cleanup_pending?'warning':'success');
    }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Logo removal failed: ${error.message}`)}
  };
}
function previewCompanyTransfer(){
  const workspace=state.workspace,current=state.sourceConfig?.currentWorkspace;
  if(!current||current.kind!=='company'||current.is_demo===true){setSourceAction(noticeHtml('Transfer packages are available only for a custom company.','warning'));return}
  setSourceAction(`<div class="confirmation-card"><span class="section-label">TRANSFER FINANCIAL RECORDS</span><h3>${escapeHtml(current.name)}</h3><div class="notice info"><b>This creates a portable ZIP that can be opened without PayProof.</b> It includes browser-readable HTML, Excel-safe CSV, structured JSON, and a SHA-256 manifest so the recipient can verify the files.</div><div class="notice warning">Credentials, access tokens, connector configuration, and raw intake files are excluded. A buyer or successor must reconnect their own bank and email accounts.</div><label id="transferCompanyNameLabel">Type <strong>${escapeHtml(current.name)}</strong> exactly to confirm<input id="transferCompanyNameConfirm" autocomplete="off" spellcheck="false"></label><div class="modal-actions"><button id="confirmCompanyTransfer" class="button primary" disabled>Download transfer package</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
  const confirmationName=$('#transferCompanyNameConfirm'),confirmButton=$('#confirmCompanyTransfer');
  confirmationName.oninput=()=>{confirmButton.disabled=confirmationName.value!==current.name};
  $('#cancelSourceAction').onclick=()=>setSourceAction('');
  confirmButton.onclick=async event=>{
    if(confirmationName.value!==current.name){confirmationName.focus();return}
    event.currentTarget.disabled=true;
    setSourceAction(noticeHtml(`Building the transfer package for ${current.name}...`,'info'));
    try{
      const response=await fetch(`/api/workspaces/${encodeURIComponent(workspace)}/transfer-package`,jsonRequest('POST',{confirm:true,company_name:current.name}));
      if(!response.ok){
        let payload={};
        try{payload=await response.json()}catch{}
        const error=new Error(payload.error||payload.errors?.join(', ')||`Transfer package failed (${response.status}).`);error.payload=payload;error.status=response.status;throw error;
      }
      const blob=await response.blob();
      if(!blob.size)throw new Error('The server returned an empty transfer package.');
      const fallback=`${current.name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')||'company'}-payproof-transfer.zip`;
      const filename=safeTransferFilename(response.headers.get('Content-Disposition'),fallback),objectUrl=URL.createObjectURL(blob),anchor=document.createElement('a');
      try{
        anchor.href=objectUrl;anchor.download=filename;anchor.hidden=true;document.body.append(anchor);anchor.click();anchor.remove();
      }finally{window.setTimeout(()=>URL.revokeObjectURL(objectUrl),1000)}
      if(state.workspace===workspace)setSourceAction(noticeHtml(`Downloaded ${filename}. The recipient can inspect the HTML and CSV without PayProof and verify every exported file with the SHA-256 manifest.`,'success'));
      else toast(`${current.name} transfer package downloaded.`);
    }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Transfer package failed: ${error.message}`)}
  };
}
function previewCompanyArchive(){
  const workspace=state.workspace,current=state.sourceConfig?.currentWorkspace;
  if(!current||current.kind!=='company'||current.is_demo===true){setSourceAction(noticeHtml('Demo workspaces cannot be removed.','warning'));return}
  setSourceAction(`<div class="confirmation-card"><span class="section-label">REMOVE COMPANY FROM ACTIVE USE</span><h3>${escapeHtml(current.name)}</h3><div class="notice warning"><b>This archives the company; it does not erase it.</b> All financial records, evidence, bank and Gmail connections, intake folders, logos, and audit history remain preserved and can be restored later.</div><label id="archiveCompanyNameLabel">Type <strong>${escapeHtml(current.name)}</strong> exactly to confirm<input id="archiveCompanyNameConfirm" autocomplete="off" spellcheck="false"></label><div class="modal-actions"><button id="confirmCompanyArchive" class="button danger" disabled>Remove company</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
  const confirmationName=$('#archiveCompanyNameConfirm'),confirmButton=$('#confirmCompanyArchive');
  confirmationName.oninput=()=>{confirmButton.disabled=confirmationName.value!==current.name};
  $('#cancelSourceAction').onclick=()=>setSourceAction('');
  confirmButton.onclick=async event=>{
    if(confirmationName.value!==current.name){confirmationName.focus();return}
    event.currentTarget.disabled=true;
    try{
      const result=await api(`/api/workspaces/${encodeURIComponent(workspace)}`,jsonRequest('DELETE',{confirm:true,company_name:current.name}));
      if(state.workspace!==workspace){toast(`${current.name} was removed from the active company list. Its records remain preserved.`);return}
      const nextWorkspace=String(result.next_workspace||'business'),next=state.sourceConfig?.workspaces?.find(item=>item.id===nextWorkspace);
      const preserved=result.records_preserved===true&&result.connections_preserved===true;
      await switchWorkspace(nextWorkspace,next?.name||nextWorkspace,true,preserved?`${current.name} was removed from active use. All records and connections were preserved; restore it from Archived companies at any time.`:`${current.name} was archived, but the server returned an unexpected preservation status.`);
    }catch(error){if(state.workspace===workspace)setSourceAction(apiErrorHtml(error));else toast(`Company removal failed: ${error.message}`)}
  };
}
function previewCompanyRestore(workspaceId){
  const originWorkspace=state.workspace,company=(state.sourceConfig?.archivedWorkspaces||[]).find(item=>String(item.id)===String(workspaceId));
  if(!company){setSourceAction(noticeHtml('That archived company is no longer available. Refresh and try again.','warning'));return}
  setSourceAction(`<div class="confirmation-card"><span class="section-label">RESTORE ARCHIVED COMPANY</span><h3>${escapeHtml(company.name)}</h3><div class="notice info">Restoring returns this company to the active selector with its preserved records, evidence, connections, intake folders, branding, and audit history.</div><div class="modal-actions"><button id="confirmCompanyRestore" class="button primary">Confirm restore</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
  $('#cancelSourceAction').onclick=()=>setSourceAction('');
  $('#confirmCompanyRestore').onclick=async event=>{
    event.currentTarget.disabled=true;
    try{
      const result=await api(`/api/workspaces/${encodeURIComponent(company.id)}/restore`,jsonRequest('POST',{confirm:true}));
      if(state.workspace!==originWorkspace){toast(`${company.name} was restored to the active company list.`);return}
      await sourcesDrawer(result.restored?`${company.name} was restored with all preserved records and connections.`:`${company.name} is already active.`,'success');
    }catch(error){if(state.workspace===originWorkspace)setSourceAction(apiErrorHtml(error));else toast(`Company restore failed: ${error.message}`)}
  };
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
  const workspace=state.workspace,webResearch=String(sourceId||'').startsWith('web:');
  setSourceAction(noticeHtml('Calculating which local records would be removed…','info'));
  try{
    const params=new URLSearchParams({workspace});
    const preview=await api(`/api/sources/${encodeURIComponent(sourceId)}/removal-preview?${params}`);
    if(state.workspace!==workspace)return;
    const removalNotice=webResearch?'Only this saved local research will be removed. Nothing is deleted from Tavily or the public web, and the finding stays open.':'Only these local PayProof records will be removed. Provider data and connection permissions are unchanged.';
    setSourceAction(`<div class="confirmation-card"><span class="section-label">SOURCE REMOVAL PREVIEW</span><h3>${escapeHtml(preview.filename||preview.source_id)}</h3>${affectedHtml(preview.affected)}<div class="notice warning">${removalNotice}</div><div class="modal-actions"><button id="confirmSourceRemoval" class="button danger">Confirm removal</button><button id="cancelSourceAction" class="button ghost">Cancel</button></div></div>`);
    $('#cancelSourceAction').onclick=()=>setSourceAction('');
    $('#confirmSourceRemoval').onclick=async event=>{
      event.currentTarget.disabled=true;
      try{
        const params=new URLSearchParams({workspace,preview_id:preview.preview_id,confirm:'true'});
        const result=await api(`/api/sources/${encodeURIComponent(sourceId)}?${params}`,{method:'DELETE'});
        if(state.workspace!==workspace){toast(`Source removed from ${workspace}.`);return}
        if(webResearch)state.outsideResearchResultsByWorkspace[workspace]=[];
        await loadData();await sourcesDrawer(webResearch?`Removed ${safeCount(result.removed)} saved research lead(s) from PayProof only. Tavily, public pages, and the finding were unchanged.`:`Removed ${safeCount(result.removed)} local record(s). Upstream provider data was not changed.`,'success');
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

function isEligibleBrowserReplyVoice(voice){
  const label=`${voice?.name||''} ${voice?.voiceURI||''}`;
  const preferred=/\b(Aria|Jenny|Ava|Emma|Sonia|Natasha|Libby|Michelle)\b/i;
  return preferred.test(label)&&/(natural|neural|online)/i.test(label)&&voice?.localService!==true&&!/(offline|robot|robotic|espeak|festival)/i.test(label);
}
function eligibleBrowserReplyVoice(){
  if(!window.speechSynthesis||typeof window.speechSynthesis.getVoices!=='function')return null;
  const preference=['aria','jenny','ava','emma','sonia','natasha','libby','michelle'];
  const eligible=window.speechSynthesis.getVoices().filter(isEligibleBrowserReplyVoice).sort((left,right)=>preference.findIndex(name=>String(left.name||'').toLowerCase().includes(name))-preference.findIndex(name=>String(right.name||'').toLowerCase().includes(name)));
  const language=String(navigator.language||'').split('-')[0].toLowerCase();
  return eligible.find(voice=>String(voice.lang||'').toLowerCase().startsWith(language))||eligible[0]||null;
}
function renderVoiceControls(message){
  if(typeof message==='string')state.voice.statusMessage=message;
  else if(message===null)state.voice.statusMessage='';
  const mic=$('#micToggle'),spoken=$('#spokenRepliesToggle'),status=$('#voiceStatus');
  if(!mic||!spoken||!status)return;
  const micLabels={off:'◉ Mic off',listening:'● Listening',processing:'… Processing'};
  mic.textContent=micLabels[state.voice.micState]||micLabels.off;
  mic.disabled=!state.voice.inputAvailable||state.voice.micState==='processing';
  mic.setAttribute('aria-pressed',String(state.voice.micState==='listening'));
  mic.classList.toggle('listening',state.voice.micState==='listening');
  mic.classList.toggle('processing',state.voice.micState==='processing');
  const replyAvailable=Boolean(state.voice.replyVoice&&window.speechSynthesis&&typeof window.SpeechSynthesisUtterance==='function');
  if(!replyAvailable)state.voice.spokenReplies=false;
  spoken.disabled=!replyAvailable;
  spoken.textContent=state.voice.spokenReplies?'♫ Spoken replies on':'♩ Spoken replies off';
  spoken.setAttribute('aria-pressed',String(state.voice.spokenReplies));
  spoken.classList.toggle('enabled',state.voice.spokenReplies);
  let defaultStatus='Voice controls are off and start only when clicked.';
  if(!state.voice.inputAvailable)defaultStatus='Microphone input is unavailable in this browser.';
  else if(state.voice.micState==='listening')defaultStatus='Listening now. Speak once; click again to cancel.';
  else if(state.voice.micState==='processing')defaultStatus='Processing the captured transcript.';
  else if(state.voice.spokenReplies&&state.voice.replyVoice)defaultStatus=`Mic off · spoken replies use browser voice ${state.voice.replyVoice.name}.`;
  else if(state.voice.replyVoice)defaultStatus='Mic off · an eligible browser voice is available; spoken replies remain off.';
  else defaultStatus='Mic off · no Natural, Neural, or Online browser voice is available, so replies stay text-only.';
  status.textContent=state.voice.statusMessage||defaultStatus;
}
function refreshEligibleReplyVoice(){
  state.voice.replyVoice=eligibleBrowserReplyVoice();
  if(!state.voice.replyVoice&&state.voice.spokenReplies){state.voice.spokenReplies=false;window.speechSynthesis?.cancel?.()}
  renderVoiceControls();
}
function speechRecognitionErrorMessage(code){
  if(code==='not-allowed'||code==='service-not-allowed')return 'Microphone permission was not granted. Enable it in browser site settings, then click Mic off to try again.';
  if(code==='audio-capture')return 'No working microphone was found by the browser.';
  if(code==='no-speech')return 'No speech was detected. Nothing was submitted.';
  if(code==='network')return 'The browser speech-recognition service could not be reached.';
  return `Voice input stopped${code?`: ${code}`:'.'}`;
}
function cancelVoiceCapture(message='Microphone input canceled. Nothing was submitted.'){
  const recognition=state.voice.recognition;
  if(recognition){recognition._payproofCancelled=true;try{recognition.abort()}catch{}state.voice.recognition=null}
  state.voice.micState='off';renderVoiceControls(message);
}
function toggleMicInput(){
  if(state.voice.micState==='listening'){cancelVoiceCapture('Listening stopped. Nothing was submitted.');return}
  if(!state.voice.inputAvailable){renderVoiceControls('Microphone input is unavailable in this browser.');return}
  if($('#chatSend').disabled){renderVoiceControls('Wait for the current answer before starting microphone input.');return}
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition,recognition=new Recognition();
  recognition.continuous=false;recognition.interimResults=true;recognition.maxAlternatives=1;recognition.lang=navigator.language||'en-US';
  recognition._payproofTranscript='';recognition._payproofCancelled=false;recognition._payproofError=false;recognition._payproofSubmitted=false;
  recognition.onstart=()=>{state.voice.micState='listening';renderVoiceControls('Listening now. Speak once; click again to cancel.')};
  recognition.onresult=event=>{
    let interim='',hasFinal=false;
    for(let index=event.resultIndex;index<event.results.length;index+=1){const transcript=String(event.results[index][0]?.transcript||'').trim();if(event.results[index].isFinal){if(transcript)recognition._payproofTranscript+=`${transcript} `;hasFinal=true}else interim+=`${transcript} `}
    const visible=`${recognition._payproofTranscript} ${interim}`.trim();if(visible)$('#chatInput').value=visible;
    if(hasFinal){state.voice.micState='processing';renderVoiceControls('Processing the captured transcript.');try{recognition.stop()}catch{}}
  };
  recognition.onerror=event=>{if(recognition._payproofCancelled)return;recognition._payproofError=true;state.voice.micState='off';renderVoiceControls(speechRecognitionErrorMessage(event.error))};
  recognition.onend=async()=>{
    if(state.voice.recognition===recognition)state.voice.recognition=null;
    if(recognition._payproofCancelled||recognition._payproofError||recognition._payproofSubmitted)return;
    const transcript=String(recognition._payproofTranscript||'').trim();
    if(!transcript){state.voice.micState='off';renderVoiceControls('No speech was captured. Nothing was submitted.');return}
    recognition._payproofSubmitted=true;
    $('#chatInput').value=transcript;state.voice.micState='processing';renderVoiceControls('Processing the captured transcript.');
    await ask(transcript,{fromVoice:true});
  };
  state.voice.recognition=recognition;state.voice.micState='listening';renderVoiceControls('Requesting microphone access from your browser...');
  try{recognition.start()}catch(error){state.voice.recognition=null;state.voice.micState='off';renderVoiceControls(`Microphone input could not start: ${error.message}`)}
}
function toggleSpokenReplies(){
  if(!state.voice.replyVoice){renderVoiceControls('No eligible Natural, Neural, or Online browser voice is available. Replies remain text-only.');return}
  state.voice.spokenReplies=!state.voice.spokenReplies;
  if(!state.voice.spokenReplies)window.speechSynthesis.cancel();
  renderVoiceControls(state.voice.spokenReplies?`Spoken replies enabled with browser voice ${state.voice.replyVoice.name}.`:'Spoken replies are off. Replies remain text-only.');
}
function spokenReplyText(text,maxLength=680){
  let spoken=String(text||'').replace(/\[(?:[A-Z][A-Z0-9_]*-)[A-Z0-9_.:-]+\]/gi,' ').replace(/\s+([,.;:!?])/g,'$1').replace(/\s+/g,' ').trim();
  if(spoken.length<=maxLength)return spoken;
  const clipped=spoken.slice(0,maxLength+1),sentences=[...clipped.matchAll(/[.!?](?=\s|$)/g)],lastSentence=sentences.at(-1)?.index;
  if(Number.isInteger(lastSentence)&&lastSentence>=Math.floor(maxLength*.45))return clipped.slice(0,lastSentence+1).trim();
  const lastSpace=clipped.lastIndexOf(' ',maxLength-1);
  return `${clipped.slice(0,lastSpace>Math.floor(maxLength*.45)?lastSpace:maxLength-1).trim()}…`;
}
function speakAssistantReply(text){
  const voice=state.voice.replyVoice;
  if(!state.voice.spokenReplies||!isEligibleBrowserReplyVoice(voice)||!window.speechSynthesis||typeof window.SpeechSynthesisUtterance!=='function')return;
  const spoken=spokenReplyText(text);if(!spoken)return;
  window.speechSynthesis.cancel();
  const utterance=new window.SpeechSynthesisUtterance(spoken);utterance.voice=voice;utterance.lang=voice.lang||navigator.language||'en-US';utterance.rate=.98;
  utterance.onstart=()=>renderVoiceControls(`Speaking with browser voice ${voice.name}.`);
  utterance.onend=()=>renderVoiceControls(null);
  utterance.onerror=()=>renderVoiceControls('The browser could not play this reply. Spoken replies remain enabled for the next answer.');
  window.speechSynthesis.speak(utterance);
}
function setupVoiceControls(){
  state.voice.inputAvailable=Boolean(window.SpeechRecognition||window.webkitSpeechRecognition);
  $('#micToggle').onclick=toggleMicInput;$('#spokenRepliesToggle').onclick=toggleSpokenReplies;
  if(window.speechSynthesis&&!state.voice.voicesBound){state.voice.voicesBound=true;window.speechSynthesis.addEventListener?.('voiceschanged',refreshEligibleReplyVoice)}
  refreshEligibleReplyVoice();renderVoiceControls(null);
}

function evidenceRecordRef(sourceId){const value=String(sourceId||'');const data=state.data||{};if((data.security?.evidence||[]).some(item=>item.id===value))return `security:${value}`;for(const [rows,prefix] of [[data.bank_transactions,'bank'],[data.transactions,'transaction'],[data.invoices,'invoice'],[data.receipts,'receipt'],[data.emails,'email'],[data.expenses,'expense'],[data.documents,'document'],[data.web_evidence,'web']]){const row=(rows||[]).find(item=>item.id===value||item.source_id===value);if(row)return `${prefix}:${row.id}`}return null}
function addMessage(role,text,evidence=[]){const el=document.createElement('div');el.className=`message ${role}-message`;const unique=[...new Set(evidence||[])],sources=unique.length?`<details class="message-sources"><summary>Sources (${unique.length})</summary><div>${unique.slice(0,12).map(source=>{const ref=evidenceRecordRef(source);return ref?`<button data-chat-record="${escapeHtml(ref)}">${escapeHtml(source)}</button>`:`<span>${escapeHtml(source)}</span>`}).join('')}${unique.length>12?`<span>+${unique.length-12} more</span>`:''}</div></details>`:'';el.innerHTML=`<span class="message-label">${role==='user'?'YOU':'PAYPROOF'}</span><p>${escapeHtml(text)}</p>${sources}`;$('#chatLog').append(el);$$('[data-chat-record]',el).forEach(button=>button.onclick=()=>openRecord(button.dataset.chatRecord));$('#chatLog').scrollTop=$('#chatLog').scrollHeight}
function questionUsesSelectedContext(question){const text=String(question||'').toLowerCase().trim();return /^(why|how so|tell me more|what about (it|this|that))\b/.test(text)||anyPhrase(text,['this item','this record','this control','selected item','selected record','selected control','show its evidence','show the evidence','what was bought','what items','purchase details','open it'])}
function anyPhrase(text,phrases){return phrases.some(phrase=>text.includes(phrase))}
function merchantForFocus(focus){const [type,...parts]=String(focus||'').split(':'),id=parts.join(':');if(type==='vendor')return (state.data.vendors||[]).find(item=>String(item.id)===id)?.name||id;if(type==='transaction')return (state.data.transactions||[]).find(item=>String(item.id)===id)?.merchant_raw||id;if(type==='bank')return (state.data.bank_transactions||[]).find(item=>String(item.id)===id)?.description||id;return ''}
function navigateFromAssistant(question,result){
  const text=String(question||'').toLowerCase(),focus=String(result.focus_ids?.[0]||''),calculation=result.calculation||{};
  const namedEmployee=(state.data.employees||[]).find(item=>text.includes(String(item.name||'').toLowerCase()));
  if(namedEmployee||focus.startsWith('employee:')||Array.isArray(calculation.employees)){const id=namedEmployee?.id||focus.split(':').slice(1).join(':');state.view='people';if(id)state.assistantSpotlight={type:'employee',id};syncNav();renderVisual();return}
  if(Number.isFinite(calculation.review_count)||anyPhrase(text,['needs review','need review','needs my attention','possible fraud','why was','why are these'])){state.view='records';state.recordFilter=null;syncNav();renderVisual();return}
  if(calculation.revenue_by_currency||anyPhrase(text,['revenue','money in','money out','cash flow','spending trend'])){state.view='change';syncNav();renderVisual();return}
  if(focus.startsWith('transaction:')||focus.startsWith('bank:')||focus.startsWith('vendor:')||anyPhrase(text,['transaction','amazon','purchase'])){state.recordFilter=text.includes('amazon')?'amazon':merchantForFocus(focus);state.view='records';syncNav();renderVisual();return}
  if(focus.startsWith('control:')||anyPhrase(text,['mfa','backup','security','questionnaire','production access'])){state.view='records';syncNav();renderVisual();return}
  if(anyPhrase(text,['bank account','email connection','intake folder','connect'])){state.view='geo';syncNav();renderVisual()}
}
async function ask(question,options={}){
  if(state.chatPending){
    if(options.fromVoice&&state.voice.micState==='processing'){state.voice.micState='off';renderVoiceControls('Wait for the current answer, then press the microphone again.')}
    return;
  }
  const q=String(question||$('#chatInput').value||'').trim();
  if(!q)return;
  if(!options.fromVoice&&state.voice.micState==='listening')cancelVoiceCapture('Microphone input canceled because a typed question was submitted.');
  const workspace=state.workspace,generation=state.workspaceGeneration,selectedId=questionUsesSelectedContext(q)?state.selectedId:null;
  state.chatPending=true;$('#chatInput').value='';addMessage('user',q);$('#chatSend').disabled=true;
  let reply='';
  try{
    const payload={question:q,workspace,session_id:state.sessionId};if(selectedId)payload.selected_id=selectedId;
    const result=await api('/api/chat',jsonRequest('POST',payload));
    if(state.workspace!==workspace||generation!==state.workspaceGeneration){toast(`An answer finished for ${workspace}, but it was not shown because the active company changed.`);return}
    reply=String(result.answer||'');
    addMessage('assistant',reply,result.evidence_ids);
    state.lastContext=result.context;
    $('#traceStatus').textContent=`${result.model.state==='live_model'?'AI':'Fallback'} · Trace: ${result.trace.state}`;
    if(result.focus_ids?.length)state.selectedId=result.focus_ids[0];navigateFromAssistant(q,result);
  }catch(error){
    if(state.workspace===workspace&&generation===state.workspaceGeneration)addMessage('assistant',`I could not complete that request: ${error.message}`);
    else toast(`A request for ${workspace} ended after the active company changed.`);
  }finally{
    state.chatPending=false;$('#chatSend').disabled=false;
    if(options.fromVoice&&state.voice.micState==='processing'){state.voice.micState='off';renderVoiceControls(null)}
    $('#chatInput').focus();
  }
  if(reply&&state.workspace===workspace&&generation===state.workspaceGeneration)speakAssistantReply(reply);
}
async function takeAction(action){const reason=action==='dismissed'?prompt('Reason for dismissal:')||'':'';try{const r=await api('/api/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace:state.workspace,finding_id:state.selectedFinding,action,reason})});toast(`Simulated action recorded: ${r.status}`);await loadData()}catch(e){toast(e.message)}}
function openDrawer(label,title,html){$('#drawerLabel').textContent=label;$('#drawerTitle').textContent=title;$('#drawerContent').innerHTML=html;$('#drawer').classList.remove('hidden');$('#drawerBackdrop').classList.remove('hidden')}
function closeDrawer(){$('#drawer').classList.add('hidden');$('#drawerBackdrop').classList.add('hidden')}
function toast(message){const t=document.createElement('div');t.className='toast';t.textContent=message;document.body.append(t);setTimeout(()=>t.remove(),2600)}
function escapeHtml(value){return String(value??'').replace(/[&<>'"]/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]))}

function startDemo(){const steps=[()=>{state.view='overview';syncNav();renderVisual();toast('Step 1 · See money, budgets, sources, and risk together')},()=>ask('What needs my attention?'),()=>ask('Who is over budget?'),()=>ask('What was the last transaction?')];steps[state.demoStep%steps.length]();state.demoStep++;$('#tourButton').textContent=state.demoStep%steps.length?`Next ${state.demoStep+1}/${steps.length}`:'▶ Demo'}
function syncNav(){$$('#viewNav button').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view))}
function openCompanyMenu(){const panel=$('#companyQuickPanel'),toggle=$('#companyMenuToggle');panel?.classList.remove('hidden');toggle?.setAttribute('aria-expanded','true')}
function closeCompanyMenu(){const panel=$('#companyQuickPanel'),toggle=$('#companyMenuToggle');panel?.classList.add('hidden');toggle?.setAttribute('aria-expanded','false')}
function setupCompanyMenu(){
  $('#companyMenuToggle').onclick=()=>$('#companyQuickPanel').classList.contains('hidden')?openCompanyMenu():closeCompanyMenu();$('#companyMenuClose').onclick=closeCompanyMenu;
  $('#quickManageCompany').onclick=()=>{closeCompanyMenu();sourcesDrawer().catch(error=>toast(error.message))};$('#quickAddCompany').onclick=async()=>{closeCompanyMenu();try{await sourcesDrawer();const form=$('#createCompanyForm');const details=form?.closest('details');if(details)details.open=true;form?.querySelector('input')?.focus();form?.scrollIntoView({block:'nearest'})}catch(error){toast(error.message)}};
  document.addEventListener('pointerdown',event=>{if(!event.target.closest('.company-menu'))closeCompanyMenu()});document.addEventListener('keydown',event=>{if(event.key==='Escape')closeCompanyMenu()});
}
function applyTheme(theme){const selected=theme==='light'?'light':'dark';document.documentElement.dataset.theme=selected;const button=$('#themeToggle');if(button){button.textContent=selected==='light'?'☾':'☀';button.title=selected==='light'?'Use dark mode':'Use light mode';button.setAttribute('aria-label',button.title)}try{localStorage.setItem('payproof-theme',selected)}catch{}}
function setupTheme(){let saved='dark';try{saved=localStorage.getItem('payproof-theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark')}catch{}applyTheme(saved);$('#themeToggle').onclick=()=>applyTheme(document.documentElement.dataset.theme==='light'?'dark':'light')}

$('#workspaceSelect').onchange=event=>switchWorkspace(event.target.value,event.target.selectedOptions[0]?.textContent||event.target.value);
$$('#viewNav button').forEach(b=>b.onclick=()=>{state.view=b.dataset.view;if(state.view!=='records')state.recordFilter=null;syncNav();renderVisual()});
$('#refreshButton').onclick=()=>loadData();$('#resetButton').onclick=async()=>{if(confirm('Reset only the built-in synthetic example?')){await api('/api/reset',{method:'POST'});state.selectedFinding='F-ROUTE-001';state.selectedId='invoice:INV-1007';await loadData();toast('Synthetic example reset')}};
$('#importOpen').onclick=importDrawer;$('#sourcesOpen').onclick=()=>sourcesDrawer().catch(e=>toast(e.message));['#bankHeaderStatus','#emailHeaderStatus','#intakeHeaderStatus'].forEach(selector=>$(selector).onclick=()=>sourcesDrawer().catch(error=>toast(error.message)));$('#tourButton').onclick=startDemo;$('#evidenceButton').onclick=evidenceDrawer;$('#contextOpen').onclick=contextDrawer;$('#chatContextButton').onclick=contextDrawer;
$('#drawerClose').onclick=closeDrawer;$('#drawerBackdrop').onclick=closeDrawer;$('#chatSend').onclick=()=>ask();$('#chatInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask()}};
$$('#suggestions button').forEach(b=>b.onclick=()=>ask(b.textContent));$$('[data-action]').forEach(b=>b.onclick=()=>takeAction(b.dataset.action));
$('#zoomIn').onclick=()=>{state.zoom=Math.min(2,state.zoom+.15);drawAtlas()};$('#zoomOut').onclick=()=>{state.zoom=Math.max(.65,state.zoom-.15);drawAtlas()};$('#zoomReset').onclick=()=>{state.zoom=1;state.pan={x:0,y:0};drawAtlas()};
$('#atlasCanvas').onclick=e=>{const box=e.currentTarget.getBoundingClientRect(),x=(e.clientX-box.left-state.pan.x)/state.zoom,y=(e.clientY-box.top-state.pan.y)/state.zoom;let hit=null,best=999;state.nodes.forEach(n=>{const d=Math.hypot(n.x-x,n.y-y);if(d<Math.max(18,n.size+8)&&d<best){hit=n;best=d}});if(hit){state.selectedId=hit.id;$('#selectionCard').style.display='block';$('#selectionCard').innerHTML=`<b>${escapeHtml(hit.label)}</b><small>${escapeHtml(String(hit.type||'record').replaceAll('_',' '))} · ${escapeHtml(hit.source||'saved evidence')} · choose the node for details</small>`;if(hit.type==='web')openOutsideResearch(hit.id);else if(hit.type==='employee')openPersonDetails(String(hit.id).replace(/^employee:/,''));else if(['vendor','invoice','transaction','receipt','email','expense','bank_transaction'].includes(hit.type)||String(hit.id).startsWith('security:'))openRecord(hit.id);drawAtlas()}};
let rotateStart=null;$('#atlasCanvas').onpointerdown=e=>{rotateStart={x:e.clientX,yaw:state.yaw};e.currentTarget.setPointerCapture(e.pointerId)};$('#atlasCanvas').onpointermove=e=>{if(!rotateStart)return;state.yaw=rotateStart.yaw+(e.clientX-rotateStart.x)/240;drawAtlas()};$('#atlasCanvas').onpointerup=()=>{rotateStart=null};
window.addEventListener('resize',()=>state.view==='atlas'&&drawAtlas());
setupVoiceControls();
setupAutoRefresh();
setupConnectivity();
setupCompanyMenu();
setupTheme();
addMessage('assistant','Hi. Ask me what came in or went out, what needs attention, who is over budget, or why a record was flagged. I will show the matching screen and the sources behind my answer.');
loadData().catch(e=>addMessage('assistant',`The application could not load: ${e.message}`));
