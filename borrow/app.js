(function(){
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const C={red:"#e30613",blue:"#0b5fd6",green:"#00875a",amber:"#946000",ink:"#0f1114",mute:"#5c6570",line:"#e4e7eb",line2:"#cdd2d8"};
const BC=["#00875a","#946000","#c2410c","#e30613"];           // 低／中／偏高／高
function fmt(v,d,sign){
  if(v===null||v===undefined||isNaN(v)) return "—";
  const s=Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
  return (v<0?"−":sign&&v>0?"+":"")+s;
}
const md=d=>{const p=d.split("-");return `${p[0]}/${+p[1]}/${+p[2]}`};
const wd=d=>"日一二三四五六"[new Date(d+"T00:00:00Z").getUTCDay()];
const light=(lv,name,v)=>`<li><i class="${lv}"></i><span>${name}</span><b>${v}</b></li>`;
function debounce(fn,t){let h;return()=>{clearTimeout(h);h=setTimeout(fn,t)}}
const bandOf=(v,B)=>v===null||v===undefined?null:B.findIndex(b=>v>=b[0]&&v<b[1]);

const SPK={};
function spark(id,S,lines,color,d,cap){
  if(!S||S.length<2) return "";
  SPK[id]={S,d};
  const W=400,H=110,P=6,vals=S.map(x=>x[1]);
  let lo=Math.min(...vals),hi=Math.max(...vals);
  lines.forEach(t=>{lo=Math.min(lo,t[0]);hi=Math.max(hi,t[0])});
  const pad=(hi-lo||1)*.08;lo-=pad;hi+=pad;
  const X=k=>P+(W-2*P)*k/(S.length-1),Y=v=>P+(H-2*P)*(1-(v-lo)/(hi-lo));
  const pts=S.map((x,k)=>X(k).toFixed(1)+","+Y(x[1]).toFixed(1)).join(" ");
  const L=S[S.length-1];
  const ln=lines.map(t=>`<line x1="0" x2="${W}" y1="${Y(t[0]).toFixed(1)}" y2="${Y(t[0]).toFixed(1)}" stroke="${t[2]||C.mute}" stroke-opacity=".8" stroke-dasharray="4 5" stroke-width="1.2" vector-effect="non-scaling-stroke"/>`).join("");
  const lb=lines.map(t=>`<span class="tl" style="top:${(Y(t[0])/H*100).toFixed(1)}%;color:${t[2]||C.mute}">${esc(t[1])}</span>`).join("");
  return `<div class="spark" data-id="${id}"><div class="plot">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px"><defs><linearGradient id="g${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${C.ink}" stop-opacity=".07"/><stop offset="1" stop-color="${C.ink}" stop-opacity="0"/></linearGradient></defs>${ln}
    <polygon points="${X(0).toFixed(1)},${H} ${pts} ${X(S.length-1).toFixed(1)},${H}" fill="url(#g${id})"/>
    <polyline points="${pts}" fill="none" stroke="${C.ink}" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    <line class="cur" x1="0" x2="0" y1="0" y2="${H}" stroke="${C.red}" stroke-width="1" opacity="0" vector-effect="non-scaling-stroke"/>
    <circle cx="${X(S.length-1).toFixed(1)}" cy="${Y(L[1]).toFixed(1)}" r="5" fill="${color}" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>${lb}</div>
    <div class="cap"><span class="tipL">${esc(cap)}</span><span>最新 <b>${fmt(L[1],d)}</b></span></div></div>`;
}
function bindSparks(){
  document.querySelectorAll(".spark").forEach(c=>{
    const {S,d}=SPK[c.dataset.id],svg=c.querySelector("svg"),cur=c.querySelector(".cur"),tl=c.querySelector(".tipL"),def=tl.textContent;
    svg.addEventListener("pointermove",e=>{
      const b=svg.getBoundingClientRect(),k=Math.max(0,Math.min(S.length-1,Math.round((e.clientX-b.left)/b.width*(S.length-1))));
      const x=6+388*k/(S.length-1);cur.setAttribute("x1",x);cur.setAttribute("x2",x);cur.setAttribute("opacity","1");
      tl.textContent=md(S[k][0])+"　"+fmt(S[k][1],d);
    });
    svg.addEventListener("pointerleave",()=>{cur.setAttribute("opacity","0");tl.textContent=def});
  });
}

/* ═════ 主資料 ═════ */
function render(D,G){
  const s=D.sig,B=D.bins,cal=D.cal,bi=s.band,bc=bi===null?C.mute:BC[bi],P=v=>Math.max(0,Math.min(100,v));
  const t=new Date(D.updated.replace(" UTC","Z").replace(" ","T"));
  const st=$("#stamp");
  st.textContent=(isNaN(t)?D.updated:"更新 "+t.toLocaleString("zh-TW",{timeZone:"Asia/Taipei",month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}))+"　收盤 "+md(D.asof);
  if(D.stale.length) st.classList.add("bad");
  document.documentElement.style.setProperty("--pc",bc);

  /* 指數卡 */
  const cb=bi===null?null:cal.bins[bi];
  const comps=[["高收益對公債",s.A,"HYG ÷ IEF 落後幅度"],["高收益對投資級",s.C,"HYG ÷ LQD 落後幅度"]];
  $("#score").innerHTML=`<p class="eyebrow"><span class="k">index</span><span class="v">= 借錢成本指數</span></p>
    <div class="bignum"><b>${fmt(s.score,0)}</b><span>/ 100</span><em>${bi===null?"":esc(B[bi][2])}</em>
      <small>前一日 ${fmt(s.scorePrev,0)}（${fmt(s.score-s.scorePrev,1,1)}）</small></div>
    <div class="scale">
      <div class="track">${B.map((b,k)=>`<span style="width:${Math.min(b[1],100)-b[0]}%;background:${BC[k]}59"></span>`).join("")}</div>
      <div class="ptr" style="left:${P(s.score)}%;top:-6px"></div>
      <div class="ticks">${[[0,"0"],[40,"40"],[60,"60"],[75,"75"]].map(x=>`<span style="left:${x[0]}%">${x[1]}</span>`).join("")}</div>
    </div>
    <ul class="comps">${comps.map(c=>`<li><span>${c[0]}<small style="display:block;font:500 13px var(--mono2);color:var(--mute)">${c[2]}</small></span><i><u style="width:${P(c[1])}%"></u></i><b>${fmt(c[1],0)}</b></li>`).join("")}</ul>
    ${cb?`<p class="hint">歷史上指數在「${esc(cb.name)}」區時，之後 21 日 SPX 回撤超過 10% 的比例為 <b>${fmt(cb.d10,1)}%</b>，超過 5% 為 <b>${fmt(cb.d5,1)}%</b>（全期平均 ${fmt(cal.base.d10,1)}%／${fmt(cal.base.d5,1)}%）。</p>`:""}`;

  /* 三層儀表：管道 → 價格 → 信用（節目的判斷順序） */
  const sp=G&&G.indicators?G.indicators.find(i=>i.id==="spread"):null;
  const pipe=sp?{lv:sp.level,v:`SOFR − IORB ${fmt(sp.value,1,1)} bp`,w:{red:"錢不夠",yellow:"偏緊",green:"錢夠"}[sp.level]||"—",n:`錢荒分頁：${esc(G.regime||"")}`}:{lv:"gray",v:"錢荒資料未載入",w:"—",n:""};
  const rr=s.rate||"—",rlv=rr.startsWith("短端")?"red":rr.startsWith("長端")?"yellow":"green";
  const price={lv:rlv,v:`2 年 ${fmt(s.d2,0,1)}bp　10 年 ${fmt(s.d10,0,1)}bp`,w:rr.split("：")[0],n:`21 日變化；隱含通脹 ${fmt(s.dbei,0,1)}bp`};
  const clv=bi>=3?"red":bi>=2?"yellow":"green";
  const credit={lv:clv,v:`借錢成本指數 ${fmt(s.score,0)}`,w:{red:"貴在低評等",yellow:"低評等轉貴",green:"信用平穩"}[clv],n:`高收益落後公債第 ${fmt(s.A,0)}、落後投資級第 ${fmt(s.C,0)} 百分位`};
  const L3=[["01","管道層","錢夠不夠",pipe],["02","價格層","是不是加息預期",price],["03","信用層","貴在誰身上",credit]];
  const lvC={red:C.red,yellow:C.amber,green:C.green,gray:C.mute};
  $("#layers").innerHTML=`<p class="eyebrow"><span class="k">layers</span><span class="v">= 先排除管道，再看價格，最後定位信用</span></p>
    <div class="layers">${L3.map(l=>`<div class="ly"><i>${l[0]}</i><div><b>${l[1]}<small>${l[2]}</small></b><span class="w" style="color:${lvC[l[3].lv]}">${esc(l[3].w)}</span>
      <span class="lv">${l[3].v}</span><span class="ln">${l[3].n}</span></div></div>`).join("")}</div>`;

  /* 校準表 */
  const per=cal.periods[0];
  $("#calr").textContent=`= ${md(per.from)} → ${md(D.asof)}`;
  $("#cal").innerHTML=cal.bins.map((b,k)=>`<tr class="${k===bi?"curbin":""}"><td><span class="bn"><i style="background:${BC[k]}"></i>${esc(b.name)}　<small style="font:600 14px var(--sans);color:var(--mute)">${b.lo}–${Math.min(b.hi,100)}</small></span></td><td>${fmt(b.share,1)}%</td><td>${fmt(b.d5,1)}%</td><td>${fmt(b.d10,1)}%</td></tr>`).join("")
    +`<tr><td><span class="bn" style="color:var(--mute)">全期平均</span></td><td>100%</td><td>${fmt(cal.base.d5,1)}%</td><td>${fmt(cal.base.d10,1)}%</td></tr>`;
  const a=per.auc;
  $("#calnote").innerHTML=`區分「21 日內回撤超過 10%」的能力（AUC，0.5 為隨機）：指數 <b>${fmt(a.score[1],2)}</b>；事先宣告的三成分版本 <b>${fmt(a.score3[1],2)}</b>，其中 2 年期上升為反向 <b>${fmt(a.Bp[1],2)}</b>，已移出指數＊。回撤超過 5% 的區分力較弱（${fmt(a.score[0],2)}）。詳見<a href="機制說明.html#idx">機制說明</a>。`;

  /* 成分卡 */
  const cards=[
    ["01","高收益對公債",s.A,s.aS,`HYG ÷ IEF 21 日 <b>${fmt(-s.Araw,2,1)}%</b>`,"高收益債總報酬落後同期公債越多，代表信用利差在擴大、低評等借錢變貴。","Yahoo Finance HYG、IEF 還原收盤"],
    ["02","高收益對投資級",s.C,s.cS,`HYG ÷ LQD 21 日 <b>${fmt(-s.Craw,2,1)}%</b>`,"低評等落後高評等越多，代表壓力集中在最需要借錢的那一層。","Yahoo Finance HYG、LQD 還原收盤"]];
  let html=cards.map(c=>{const b=bandOf(c[2],B);return `<article class="card sig">
    <h3><i>${c[0]}</i>${c[1]}</h3>
    <div class="main"><span>5 年百分位</span><b style="color:${BC[b]}">${fmt(c[2],0)}</b></div>
    <p class="hint" style="margin-top:8px">${c[4]}</p>
    ${spark("s"+c[0],c[3],[[75,"75",C.red]],BC[b],0,"近 130 日百分位")}
    <p class="hint" style="font-size:15px;color:var(--mute)">${esc(c[5])}</p>
    <p class="srcline">來源：${esc(c[6])}</p></article>`}).join("");
  html+=`<article class="card sig">
    <h3><i>03</i>利率重估＊</h3>
    <div class="main"><span>21 日判讀</span><b style="font-size:30px;color:${lvC[rlv]}">${esc(rr.split("：")[1]||rr)}</b></div>
    <p class="hint" style="margin-top:8px">2 年 <b>${fmt(s.y2,2)}%</b>（${fmt(s.d2,0,1)}bp）　10 年 <b>${fmt(s.y10,2)}%</b>（${fmt(s.d10,0,1)}bp）　隱含通脹 <b>${fmt(s.bei,2)}%</b>（${fmt(s.dbei,0,1)}bp）</p>
    ${spark("y2",s.y2S,[],C.ink,2,"近 130 日 2 年期殖利率")}
    <p class="hint" style="font-size:15px;color:var(--mute)">短端升得比長端多、隱含通脹下降，代表市場在重估加息。回測方向與大跌相反，不納入指數。</p>
    <p class="srcline">來源：美國財政部每日殖利率</p></article>`;
  if(D.ice){
    const cc=D.ice.ccc,hy=D.ice.hy,ccl=cc[cc.length-1][1];
    html+=`<article class="card sig"><h3><i>04</i>ICE 信用利差</h3>
      <div class="main"><span>CCC 及以下 OAS</span><b style="color:${ccl<D.params.CCC_STABLE?C.green:C.red}">${fmt(ccl,2)}<small>%</small></b></div>
      <p class="hint" style="margin-top:8px">高收益 OAS <b>${fmt(hy[hy.length-1][1],2)}%</b>　節目企穩線：CCC 回到 <b>${D.params.CCC_STABLE}%</b> 以下</p>
      ${spark("ccc",cc,[[D.params.CCC_STABLE,"企穩線",C.green]],ccl<D.params.CCC_STABLE?C.green:C.red,2,"近 130 日 CCC OAS")}
      <p class="hint" style="font-size:15px;color:var(--mute)">FRED 只提供近 3 年，不足以算 5 年百分位，因此不納入指數。</p>
      <p class="srcline">來源：ICE BofA，經 FRED</p></article>`;
  }else{
    html+=`<article class="card sig"><h3><i>04</i>ICE 信用利差</h3>
      <div class="main"><span>CCC 及以下 OAS</span><b style="font-size:30px;color:${C.mute}">待金鑰</b></div>
      <p class="hint" style="margin-top:8px">節目企穩線：CCC 回到 <b>${D.params.CCC_STABLE}%</b> 以下。設定 FRED API 金鑰後顯示。</p>
      <p class="srcline">來源：ICE BofA，經 FRED</p></article>`;
  }
  $("#sigs").innerHTML=html;$("#sigs").classList.add("four");
  bindSparks();

  /* 結算日曆 */
  const big=D.params.SETTLE_BIG;
  $("#stl").innerHTML=D.settle.map(x=>`<tr class="${x.coupon>=big?"nowrow":""}"><td>${md(x.d)}（${wd(x.d)}）<small class="itm">${esc(x.items.filter(i=>!i.includes("短券")).join("、")||"短券")}</small></td><td${x.coupon>=big?' class="dn"':""}>${x.coupon?fmt(x.coupon,0)+" 億":"—"}</td><td>${x.bill?fmt(x.bill,0)+" 億":"—"}</td><td class="it">${esc(x.items.filter(i=>!i.includes("短券")).join("、")||"短券")}</td></tr>`).join("")||`<tr><td colspan="4">已公告範圍內沒有結算</td></tr>`;
  $("#stlnote").innerHTML=`金額為公告標售量（毛額，未扣到期贖回）。財政部約提前一週公告，因此只列已公告部分。節目另列 12/15（企業季度繳稅日）與 12/31（年末報表）為觀察日，屆時看錢荒分頁的 SOFR − IORB 與常備回購用量。`;

  /* 警示與觀察 */
  $("#alcount").textContent=`= ${D.alerts.filter(a=>a.on).length} / ${D.alerts.length} 觸發`;
  $("#alerts").innerHTML=[...D.alerts].sort((a,b)=>b.on-a.on).map(a=>`<div class="al"><div><span class="tag ${a.on?a.kind:""}">${a.on?"觸發中":"未觸發"}</span></div>
    <div class="n">${esc(a.name)}</div><div class="r">${esc(a.rule)}</div><div class="c">${esc(a.now)}</div></div>`).join("");
  const dv=D.diverge,rc=dv.recent.filter(x=>x.lag);
  $("#refs").innerHTML=[
    light(rc.length?"yellow":"gray",`股漲債不跟<small>QQQ 單日 ≥ +${D.params.DIVERGE_UP}%、高收益債卻落後公債；回測不成立：之後跌超過 5% 的比例 ${fmt(dv.lag.d5,1)}%（${dv.lag.n} 次），同漲時 ${fmt(dv.join.d5,1)}%</small>`,rc.length?rc.map(x=>md(x.d)).join("、"):"近 5 日未出現"),
    light("gray",`單一公司 CDS 與債券殖利率<small>節目企穩線：CoreWeave 五年 CDS 回到 900–1,000bp 以下、2031 年債殖利率 12% 以下；沒有免費可靠來源</small>`,"未納入"),
  ].join("");
  $("#srcs").innerHTML=D.sources.map(x=>`<div><b>${esc(x.name)}</b><span class="u">${esc(x.src)}</span>
    <span class="m"><span class="tag ${D.stale.includes(x.name)?"bad":"good"}">${D.stale.includes(x.name)?"停更":"正常"}</span>${esc(md(x.asof))}</span></div>`).join("");
  if(D.stale.length) $("#errs").innerHTML=`<div class="stale">資料停更：${esc(D.stale.join("、"))}，指數可能失準。</div>`;

  chart(D);
}

/* ═════ 指數歷史圖 ═════ */
function chart(D){
  const H=window.BORROW_HIST,LW=window.LightweightCharts,el=$("#tv"),B=D.bins;
  $("#legend").innerHTML=`<span>上方線＝S&amp;P 500</span><span>下方柱＝借錢成本指數</span>${B.map((b,k)=>`<span style="white-space:nowrap"><i style="background:${BC[k]}"></i>${b[2]}</span>`).join("")}`;
  if(!LW||!H){el.innerHTML='<p style="color:var(--mute);padding:20px">圖表資料載入失敗</p>';return}
  const ch=LW.createChart(el,{autoSize:true,
    layout:{background:{type:"solid",color:"transparent"},textColor:C.mute,fontFamily:"Archivo, Noto Sans TC, sans-serif",fontSize:13},
    grid:{vertLines:{color:"rgba(15,17,20,.05)"},horzLines:{color:"rgba(15,17,20,.05)"}},
    rightPriceScale:{borderColor:"rgba(15,17,20,.2)",scaleMargins:{top:.06,bottom:.3}},
    timeScale:{borderColor:"rgba(15,17,20,.2)",rightOffset:6,minBarSpacing:.3},
    crosshair:{mode:0,vertLine:{color:"rgba(15,17,20,.45)",style:2,labelBackgroundColor:"#0f1114"},horzLine:{color:"rgba(15,17,20,.3)",style:2,labelBackgroundColor:"#0f1114"}},
    handleScale:{axisPressedMouseMove:{time:true,price:false}},
    localization:{locale:"zh-TW",dateFormat:"yyyy/MM/dd"}});
  const line=ch.addLineSeries({color:C.ink,lineWidth:2,priceLineColor:"rgba(227,6,19,.7)",priceLineStyle:2});
  const sh=ch.addHistogramSeries({priceScaleId:"s",priceLineVisible:false,lastValueVisible:false,base:0,priceFormat:{type:"custom",minMove:1,formatter:v=>Math.round(v)}});
  ch.priceScale("s").applyOptions({scaleMargins:{top:.76,bottom:0},visible:false});
  line.setData(H.spx.map(([d,v])=>({time:d,value:v})));
  sh.setData(H.score.map(([d,v])=>({time:d,value:v,color:BC[bandOf(v,B)]+"cc"})));
  const smap=new Map(H.score),pmap=new Map(H.spx),dates=H.spx.map(x=>x[0]);
  const RG=[["近 1 年",365],["近 3 年",1095],["全部",0]];let rg=el.clientWidth<560?0:1;
  $("#ranges").innerHTML=RG.map((r,k)=>`<button data-k="${k}" aria-pressed="${k===rg}">${r[0]}</button>`).join("");
  function setRange(){
    const n=RG[rg][1];if(!n){ch.timeScale().fitContent();return}
    const end=dates[dates.length-1],t=new Date(end+"T00:00:00Z");t.setUTCDate(t.getUTCDate()-n);
    ch.timeScale().setVisibleRange({from:t.toISOString().slice(0,10),to:end});
  }
  function show(d){const v=smap.get(d),b=bandOf(v,B);
    $("#ohlc").innerHTML=`<b>S&amp;P 500</b><span>${md(d)}</span><span>收 <b>${fmt(pmap.get(d),2)}</b></span><span>指數 <b style="color:${b===null?C.mute:BC[b]}">${v===undefined?"—":fmt(v,0)}</b></span>`}
  ch.subscribeCrosshairMove(p=>show(p.time||dates[dates.length-1]));
  $("#ranges").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;rg=+b.dataset.k;
    [...$("#ranges").children].forEach((x,k)=>x.setAttribute("aria-pressed",k===rg));setRange()});
  show(dates[dates.length-1]);setRange();
}

try{render(window.BORROW,window.DASH)}catch(e){console.error(e);document.querySelector("#errs").innerHTML='<div class="stale">頁面渲染失敗：'+esc(e.message)+'</div>'}
})();
