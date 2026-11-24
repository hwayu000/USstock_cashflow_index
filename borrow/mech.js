(function(){
const D=window.BORROW;if(!D) return;
const a=x=>x?`${x[0]===null?"—":x[0].toFixed(2)}／${x[1]===null?"—":x[1].toFixed(2)}`:"—";
document.querySelector("#auc").innerHTML=D.cal.periods.map(p=>`<tr><td>${p.name}</td><td class="n">${p.n.toLocaleString("en-US")}</td>${["score","score3","Ap","Cp","Bp"].map(k=>`<td class="n">${a(p.auc[k])}</td>`).join("")}</tr>`).join("");
const f=v=>v===null||v===undefined?"—":v.toFixed(1)+"%",dv=D.diverge,hi=D.cal.bins[3],base=D.cal.base;
document.querySelector("#obs").innerHTML=[
 `<b>信用落後時，大跌機率較高。</b>指數在「高」區時，之後 21 日 SPX 回撤超過 10% 的比例 ${f(hi.d10)}，全期平均 ${f(base.d10)}。`,
 `<b>股漲債不跟不是警訊。</b>QQQ 單日 ≥ +2% 且高收益債落後公債共 ${dv.lag.n} 次，之後回撤超過 5% 的比例 ${f(dv.lag.d5)}；信用同步上漲時 ${dv.join.n} 次為 ${f(dv.join.d5)}。`,
 `<b>短端上升與大跌反向。</b>2 年期 21 日上升的百分位越高，之後 10% 回撤反而越少，因此只用於分辨利率上升的原因。`,
].map(x=>`<li>${x}</li>`).join("");
})();
