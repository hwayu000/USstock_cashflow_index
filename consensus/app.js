(function(){
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const C={red:"#e30613",blue:"#0b5fd6",green:"#00875a",ink:"#0f1114",mute:"#5c6570",line:"#e4e7eb",line2:"#cdd2d8"};
const BC=["#00875a","#946000","#c2410c","#e30613"];           // 指數四區顏色：低／中／偏高／高
const PH=[null,{n:"翻轉前",c:C.green},{n:"翻轉過程",c:C.red},{n:"恐慌回落",c:C.blue}];
function fmt(v,d,sign){
  if(v===null||v===undefined||isNaN(v)) return "—";
  const s=Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
  return (v<0?"−":sign&&v>0?"+":"")+s;
}
const pctv=p=>p===null||p===undefined?"—":fmt(p*100,1)+"%";
const md=d=>{const p=d.split("-");return `${p[0]}/${+p[1]}/${+p[2]}`};
const light=(lv,name,v)=>`<li><i class="${lv}"></i>${name}<b>${v}</b></li>`;
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
function attachHover(wrap,svg,fn){
  const tip=document.createElement("div");tip.className="tip";tip.hidden=true;wrap.appendChild(tip);
  const cur=svg.querySelector(".cur");
  svg.addEventListener("pointermove",e=>{
    const b=svg.getBoundingClientRect(),vb=svg.viewBox.baseVal,x=(e.clientX-b.left)/b.width*vb.width;
    const r=fn(x);if(!r){tip.hidden=true;return}
    tip.hidden=false;tip.innerHTML=r.html;
    tip.style.left=Math.max(80,Math.min(b.width-80,r.x/vb.width*b.width))+"px";
    tip.style.top=Math.max(56,(r.y??40)/vb.height*b.height)+"px";
    if(cur){cur.setAttribute("x1",r.x);cur.setAttribute("x2",r.x);cur.setAttribute("opacity","1")}
  });
  svg.addEventListener("pointerleave",()=>{tip.hidden=true;if(cur)cur.setAttribute("opacity","0")});
}

/* ═════ 主資料 ═════ */
function render(D){
  const s=D.sig,B=D.bins,cal=D.cal||{bins:[],base:{},periods:[{auc:{score:[null,null],VIXp:[null,null]}}],from:D.asof,to:D.asof},bi=s.band,bc=bi===null?C.mute:BC[bi];
  const t=new Date(D.updated.replace(" UTC","Z").replace(" ","T"));
  const st=$("#stamp");
  st.textContent=(isNaN(t)?D.updated:"更新 "+t.toLocaleString("zh-TW",{timeZone:"Asia/Taipei",month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}))+"　收盤 "+md(D.asof);
  if(D.stale.length) st.classList.add("bad");
  document.documentElement.style.setProperty("--pc",bc);

  /* 指數卡 */
  const cb=bi===null?null:cal.bins[bi]||null,P=v=>Math.max(0,Math.min(100,v));
  const comps=[["翻轉強度",s.A,"VIX／VIX3M"],["市場同步",s.B,"COR3M"],["Gamma 偏低",s.C,"GEX 反向"]];
  $("#score").innerHTML=`<p class="eyebrow"><span class="k">index</span><span class="v">= 共識崩塌指數</span></p>
    <div class="bignum"><b>${s.score===null?"—":fmt(s.score,0)}</b><span>/ 100</span><em>${bi===null?"":esc(B[bi][2])}</em>
      <small>前一日 ${fmt(s.scorePrev,0)}（${fmt(s.score-s.scorePrev,1,1)}）${s.scoreN<3?"　· 成分不足，以其餘兩項計算":""}</small></div>
    <div class="scale">
      <div class="track">${B.map((b,k)=>`<span style="width:${Math.min(b[1],100)-b[0]}%;background:${BC[k]}59"></span>`).join("")}</div>
      ${s.score===null?"":`<div class="ptr" style="left:${P(s.score)}%;top:-6px"></div>`}
      <div class="ticks">${[[0,"0"],[40,"40"],[60,"60"],[75,"75"]].map(x=>`<span style="left:${x[0]}%">${x[1]}</span>`).join("")}</div>
    </div>
    <ul class="comps">${comps.map(c=>`<li><span>${c[0]}<small style="display:block;font:500 13px var(--mono2);color:var(--mute)">${c[2]}</small></span><i><u style="width:${c[1]===null?0:P(c[1])}%"></u></i><b>${c[1]===null?"—":fmt(c[1],0)}</b></li>`).join("")}</ul>
    ${cb?`<p class="hint">歷史上指數在「${esc(cb.name)}」區時，之後 21 日 SPX 回撤超過 10% 的比例為 <b>${fmt(cb.d10,1)}%</b>，超過 5% 為 <b>${fmt(cb.d5,1)}%</b>（全期平均 ${fmt(cal.base.d10,1)}%／${fmt(cal.base.d5,1)}%）。</p>`:""}`;

  /* 階段卡 */
  const phc=PH[D.phase].c;
  let nx;
  if(D.phase===2){const gate=s.peak*.85;
    nx={r:`進入恐慌回落：VIX 收盤 ≤ ${fmt(gate,2)}（高點 ${fmt(s.peak,2)} ×0.85）`,todo:"持有的 Put 趁翻轉過程賣給做市商的強制流，不留到反彈。",p:(s.peak-s.vix)/(s.peak-gate),l:`VIX <b>${fmt(s.vix,2)}</b>`,rr:`高點後第 <b>${D.sincePeak??0}</b> 日`};
  }else if(D.phase===3){const gate=s.evBase+.25*(s.peak-s.evBase);
    nx={r:`回落完成：VIX ≤ ${fmt(gate,2)}（超額回到高點時的 25%）`,todo:`歷史半衰中位 ${fmt(D.halfMed,0)} 日、回落完成中位 ${fmt(D.quarterMed,0)} 日；此階段重新評估，不追賣。`,p:(s.peak-s.vix)/(s.peak-gate),l:`VIX <b>${fmt(s.vix,2)}</b>`,rr:`高點後第 <b>${D.sincePeak??0}</b> 日`};
  }else{const gate=Math.max(s.vix3m,1.25*s.base);
    nx={r:`翻轉觸發：VIX 收盤 ≥ ${fmt(gate,2)}（高於 VIX3M 且 ≥ 20 日中位數 ×1.25）`,todo:`波動安靜時買前端 Put，自身判斷的機率須高於市場定價。目前 VIX 在第 ${fmt(s.vixp,0)} 百分位。`,p:s.vix/gate,l:`VIX <b>${fmt(s.vix,2)}</b>`,rr:`VIX/VIX3M <b>${fmt(s.ratio,2)}</b>`};
  }
  const p=Math.max(0,Math.min(1,nx.p)),on=Math.round(p*20);
  $("#next").style.setProperty("--phc",phc);
  $("#next").innerHTML=`<p class="eyebrow"><span class="k">phase</span><span class="v">= ${D.phase} / 3</span></p>
    <div class="ph2">${esc(PH[D.phase].n)}</div>
    <div class="minirail">${[1,2,3].map(k=>`<span class="${k===D.phase?"cur":""}">${PH[k].n}</span>`).join("")}</div>
    <p class="rule">下一步　${esc(nx.r)}</p><p class="todo"><b>節目做法：</b>${esc(nx.todo)}</p>
    <div class="cells" role="img" aria-label="進度 ${Math.round(p*100)}%">${Array.from({length:20},(_,k)=>`<i class="${k<on?"on":k===19?"goal":""}"></i>`).join("")}</div>
    <div class="pv"><span>${nx.l}</span><span>${nx.rr}</span></div>`;

  /* 校準表 */
  $("#calr").textContent=`= ${md(cal.from)} → ${md(cal.to)}${cal.stale?"（沿用上次）":""}`;
  $("#cal").innerHTML=cal.bins.map((b,k)=>`<tr class="${k===bi?"curbin":""}"><td><span class="bn"><i style="background:${BC[k]}"></i>${esc(b.name)}　<small style="font:600 14px var(--sans);color:var(--mute)">${b.lo}–${Math.min(b.hi,100)}</small></span></td><td>${fmt(b.share,1)}%</td><td>${fmt(b.d5,1)}%</td><td>${fmt(b.d10,1)}%</td></tr>`).join("")
    +`<tr><td><span class="bn" style="color:var(--mute)">全期平均</span></td><td>100%</td><td>${fmt(cal.base.d5,1)}%</td><td>${fmt(cal.base.d10,1)}%</td></tr>`;
  const all=cal.periods[0].auc;
  $("#calnote").innerHTML=`區分「21 日內回撤超過 10%」的能力（AUC，0.5 為隨機）：指數 <b>${fmt(all.score[1],2)}</b>，只看 VIX <b>${fmt(all.VIXp[1],2)}</b>。成分與限制見<a href="機制說明.html#idx">機制說明</a>。`;

  /* 成分卡 */
  const cards=[
    ["01","翻轉強度",s.A,s.aS,`VIX ÷ VIX3M <b>${fmt(s.ratio,2)}</b>`,"大於 1 代表前端恐慌高於中期，翻轉正在定價。","Cboe VIX、VIX3M"],
    ["02","市場同步",s.B,s.bS,`隱含相關 COR3M <b>${fmt(s.cor3m,1)}</b>`,`越高代表個股越同進同出；隱含獨立份數 1/ρ 約 ${s.cor3m?fmt(100/s.cor3m,1):"—"} 份。`,"Cboe COR3M"],
    ["03","Gamma 偏低",s.C,s.cS,`GEX <b>${s.gex===null?"無資料":fmt(s.gex,2,1)+" 十億美元"}</b>`,"做市商 Gamma 越低，越無法緩衝價格跳動，取反向百分位。","SqueezeMetrics GEX"]];
  $("#sigs").innerHTML=cards.map(c=>{const b=bandOf(c[2],B);return `<article class="card sig">
    <h3><i>${c[0]}</i>${c[1]}</h3>
    <div class="main"><span>5 年百分位</span><b style="color:${b===null?C.mute:BC[b]}">${c[2]===null?"—":fmt(c[2],0)}</b></div>
    <p class="hint" style="margin-top:8px">${c[4]}</p>
    ${spark("s"+c[0],c[3],[[75,"75",C.red]],b===null?C.mute:BC[b],0,"近 130 日百分位")}
    <p class="hint" style="font-size:15px;color:var(--mute)">${esc(c[5])}</p>
    <p class="srcline">來源：${esc(c[6])}</p></article>`}).join("");
  bindSparks();
  const ex=(D.opt&&D.opt.exps)||[],e30=ex.find(e=>e.tgt===30),k2=ex.filter(e=>e.k2);
  $("#refs").innerHTML=[
    light(s.skewp>=90?"yellow":"gray",`SKEW 尾部保險<small>與大跌反向，已被定價</small>`,`${fmt(s.skew,1)}（第 ${fmt(s.skewp,0)} 百分位）`),
    light("gray",`${e30?e30.dte:30} 日跌破 −10% 的定價機率<small>SPX 選擇權反推</small>`,pctv(e30&&e30.p10)),
    light(k2.length?"red":"gray",`定價分布第二峰<small>尚無歷史可驗證</small>`,k2.length?k2.map(e=>fmt(e.k2,0)).join("、"):"未出現"),
    light(D.kospi.last&&D.kospi.last.d===D.asof?"red":"gray",`KOSPI 今年盤中跌 8% 以上<small>熔斷代理</small>`,`${D.kospi.n} 日`),
  ].join("");

  $("#alcount").textContent=`= ${D.alerts.filter(a=>a.on).length} / ${D.alerts.length} 觸發`;
  $("#alerts").innerHTML=[...D.alerts].sort((a,b)=>b.on-a.on).map(a=>`<div class="al"><div><span class="tag ${a.on?a.kind:""}">${a.on?"觸發中":"未觸發"}</span></div>
    <div class="n">${esc(a.name)}</div><div class="r">${esc(a.rule)}</div><div class="c">${esc(a.now)}</div></div>`).join("");
  $("#srcs").innerHTML=D.sources.map(x=>`<div><b>${esc(x.name)}</b><span class="u">${esc(x.use)}</span>
    <span class="m"><span class="tag ${x.ok?"good":"bad"}">${x.ok?"正常":"停更"}</span>${x.asof?esc(md(x.asof.slice(0,10))):"無資料"}</span>
    <span class="m"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.provider)}</a></span>${x.note?`<span class="m">${esc(x.note)}</span>`:""}</div>`).join("");
  if(D.stale.length) $("#errs").innerHTML=`<div class="stale">資料停更：${esc(D.stale.join("、"))}，指數可能失準。</div>`;

  overlay(D);chart(D);
}

/* ═════ 回落疊圖 ═════ */
function overlay(D){
  const evs=D.events;
  function draw(){
    const W=Math.max(300,$("#ov").clientWidth||520),HH=W<460?260:300,L=40,Rr=14,T=14,B=HH-34,N=15;
    const X=t=>L+(W-L-Rr)*t/N,Y=v=>B-(B-T)*(v+.1)/1.2;
    const recent=evs.filter(e=>e.decay.length>4&&!e.live).slice(0,8),live=evs.find(e=>e.live);
    const path=a=>a.map((v,t)=>`${X(t).toFixed(1)},${Y(Math.max(-.1,Math.min(1.1,v))).toFixed(1)}`).join(" ");
    const ref=Array.from({length:N+1},(_,t)=>Math.pow(.5,t/3));
    const grid=[0,.25,.5,1].map(v=>`<line x1="${L}" x2="${W-Rr}" y1="${Y(v)}" y2="${Y(v)}" stroke="${C.line}"/><text x="${L-6}" y="${Y(v)+5}" font-size="14" text-anchor="end" fill="${C.mute}">${v*100}%</text>`).join("");
    const xa=[0,3,6,9,12,15].map(t=>`<text x="${X(t)}" y="${HH-12}" font-size="14" text-anchor="middle" fill="${C.mute}">${t}</text>`).join("");
    $("#ov").innerHTML=`<svg viewBox="0 0 ${W} ${HH}" role="img" aria-label="歷次恐慌回落曲線">${grid}${xa}
      ${recent.map(e=>`<polyline points="${path(e.decay)}" fill="none" stroke="${C.line2}" stroke-width="1.5"/>`).join("")}
      <polyline points="${path(ref)}" fill="none" stroke="${C.blue}" stroke-width="2" stroke-dasharray="5 5"/>
      <polyline points="${path(D.decayMed)}" fill="none" stroke="${C.ink}" stroke-width="2.5"/>
      ${live&&live.decay.length?`<polyline points="${path(live.decay)}" fill="none" stroke="${C.red}" stroke-width="2.5"/><circle cx="${X(live.decay.length-1)}" cy="${Y(live.decay[live.decay.length-1])}" r="5" fill="${C.red}" stroke="#fff" stroke-width="2"/>`:""}
      <line class="cur" x1="0" x2="0" y1="${T}" y2="${B}" stroke="${C.red}" opacity="0"/></svg>`;
    attachHover($("#ov"),$("#ov svg"),x=>{
      const t=Math.max(0,Math.min(D.decayMed.length-1,Math.round((x-L)/(W-L-Rr)*N)));
      return {x:X(t),y:Y(D.decayMed[t]),html:`高點後第 ${t} 日<br>中位 ${fmt(D.decayMed[t]*100,0)}%　3 日半衰 ${fmt(ref[t]*100,0)}%${live&&live.decay[t]!==undefined?`<br>本次 ${fmt(live.decay[t]*100,0)}%`:""}`};
    });
    $("#ovt").textContent=`恐慌回落：${D.evCount} 次半衰期中位 ${fmt(D.halfMed,1)} 日`;
    $("#ovlg").innerHTML=`<span class="lgln"><i style="border-color:${C.ink};border-top-width:3px"></i>全部中位數</span><span class="lgln"><i style="border-color:${C.blue};border-top-style:dashed"></i>3 日半衰</span><span class="lgln"><i style="border-color:${C.line2}"></i>最近 8 次</span>${live?`<span class="lgln"><i style="border-color:${C.red};border-top-width:3px"></i>本次</span>`:""}<span>縱軸：VIX 超額佔高點的比例；橫軸：高點後交易日</span>`;
  }
  draw();window.addEventListener("resize",debounce(draw,200));
}

/* ═════ 指數歷史圖 ═════ */
function chart(D){
  const H=window.RADAR_HIST,LW=window.LightweightCharts,el=$("#tv"),B=D.bins;
  $("#legend").innerHTML=`<span><i style="background:rgba(227,6,19,.3)"></i>翻轉過程</span><span><i style="background:rgba(11,95,214,.3)"></i>恐慌回落</span><span>下方柱＝共識崩塌指數</span>${B.map((b,k)=>`<span style="white-space:nowrap"><i style="background:${BC[k]}"></i>${b[2]}</span>`).join("")}`;
  if(!LW||!H||!H.px.SPX){el.innerHTML='<p style="color:var(--mute);padding:20px">圖表資料載入失敗</p>';return}
  const chart=LW.createChart(el,{autoSize:true,
    layout:{background:{type:"solid",color:"transparent"},textColor:C.mute,fontFamily:"Archivo, Noto Sans TC, sans-serif",fontSize:13},
    grid:{vertLines:{color:"rgba(15,17,20,.05)"},horzLines:{color:"rgba(15,17,20,.05)"}},
    rightPriceScale:{borderColor:"rgba(15,17,20,.2)",scaleMargins:{top:.06,bottom:.3}},
    timeScale:{borderColor:"rgba(15,17,20,.2)",rightOffset:6,minBarSpacing:.3},
    crosshair:{mode:0,vertLine:{color:"rgba(15,17,20,.45)",style:2,labelBackgroundColor:"#0f1114"},horzLine:{color:"rgba(15,17,20,.3)",style:2,labelBackgroundColor:"#0f1114"}},
    handleScale:{axisPressedMouseMove:{time:true,price:false}},
    localization:{locale:"zh-TW",dateFormat:"yyyy/MM/dd"}});
  const candle=chart.addCandlestickSeries({upColor:"#fff",borderUpColor:C.ink,wickUpColor:C.ink,downColor:C.ink,borderDownColor:C.ink,wickDownColor:C.ink,priceLineColor:"rgba(227,6,19,.7)",priceLineStyle:2});
  const sh=chart.addHistogramSeries({priceScaleId:"s",priceLineVisible:false,lastValueVisible:false,base:0,priceFormat:{type:"custom",minMove:1,formatter:v=>Math.round(v)}});
  chart.priceScale("s").applyOptions({scaleMargins:{top:.76,bottom:0},visible:false});
  const smap=new Map(H.score);
  sh.setData(H.score.map(([d,v])=>({time:d,value:v,color:BC[bandOf(v,B)]+"cc"})));
  class Bands{
    constructor(){this.items=[]}
    attached(p){this.chart=p.chart;this.req=p.requestUpdate}
    detached(){}
    set(items,dates){this.items=items;this.dates=dates;this.req&&this.req()}
    updateAllViews(){}
    paneViews(){const self=this;return[{zOrder:()=>"bottom",renderer:()=>({draw:t=>self.draw(t),drawBackground:()=>{}})}]}
    x(d,side){
      const ts=this.chart.timeScale(),dates=this.dates;if(!dates||!dates.length) return null;
      let lo=0,hi=dates.length-1;
      if(side>0){while(lo<hi){const m=(lo+hi+1)>>1;if(dates[m]<=d) lo=m;else hi=m-1}}
      else{while(lo<hi){const m=(lo+hi)>>1;if(dates[m]>=d) hi=m;else lo=m+1}}
      const c=ts.timeToCoordinate(dates[lo]);if(c===null) return null;
      return c+(side>0?1:-1)*ts.options().barSpacing/2;
    }
    draw(target){
      target.useBitmapCoordinateSpace(({context:ctx,bitmapSize:bs,horizontalPixelRatio:hr,verticalPixelRatio:vr})=>{
        this.items.forEach(b=>{
          const x0=this.x(b.from,-1),x1=this.x(b.to,1);if(x0===null||x1===null) return;
          const a=Math.round(x0*hr),w=Math.max(2*hr,Math.round(x1*hr)-a),col=PH[b.ph].c;
          ctx.fillStyle=col+"24";ctx.fillRect(a,0,w,bs.height*.72);
          ctx.fillStyle=col;ctx.fillRect(a,0,w,3*vr);
        });
      });
    }
  }
  const bands=new Bands();candle.attachPrimitive(bands);
  const SYMS=["SPX","NDX","KOSPI"].filter(s=>H.px[s]);
  let sym="SPX",dates=[];
  $("#symtab").innerHTML=SYMS.map(s=>`<button data-s="${s}" aria-pressed="${s===sym}">${s}</button>`).join("");
  const RG=[["近 1 年",365],["近 3 年",1095],["全部",0]];let rg=el.clientWidth<560?0:1;
  $("#ranges").innerHTML=RG.map((r,k)=>`<button data-k="${k}" aria-pressed="${k===rg}">${r[0]}</button>`).join("");
  function setRange(){
    const n=RG[rg][1];if(!n){chart.timeScale().fitContent();return}
    const end=dates[dates.length-1],t=new Date(end+"T00:00:00Z");t.setUTCDate(t.getUTCDate()-n);
    chart.timeScale().setVisibleRange({from:t.toISOString().slice(0,10),to:end});
  }
  function phaseAt(d){for(const b of H.bands) if(d>=b.from&&d<=b.to) return b.ph;return null}
  function showOhlc(r){
    if(!r) return;const ph=phaseAt(r[0]),v=smap.get(r[0]),b=bandOf(v,B);
    $("#ohlc").innerHTML=`<b>${sym}</b><span>${md(r[0])}</span><span>收 <b>${fmt(r[4],2)}</b></span><span>指數 <b style="color:${b===null?C.mute:BC[b]}">${v===undefined?"—":fmt(v,0)}</b></span>${ph?`<span class="ph" style="background:${PH[ph].c}">${PH[ph].n}</span>`:""}`;
  }
  function setSym(){
    const rows=H.px[sym];dates=rows.map(r=>r[0]);
    candle.setData(rows.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
    bands.set(H.bands,dates);showOhlc(rows[rows.length-1]);setRange();
  }
  chart.subscribeCrosshairMove(p=>{
    const rows=H.px[sym];if(!p.time){showOhlc(rows[rows.length-1]);return}
    const r=rows.find(x=>x[0]===p.time);if(r) showOhlc(r);
  });
  $("#symtab").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;sym=b.dataset.s;
    [...$("#symtab").children].forEach(x=>x.setAttribute("aria-pressed",x.dataset.s===sym));setSym()});
  $("#ranges").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;rg=+b.dataset.k;
    [...$("#ranges").children].forEach((x,k)=>x.setAttribute("aria-pressed",k===rg));setRange()});
  setSym();
}

try{render(window.RADAR)}catch(e){console.error(e);document.querySelector("#errs").innerHTML='<div class="stale">頁面渲染失敗：'+esc(e.message)+'</div>'}
})();
