(function(){
const D=window.RADAR;if(!D) return;
const f=v=>v===undefined||v===null?"—":v.toFixed(1)+"%";
const a=x=>x?`${x[0]===null?"—":x[0].toFixed(2)}／${x[1]===null?"—":x[1].toFixed(2)}`:"—";
if(D.cal) document.querySelector("#auc").innerHTML=D.cal.periods.map(p=>`<tr><td>${p.name}</td><td class="n">${p.n.toLocaleString("en-US")}</td>${["score","VIXp","A","B","C","SKEWp"].map(k=>`<td class="n">${a(p.auc[k])}</td>`).join("")}</tr>`).join("");
const R=D.backtest.rows,by=n=>R.find(r=>r.name.startsWith(n))||{};
document.querySelector("#bt").innerHTML=R.map((r,k)=>`<tr${k?"":' style="background:#f3f5f7"'}><td>${r.name}${r.post?"＊":""}</td><td class="n">${r.n.toLocaleString("en-US")}</td><td class="n">${f(r.flip)}</td><td class="n">${f(r.d5)}</td><td class="n">${f(r.d10)}</td></tr>`).join("");
document.querySelector("#btr").textContent=`${D.backtest.from} 至 ${D.backtest.to}`;
const b=R[0],s=by("SKEW"),n=by("SKEW、"),c=by("COR3M 第 75"),cl=by("COR3M 第 25"),g=by("GEX 第 25"),gh=by("GEX 第 75"),dh=by("DSPX 第 75"),dl=by("DSPX 第 25");
document.querySelector("#btn").innerHTML=[
 `<b>時序站得住。</b>${D.evCount} 次事件半衰中位 ${D.halfMed} 日、回落完成中位 ${D.quarterMed} 日，與節目的 3 日及五六個交易日一致。`,
 `<b>無法預告翻轉時點。</b>節目的三項條件達兩項時，21 日內翻轉 ${f(n.flip)}，基準 ${f(b.flip)}，因此不再單獨列為「脆斷」階段。`,
 `<b>SKEW 偏貴不代表會大跌。</b>翻轉機率 ${f(s.flip)} 高於基準，但回撤超過 10% 只有 ${f(s.d10)}，符合節目「已算進價格」的說法。`,
 `<b>同步度與 Gamma 較能反映深度。</b>COR3M 高、低同步的 10% 回撤為 ${f(c.d10)} 與 ${f(cl.d10)}；GEX 低、高為 ${f(g.d10)} 與 ${f(gh.d10)}。兩者對翻轉時點沒有明顯領先。`,
 `<b>DSPX 方向與節目相反。</b>高離散翻轉 ${f(dh.flip)}、低離散 ${f(dl.flip)}。DSPX 是個股隱含離散度，並非判斷離散度，此處只否定該代理指標。`
].map(x=>`<li>${x}</li>`).join("");
})();
