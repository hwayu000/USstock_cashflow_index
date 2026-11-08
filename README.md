# 黃金錢荒儀表板

追蹤美國回購市場資金壓力，以及它對黃金與美股指數的影響。

**網站：** https://hwayu000.github.io/USstock_cashflow_index/

## 內容
- 目前所處階段：錢荒、補水、修復
- 歷次資金緊張事件與 NQ、ES、黃金走勢對照
- 每日追蹤的關鍵訊號
- 分頁「共識崩塌」（`consensus/`）：共識崩塌指數 0–100，由 VIX/VIX3M、COR3M、做市商 Gamma 三項 5 年百分位合成，附歷史校準與恐慌回落階段

## 資料來源
紐約聯儲、美國財政部、FRED、CFTC、Yahoo Finance；共識崩塌分頁另用 Cboe 指數與延遲選擇權報價、SqueezeMetrics GEX、Naver（KOSPI 備援）。資料由 GitHub Actions 每個交易日自動更新。

圖表使用 [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/)。

## 本機預覽
```
py scripts/update.py
py consensus/scripts/update.py
```
完成後直接開啟 `index.html`。

---
本專案僅供資訊參考，不構成投資建議。
