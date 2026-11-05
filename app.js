(function(){
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const C={red:"#e30613",yellow:"#946000",green:"#00875a",gray:"#a3aab3",cyan:"#e30613",ink:"#0f1114",mute:"#5c6570"};
const PH={crunch:{n:"錢荒",c:"#e30613"},refill:{n:"補水",c:"#0b5fd6"},recover:{n:"修復",c:"#00875a"}};
const PHN=["","crunch","refill","recover"];
function fmt(v,d,sign){
  if(v===null||v===undefined||isNaN(v)) return "—";
  const s=Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
  return (v<0?"−":sign&&v>0?"+":"")+s;
}
const pct=v=>v===undefined||v===null?'<span class="na">—</span>':`<span class="${v>=0?"up":"dn"}">${fmt(v,1,1)}%</span>`;
const md=d=>{const p=d.split("-");return `${p[0]}/${+p[1]}/${+p[2]}`};

/* ── 小走勢（訊號卡用） ── */
function gauge(i,d,ticks){
  const g=i.gauge;if(!g) return "";
  const f=g.log?(v=>Math.log10(Math.max(v,g.min))):(v=>v);
  const lo=f(g.min),hi=f(g.max),P=v=>Math.max(0,Math.min(100,(f(v)-lo)/(hi-lo)*100));
  const segs=g.zones.map(z=>`<span class="${z[2]}" style="width:${(P(z[1])-P(z[0])).toFixed(2)}%"></span>`).join("");
  const tk=(ticks||g.ticks||g.zones.slice(1).map(z=>[z[0],fmt(z[0],d)])).map(t=>`<span style="left:${P(t[0]).toFixed(2)}%">${esc(t[1])}</span>`).join("");
  return `<div class="gauge">${i.value===null?"":`<div class="ptr" style="left:${P(i.value).toFixed(2)}%"></div>`}<div class="track">${segs}</div><div class="ticks">${tk}</div></div>`;
}
function spark(id,S,lines,lv,unit,d,capL,mul){
  if(!S||S.length<2) return "";
  mul=mul||1;if(mul!==1) S=S.map(x=>[x[0],x[1]*mul]);
  const W=400,H=120,P=6,vals=S.map(x=>x[1]);
  let lo=Math.min(...vals),hi=Math.max(...vals);const span=(hi-lo)||1;
  lines=(lines||[]).filter(t=>t[0]>lo-span*.6&&t[0]<hi+span*.6);
  lines.forEach(t=>{lo=Math.min(lo,t[0]);hi=Math.max(hi,t[0])});
  const pad=(hi-lo||1)*.08;lo-=pad;hi+=pad;
  const X=k=>P+(W-2*P)*k/(S.length-1),Y=v=>P+(H-2*P)*(1-(v-lo)/(hi-lo));
  const pts=S.map((x,k)=>X(k).toFixed(1)+","+Y(x[1]).toFixed(1)).join(" ");
  const L=S[S.length-1];
  const ln=lines.map(t=>`<line x1="0" x2="${W}" y1="${Y(t[0]).toFixed(1)}" y2="${Y(t[0]).toFixed(1)}" stroke="${t[2]||C.mute}" stroke-opacity=".8" stroke-dasharray="4 5" stroke-width="1.2" vector-effect="non-scaling-stroke"/>`).join("");
  const ys=lines.map(t=>Y(t[0])/H*100),ord=ys.map((y,k)=>k).sort((a,b)=>ys[a]-ys[b]);
  for(let k=1;k<ord.length;k++){if(ys[ord[k]]-ys[ord[k-1]]<16) ys[ord[k]]=ys[ord[k-1]]+16}
  const lb=lines.map((t,k)=>`<span class="tl" style="top:${ys[k].toFixed(1)}%;color:${t[2]||C.mute}">${esc(t[1])}</span>`).join("");
  const gid="g"+id;
  return `<div class="spark" data-id="${id}" data-unit="${esc(unit)}" data-d="${d}" data-mul="${mul}"><div class="plot">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${C.ink}" stop-opacity=".07"/><stop offset="1" stop-color="${C.ink}" stop-opacity="0"/></linearGradient></defs>${ln}
    <polygon points="${X(0).toFixed(1)},${H} ${pts} ${X(S.length-1).toFixed(1)},${H}" fill="url(#${gid})"/>
    <polyline points="${pts}" fill="none" stroke="${C.ink}" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    <line class="cur" x1="0" x2="0" y1="0" y2="${H}" stroke="${C.cyan}" stroke-width="1" opacity="0" vector-effect="non-scaling-stroke"/>
    <circle cx="${X(S.length-1).toFixed(1)}" cy="${Y(L[1]).toFixed(1)}" r="5" fill="${C[lv]||C.mute}" stroke="#ffffff" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>${lb}</div>
    <div class="cap"><span class="tipL">${esc(capL)}</span><span>最新 <b>${fmt(L[1],d)}</b> ${esc(unit)}</span></div></div>`;
}
const light=(lv,name,v)=>`<li><i class="${lv}"></i>${esc(name)}<b>${v}</b></li>`;

/* ═════ 主資料 ═════ */
function render(D){
  const by={};D.indicators.forEach(i=>by[i.id]=i);
  const A={};D.alerts.forEach(a=>A[a.id]=a);
  const t=new Date(D.updated.replace(" UTC","Z").replace(" ","T"));
  $("#stamp").textContent=isNaN(t)?D.updated:"更新 "+t.toLocaleString("zh-TW",{timeZone:"Asia/Taipei",month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false});

  const pc=PH[PHN[D.phase]].c;
  document.documentElement.style.setProperty("--pc",pc);
  const ph=$("#phase");ph.className="phase p"+D.phase;
  ph.innerHTML=`${esc(D.regime)}<small>SOFR − IORB <b class="num" style="color:${C.ink}">${fmt(by.spread.value,1,1)} bp</b>　·　紅燈 <b class="num" style="color:${C.ink}">${D.stress}</b> 項</small>`;
  $("#pstep").textContent=`${D.phase} / 3`;
  $("#orbn").innerHTML=`${D.phase}<small>/3</small>`;
  const S=[["錢荒期","SOFR 高於 IORB"],["補水期","RMP ≥ 200 億／4 週"],["修復期","SOFR ≤ IORB 連續 3 日"]];
  $("#rail").innerHTML=S.map((s,k)=>`<div class="${k+1<D.phase?"done":k+1===D.phase?"cur":""}"><div class="px"></div><b><i>0${k+1}</i>${s[0]}</b><span>${s[1]}</span></div>`).join("");

  let nx;
  if(D.phase===1){
    nx={h:"補水啟動",p:"RMP 四週增持達 200 億美元",cur:Math.max(0,by.rmp.value||0)*10,goal:200,unit:"億美元",l:"RMP 四週增持"};
  }else if(D.phase===2){
    const s=by.spread.value;
    nx={h:"錢荒解除",p:"SOFR − IORB 連續 3 日 ≤ 0",cur:Math.max(0,15-s),goal:15,raw:`利差 ${fmt(s,1,1)} bp → 0`};
  }else{
    nx={h:"籌碼洗乾淨",p:"投機淨多 < 未平倉 40%",cur:Math.max(0,70-by.cot.value),goal:30,raw:`投機淨多 ${fmt(by.cot.value,0)}% → 40%`};
  }
  const p=Math.max(0,Math.min(1,nx.cur/nx.goal)),on=Math.round(p*20);
  $("#next").innerHTML=`<p class="eyebrow"><span class="k">next</span><span class="v">= 下一步</span></p><h3>${nx.h}</h3><p>${nx.p}</p>
    <div class="cells" role="img" aria-label="進度 ${Math.round(p*100)}%">${Array.from({length:20},(_,k)=>`<i class="${k<on?"on":k===19?"goal":""}"></i>`).join("")}</div>
    <div class="pv">${nx.raw?`<span>${esc(nx.raw)}</span><span class="g"><b class="num">${Math.round(p*100)}</b>%</span>`
      :`<span>目前<b class="num">${fmt(nx.cur,0)}</b></span><span class="g">目標<b class="num">${nx.goal}</b>${nx.unit}</span>`}</div>`;

  /* 三訊號 */
  const sp=by.spread,rm=by.rmp,dd=by.drawdown,gl=by.gld;
  const q1={red:["還在","> 5 bp"],yellow:["緩解中","0–5 bp"],green:["解除","≤ 0"]}[sp.level]||["—",""];
  const refillLv=A.refill.on?"green":(rm.level==="yellow"||by.tga.level==="green")?"yellow":"red";
  const q2={red:["還沒","RMP 未動"],yellow:["在路上","未達 200 億"],green:["來了","達標"]}[refillLv];
  const q3={red:["還沒","< 369"],yellow:["一半","369–373"],green:["收復","≥ 373"]}[gl.level]||["—",""];
  const tgaBal=(by.tga.series||[]).slice(-1)[0],tgaLeft=tgaBal?(tgaBal[1]-850)*10:0;
  $("#sigs").innerHTML=`
  <article class="card sig">
    <h3><i>01</i>錢荒</h3>
    <div class="ans"><span class="word ${sp.level}">${q1[0]}</span><span class="why">${q1[1]}</span></div>
    <div class="main"><span>SOFR − IORB</span><b class="num">${fmt(sp.value,1,1)}<small>bp</small></b></div>
    ${gauge(sp,0,[[0,"0"],[5,"5"]])}
    ${spark("spread",sp.series,[[0,"0 正常",C.green],[5,"5 錢荒",C.red]],sp.level,"bp",1,"近 90 日")}
    <ul class="lights">
      ${light(by.tail.level,"尾部利率 − SRF 天花板",fmt(by.tail.value,1,1)+" bp")}
      ${light(by.reserves.level,"銀行準備金",fmt(by.reserves.value,2)+" 兆")}
      ${light(by.rrp.level,"隔夜逆回購",fmt(by.rrp.value*10,0)+" 億")}
    </ul>
  </article>
  <article class="card sig">
    <h3><i>02</i>補水</h3>
    <div class="ans"><span class="word ${refillLv}">${q2[0]}</span><span class="why">${q2[1]}</span></div>
    <div class="main"><span>RMP 四週增持</span><b class="num">${fmt((rm.value||0)*10,0,1)}<small>億美元</small></b></div>
    ${gauge(rm,0,[[2,"20億"],[20,"200億"]])}
    ${spark("tga",by.tga.series,[[8500,"目標 8,500",C.cyan]],by.tga.level,"億美元",0,"TGA 餘額",10)}
    <ul class="lights">
      ${light(tgaLeft>0?"yellow":"green","TGA 距年底目標",tgaLeft>0?"還要放 "+fmt(tgaLeft,0)+" 億":"已達標")}
      ${light(by.tga.level,"TGA 四週變化",fmt((by.tga.value||0)*10,0,1)+" 億")}
      ${light(by.srf.level,"SRF 緊急窗口用量",fmt((by.srf.value||0)*10,0)+" 億")}
    </ul>
  </article>
  <article class="card sig">
    <h3><i>03</i>收復</h3>
    <div class="ans"><span class="word ${gl.level}">${q3[0]}</span><span class="why">${q3[1]}</span></div>
    <div class="main"><span>GLD 收盤</span><b class="num">${fmt(gl.value,2)}<small>美元</small></b></div>
    ${gauge(gl,0)}
    ${spark("gld",gl.series,[[369,"369",C.yellow],[373,"373",C.green]],gl.level,"美元",2,"近 120 日")}
    <ul class="lights">
      ${light(dd.level,"期金距高點回撤",fmt(dd.value,1)+"%")}
      ${light(by.resid.level,"金價殘差",fmt(by.resid.value,0,1)+" 美元")}
      ${light(by.cot.level,"投機淨多 / 未平倉",fmt(by.cot.value,0)+"%")}
    </ul>
  </article>`;
  document.querySelectorAll(".spark").forEach(c=>{
    const id=c.dataset.id,Sx=by[id].series,svg=c.querySelector("svg"),cur=c.querySelector(".cur"),tl=c.querySelector(".tipL"),d=+c.dataset.d,u=c.dataset.unit,def=tl.textContent,mul=+c.dataset.mul||1;
    svg.addEventListener("pointermove",e=>{
      const b=svg.getBoundingClientRect(),k=Math.max(0,Math.min(Sx.length-1,Math.round((e.clientX-b.left)/b.width*(Sx.length-1))));
      const x=6+388*k/(Sx.length-1);cur.setAttribute("x1",x);cur.setAttribute("x2",x);cur.setAttribute("opacity","1");
      tl.textContent=Sx[k][0]+"　"+fmt(Sx[k][1]*mul,d)+" "+u;
    });
    svg.addEventListener("pointerleave",()=>{cur.setAttribute("opacity","0");tl.textContent=def});
  });

  $("#alerts").innerHTML=[...D.alerts].sort((a,b)=>b.on-a.on).map(a=>`<div class="al">
    <div><span class="tag ${a.on?a.kind:""}">${a.on?"觸發中":"未觸發"}</span></div>
    <div class="n">${esc(a.name)}</div><div class="r">${esc(a.rule)}</div><div class="c">${esc(a.now)}</div></div>`).join("");
  const NM={SOFR:"SOFR",SOFR99:"SOFR 尾部",IORB:"IORB",DFEDTARU:"目標利率",RRPONTSYD:"逆回購",WRESBAL:"銀行準備金",WTREGEN:"TGA 週資料",DFII10:"TIPS",RPONTSYD:"SRF",WSHOBL:"聯儲短債"};
  if(D.stale&&D.stale.length){const e=$("#errs");e.className="stale";e.textContent="資料停更："+D.stale.map(k=>NM[k]||k).join("、")+"，相關燈號可能失準";}
}

/* ═════ 歷次錢荒對照 ═════ */
function hist(H,D){
  const LW=window.LightweightCharts;
  if(!LW||!H){$("#tv").innerHTML='<p style="color:var(--mute);padding:20px">圖表資料載入失敗</p>';return}
  const livePhase=PHN[D?D.phase:1];
  const eps=H.episodes;
  let sym="NQ",sel=null;

  // 每日 → 階段（游標讀值用）
  const phaseAt=d=>{
    // 週線：該週 [週一, 週日] 與色帶有重疊即算；日線：精確落在區間內
    const e=WEEK?addDays(d,6):d;
    for(const b of H.bands) if(e>=b.from&&d<=b.to) return b.phase;
    const L=eps.find(e=>e.live);if(L&&d>=L.crunch[0]) return "live";
    return null;
  };
  const spMap=new Map(H.spread),spIdx=new Map(H.spread.map((r,k)=>[r[0],k]));

  const el=$("#tv");
  const chart=LW.createChart(el,{
    autoSize:true,
    layout:{background:{type:"solid",color:"transparent"},textColor:C.mute,fontFamily:"Archivo, Noto Sans TC, sans-serif",fontSize:13},
    grid:{vertLines:{color:"rgba(15,17,20,.05)"},horzLines:{color:"rgba(15,17,20,.05)"}},
    rightPriceScale:{borderColor:"rgba(15,17,20,.2)",scaleMargins:{top:.1,bottom:.24}},
    timeScale:{borderColor:"rgba(15,17,20,.2)",rightOffset:8,minBarSpacing:.3},
    crosshair:{mode:0,vertLine:{color:"rgba(15,17,20,.45)",style:2,labelBackgroundColor:"#0f1114"},horzLine:{color:"rgba(15,17,20,.3)",style:2,labelBackgroundColor:"#0f1114"}},
    handleScale:{axisPressedMouseMove:{time:true,price:false}},
    localization:{locale:"zh-TW",dateFormat:"yyyy/MM/dd"}
  });

  const candle=chart.addCandlestickSeries({
    upColor:"#ffffff",borderUpColor:"#0f1114",wickUpColor:"#0f1114",
    downColor:"#0f1114",borderDownColor:"#0f1114",wickDownColor:"#0f1114",
    priceLineColor:"rgba(227,6,19,.7)",priceLineStyle:2
  });

  const hist=chart.addHistogramSeries({priceScaleId:"sp",priceLineVisible:false,lastValueVisible:false,base:0,
    priceFormat:{type:"custom",minMove:1,formatter:v=>Math.round(v)+"bp"}});
  chart.priceScale("sp").applyOptions({scaleMargins:{top:.82,bottom:0},visible:false});
  const CAP=40;
  // 窄螢幕改週線：日線 2000 多根塞不進手機寬度
  const WEEK=el.clientWidth/((H.px.NQ||[]).length||1)<.45;
  const wk=d=>{const t=new Date(d+"T00:00:00Z"),g=(t.getUTCDay()+6)%7;t.setUTCDate(t.getUTCDate()-g);return t.toISOString().slice(0,10)};
  const weekly=rows=>{const out=[];rows.forEach(r=>{const k=wk(r[0]),L=out[out.length-1];
    if(L&&L[0]===k){L[2]=Math.max(L[2],r[2]);L[3]=Math.min(L[3],r[3]);L[4]=r[4]}else out.push([k,r[1],r[2],r[3],r[4]])});return out};
  const spRows=WEEK?(()=>{const o=[];H.spread.forEach(([d,v])=>{const k=wk(d),L=o[o.length-1];if(L&&L[0]===k){L[1]=Math.max(L[1],v)}else o.push([k,v])});return o})():H.spread;
  const PX=k=>WEEK?weekly(H.px[k]||[]):(H.px[k]||[]);
  hist.setData(spRows.map(([d,v])=>({time:d,value:Math.max(-15,Math.min(CAP,v)),
    color:v>5?"rgba(227,6,19,.85)":v>0?"rgba(214,150,0,.7)":"rgba(15,17,20,.14)"})));

  /* 階段色帶：自訂 primitive，畫在 K 線之下 */
  class Bands{
    constructor(){this.items=[]}
    attached(p){this.chart=p.chart;this.series=p.series;this.req=p.requestUpdate}
    detached(){}
    set(items){this.items=items;this.req&&this.req()}
    updateAllViews(){}
    paneViews(){const self=this;return[{zOrder:()=>"bottom",renderer:()=>({draw:t=>self.draw(t),drawBackground:()=>{}})}]}
    x(d,side){
      const ts=this.chart.timeScale(),dates=this.dates;if(!dates||!dates.length) return null;
      if(WEEK&&d!=="9999") d=wk(d);
      let lo=0,hi=dates.length-1;
      if(side>0){while(lo<hi){const m=(lo+hi+1)>>1;if(dates[m]<=d) lo=m;else hi=m-1}}
      else{while(lo<hi){const m=(lo+hi)>>1;if(dates[m]>=d) hi=m;else lo=m+1}}
      const c=ts.timeToCoordinate(dates[lo]);if(c===null) return null;
      const half=ts.options().barSpacing/2;
      return c+(side>0?half:-half);
    }
    draw(target){
      target.useBitmapCoordinateSpace(({context:ctx,bitmapSize:bs,horizontalPixelRatio:hr,verticalPixelRatio:vr})=>{
        const rows=[0,0];
        this.items.forEach((b,k)=>{
          let x0=this.x(b.from,-1),x1=b.toNext?this.x(b.toNext,-1):this.x(b.to,1);
          if(x0===null||x1===null) return;
          x0=Math.round(x0*hr);x1=Math.round(x1*hr);const w=Math.max(2*hr,x1-x0);
          ctx.save();
          if(b.live){
            ctx.fillStyle=b.color+"1f";ctx.fillRect(x0,0,w,bs.height);
            ctx.beginPath();ctx.rect(x0,0,w,bs.height);ctx.clip();
            ctx.strokeStyle=b.color+"59";ctx.lineWidth=1.5*hr;
            for(let s=-bs.height;s<w;s+=9*hr){ctx.beginPath();ctx.moveTo(x0+s,bs.height);ctx.lineTo(x0+s+bs.height,0);ctx.stroke()}
          }else{
            ctx.fillStyle=b.color+(b.sel?"38":"24");ctx.fillRect(x0,0,w,bs.height);
          }
          ctx.restore();
          ctx.fillStyle=b.color;ctx.fillRect(x0,0,w,3*vr);
          if(b.label){
            const fs=13*vr;ctx.font=`600 ${fs}px "Noto Sans TC", sans-serif`;
            const tw=ctx.measureText(b.label).width,row=b.row||0,y=(10+row*22)*vr;
            ctx.fillStyle="rgba(255,255,255,.92)";
            const pad=6*hr;ctx.fillRect(x0,y,tw+pad*2,fs+8*vr);
            ctx.fillStyle=b.live?b.color:"#0f1114";ctx.textBaseline="top";ctx.fillText(b.label,x0+pad,y+4*vr);
          }
        });
      });
    }
  }
  const bands=new Bands();candle.attachPrimitive(bands);

  function bandItems(){
    const out=[];let row=0,lastEnd="";
    // 日線：相鄰階段首尾相接（下一段起點的左緣＝本段右緣），避免 SOFR 休市但期貨有開的日子留空隙
    if(WEEK){
      // 週線：每根週 K 只歸一個階段（該週交易日最多的階段），相鄰同階段的週合併，避免一根 K 疊兩色
      const wkPh=new Map();
      H.spread.forEach(([d])=>{let ph=null;for(const b of H.bands) if(d>=b.from&&d<=b.to){ph=b.phase;break}
        const k=wk(d),m=wkPh.get(k)||{};m[ph]=(m[ph]||0)+1;wkPh.set(k,m)});
      let cur=null;
      [...wkPh.keys()].sort().forEach(k=>{const m=wkPh.get(k);
        const ph=Object.keys(m).reduce((a,b)=>m[b]>=m[a]?b:a);
        if(ph==="null"){cur=null;return}
        if(cur&&cur.ph===ph){cur.to=k}else{cur={ph,from:k,to:k};out.push(cur)}});
      out.forEach(o=>{o.color=PH[o.ph].c});
    }else
    H.bands.forEach((b,k)=>{const n=H.bands[k+1];
      const touch=!WEEK&&n&&spIdx.get(n.from)===spIdx.get(b.to)+1;
      out.push({from:b.from,to:b.to,toNext:touch?n.from:null,color:PH[b.phase].c})});
    eps.forEach(e=>{
      if(e.live){out.push({from:e.crunch[0],to:"9999",color:PH[livePhase].c,live:true,label:"本次",row:0});return}
      const end=(e.recover||e.refill||e.crunch)[1];
      row=(e.crunch[0]<lastEnd)?1-row:0;lastEnd=end;
      out.push({from:e.crunch[0],to:e.crunch[0],color:PH.crunch.c,label:e.name,row:row,mark:true,sel:sel===e.key});
    });
    // 標籤錨點只畫標籤（寬度 0 的色帶不畫底色）
    return out.map(o=>o.mark?{...o,color:o.color,to:o.from,labelOnly:true}:o);
  }
  // 改寫 draw：labelOnly 只畫文字
  const _draw=bands.draw.bind(bands);
  bands.draw=function(t){
    const all=this.items;this.items=all.filter(b=>!b.labelOnly);_draw(t);
    this.items=all.filter(b=>b.labelOnly).map(b=>({...b,lab:true}));
    t.useBitmapCoordinateSpace(({context:ctx,horizontalPixelRatio:hr,verticalPixelRatio:vr})=>{
      const placed=[];
      this.items.forEach(b=>{
        const x=this.x(b.from,-1);if(x===null) return;
        const fs=13*vr;ctx.font=`600 ${fs}px "Noto Sans TC", sans-serif`;
        const tw=ctx.measureText(b.label).width,pad=6*hr,x0=Math.round(x*hr),wd=tw+pad*2;
        let row=0;while(placed.some(p=>p.row===row&&x0<p.x1+4*hr&&x0+wd>p.x0)) row++;
        placed.push({row,x0,x1:x0+wd});
        const y=(10+row*24)*vr;
        ctx.fillStyle=b.sel?"#0f1114":"rgba(255,255,255,.92)";ctx.fillRect(x0,y,wd,fs+8*vr);
        ctx.fillStyle=PH.crunch.c;ctx.fillRect(x0,y,2*hr,fs+8*vr);
        ctx.fillStyle=b.sel?"#ffffff":"#0f1114";ctx.textBaseline="top";ctx.fillText(b.label,x0+pad,y+4*vr);
      });
    });
    this.items=all;
  };

  function setSym(k){
    sym=k;
    const rows=PX(k);
    candle.setData(rows.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
    // 色帶定位用「K 線＋利差柱」的完整時間軸（兩者交易日不完全相同）
    bands.dates=[...new Set([...rows.map(r=>r[0]),...spRows.map(r=>r[0])])].sort();
    bands.set(bandItems());
    candle.applyOptions({priceFormat:{type:"price",precision:k==="GC"?1:2,minMove:k==="GC"?.1:.25}});
    document.querySelectorAll("#symtab button").forEach(b=>b.setAttribute("aria-pressed",b.dataset.k===k));
    table();overlay();legend(null);
  }
  const symName=k=>(H.symbols.find(s=>s.key===k)||{}).name||k;
  const symShort={NQ:"NQ",ES:"ES",GC:"黃金"};

  $("#symtab").innerHTML=H.symbols.map(s=>`<button data-k="${s.key}" aria-pressed="false">${symShort[s.key]||s.key}</button>`).join("");
  $("#symtab").addEventListener("click",e=>{const b=e.target.closest("button");if(b) setSym(b.dataset.k)});

  // 事件快捷
  const addDays=(d,n)=>{const t=new Date(d+"T00:00:00Z");t.setUTCDate(t.getUTCDate()+n);return t.toISOString().slice(0,10)};
  function focus(key){
    sel=key;
    const rows=H.px[sym]||[],last=rows.length?rows[rows.length-1][0]:"";
    if(key==="all"){chart.timeScale().fitContent()}
    else{
      const e=eps.find(x=>x.key===key);if(!e) return;
      const end=e.live?last:(e.recover||e.refill||e.crunch)[1];
      chart.timeScale().setVisibleRange({from:addDays(e.crunch[0],e.live?-120:-75),to:e.live?last:addDays(end,75)});
    }
    document.querySelectorAll("#chips button").forEach(b=>b.setAttribute("aria-pressed",b.dataset.k===key));
    document.querySelectorAll("#eps tr").forEach(r=>r.classList.toggle("sel",r.dataset.k===key));
    bands.set(bandItems());overlay();
  }
  $("#chips").innerHTML=`<button data-k="all" aria-pressed="true">全部</button>`+
    eps.map(e=>`<button data-k="${e.key}" class="${e.live?"now":""}" aria-pressed="false">${esc(e.live?"本次":e.name)}</button>`).join("");
  $("#chips").addEventListener("click",e=>{const b=e.target.closest("button");if(b) focus(b.dataset.k)});

  // 游標讀值
  function legend(p){
    const rows=PX(sym);if(!rows.length) return;
    let d,o,h,l,c;
    if(p&&p.time&&p.seriesData.get(candle)){const v=p.seriesData.get(candle);d=typeof p.time==="string"?p.time:`${p.time.year}-${String(p.time.month).padStart(2,"0")}-${String(p.time.day).padStart(2,"0")}`;({open:o,high:h,low:l,close:c}=v)}
    else{const r=rows[rows.length-1];[d,o,h,l,c]=r}
    const ph=phaseAt(d),dg=sym==="GC"?1:2;
    const pl=ph==="live"?{n:"本次・"+PH[livePhase].n,c:PH[livePhase].c}:ph?PH[ph]:null;
    const s=WEEK?(spRows.find(x=>x[0]===d)||[])[1]:spMap.get(d);
    $("#ohlc").innerHTML=`<span><b>${symShort[sym]}</b> ${md(d)}${WEEK?" 週":""}</span><span>開 <b>${fmt(o,dg)}</b></span><span>高 <b>${fmt(h,dg)}</b></span><span>低 <b>${fmt(l,dg)}</b></span><span>收 <b>${fmt(c,dg)}</b></span>`+
      (s!==undefined?`<span>SOFR−IORB <b style="color:${s>5?C.red:s>0?C.yellow:C.ink}">${fmt(s,0,1)} bp</b></span>`:"")+
      (pl?`<span class="ph" style="color:${pl.c};background:${pl.c}1f">${pl.n}</span>`:"");
  }
  chart.subscribeCrosshairMove(legend);

  // 事件表
  function table(){
    $("#eps").innerHTML=eps.map(e=>{
      const s=(e.stats||{})[sym]||{};
      const dots=["crunch","refill","recover"].map(k=>`<i style="${e[k]||(e.live&&k===livePhase)?`background:${PH[k].c}`:""}" title="${PH[k].n}"></i>`).join("");
      const rng=e.live?`${md(e.crunch[0])} 起`:`${md(e.crunch[0])} – ${md((e.recover||e.refill||e.crunch)[1])}`;
      return `<tr data-k="${e.key}" class="${e.live?"nowrow":""} ${sel===e.key?"sel":""}" tabindex="0">
        <td><span class="nm" style="${e.live?"color:var(--acc)":""}">${esc(e.name)}</span><span class="dt">${rng}</span></td>
        <td><span class="ph">${dots}</span></td>
        <td class="num">${fmt(e.peak,0,1)}<span class="na" style="font-size:14px"> bp</span></td>
        <td>${pct(s.during)}</td><td>${pct(s.dd)}</td><td>${e.live?'<span class="na">進行中</span>':pct(s.after)}</td></tr>`;
    }).join("");
  }
  $("#eps").addEventListener("click",e=>{const r=e.target.closest("tr");if(r){focus(r.dataset.k);$("#tv").scrollIntoView({behavior:"smooth",block:"center"})}});
  $("#eps").addEventListener("keydown",e=>{if(e.key==="Enter"){const r=e.target.closest("tr");if(r) focus(r.dataset.k)}});
  $("#eps").addEventListener("pointerover",e=>{const r=e.target.closest("tr");overlay(r&&r.dataset.k)});
  $("#eps").addEventListener("pointerleave",()=>overlay());

  // 對齊疊圖：以錢荒前一日收盤 = 0%，X 軸為交易日
  function overlay(hl){
    const rows=H.px[sym]||[],dates=rows.map(r=>r[0]);
    const PRE=10,POST=120,W=Math.max(300,Math.round($("#ov").clientWidth||520)),Hh=W<420?300:420,L=44,R=14,T=12,B=30;
    const lines=eps.map(e=>{
      let i0=dates.findIndex(d=>d>=e.crunch[0]);if(i0<0) return null;i0=Math.max(0,i0-1);
      const base=rows[i0][4],pts=[];
      for(let k=-PRE;k<=POST;k++){const i=i0+k;if(i<0||i>=rows.length) continue;pts.push([k,(rows[i][4]/base-1)*100])}
      return {e,pts};
    }).filter(Boolean);
    let lo=-5,hi=5;lines.forEach(l=>l.pts.forEach(p=>{lo=Math.min(lo,p[1]);hi=Math.max(hi,p[1])}));
    lo=Math.floor(lo/10)*10;hi=Math.ceil(hi/10)*10;
    const X=k=>L+(W-L-R)*(k+PRE)/(PRE+POST),Y=v=>T+(Hh-T-B)*(1-(v-lo)/(hi-lo));
    let g="";
    for(let v=lo;v<=hi;v+=10) g+=`<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="rgba(15,17,20,${v===0?.35:.07})"/><text x="${L-8}" y="${Y(v)+4}" text-anchor="end" fill="${C.mute}" font-size="12" font-family="Archivo">${v>0?"+":""}${v}%</text>`;
    [0,20,40,60,80,100,120].forEach(k=>g+=`<text x="${X(k)}" y="${Hh-8}" text-anchor="middle" fill="${C.mute}" font-size="12" font-family="Archivo">${k===0?"起點":k+"日"}</text>`);
    g+=`<line x1="${X(0)}" x2="${X(0)}" y1="${T}" y2="${Hh-B}" stroke="${C.red}" stroke-opacity=".6" stroke-dasharray="3 4"/>`;
    const focusKey=hl||sel;
    const order=[...lines].sort((a,b)=>(a.e.live?2:a.e.key===focusKey?1:0)-(b.e.live?2:b.e.key===focusKey?1:0));
    const path=pts=>pts.map((p,k)=>(k?"L":"M")+X(p[0]).toFixed(1)+" "+Y(p[1]).toFixed(1)).join("");
    order.forEach(l=>{
      const on=l.e.key===focusKey,live=l.e.live;
      const col=live?C.cyan:on?C.ink:"rgba(15,17,20,.2)";
      g+=`<path d="${path(l.pts)}" fill="none" stroke="${col}" stroke-width="${live?2.6:on?2.2:1.2}" stroke-linejoin="round"/>`;
      const lp=l.pts[l.pts.length-1];
      if(live||on) g+=`<circle cx="${X(lp[0])}" cy="${Y(lp[1])}" r="4.5" fill="${col}"/><text x="${Math.min(X(lp[0])+8,W-R-60)}" y="${Y(lp[1])-8}" fill="${col}" font-size="13" font-weight="600" font-family="Noto Sans TC">${esc(live?"本次 第"+(lp[0])+"日":l.e.name)}</text>`;
    });
    $("#ov").innerHTML=`<svg viewBox="0 0 ${W} ${Hh}" width="${W}" height="${Hh}" role="img" aria-label="各次錢荒對齊疊圖">${g}</svg>`;
    $("#ovt").textContent=`${symShort[sym]} 各次錢荒疊圖`;
    $("#ovlg").innerHTML=`<span style="color:var(--acc)">━ 本次</span>　<span style="color:var(--ink)">━ 選取事件</span>　<span>━ 其他事件</span>　0% = 錢荒前一日收盤`;
  }


  setSym("NQ");
  chart.timeScale().fitContent();
  let rz;window.addEventListener("resize",()=>{clearTimeout(rz);rz=setTimeout(()=>overlay(),150)});
}

const D=window.DASH,H=window.HIST;
if(D) render(D);
hist(H,D);
})();
