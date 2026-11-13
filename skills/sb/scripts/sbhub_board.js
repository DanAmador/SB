/* sbhub_board.js: the hub page's renderer (sbhub.html, served as /board.js): a self-updating kanban board.
   It fetches nothing on its own clock. A host calls SBBoard(root, io) once, then board.render(state, opts) on every new state.
     io.answer(qid, option) / io.send(to, text) / io.unsend(id) -> Promise of null, or why it failed
     io.queue(path, body)  post a queue write (api/queue/..., api/agents/scan) -> Promise of the hub's answer,
                           {ok, stale, queue, error, ...}. Only set, move, options, agents, remove_job and clear-finished
                           carry the queue's version: the hub checks it there
     io.act(path, body)    post any other write (api/ticket/<action>, api/agents/dismiss, api/agents/clear-quiet) -> {ok, error}
     io.get(path, text)    read a hub route (api/ticket, api/item/report) -> Promise of JSON, or text when text is true
     io.changed(tickets)   refresh now (tickets true: the open tickets too)
     io.readonly           the phone page on the WiFi: every write control is hidden except Clear finished, Dismiss
                           and Clear quiet sessions (display state only)
     opts: {live: [ok, text], down: banner text or '', tickets: api/tickets rows or null while unread}
   Every state value goes through esc; no inline handlers; nothing external is loaded. Paths are relative, so the
   same page works under the phone page's /v/<token>/ prefix.
   Icons: Tabler Icons (tabler.io), MIT licence, outline set, inlined as path data below. */
(function () {
'use strict';
const STYLE = `
.sb{font:13px/1.4 var(--font,-apple-system,system-ui,sans-serif);color:var(--ink);font-variant-numeric:tabular-nums}
.sb *{box-sizing:border-box}
.sb svg{width:1em;height:1em;flex:none;vertical-align:-.14em}
.sb button{font:inherit;font-size:12.5px;padding:4px 10px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;max-width:100%;white-space:normal;text-align:left;overflow-wrap:anywhere;min-height:28px}
.sb button:hover:not(:disabled){border-color:var(--mute)}
.sb button.def{background:var(--acc);border-color:var(--acc);color:var(--onacc)}
.sb button.danger{border-color:var(--bad);color:var(--bad)}
.sb button:disabled{cursor:default;opacity:.5}
.sb button.chosen{opacity:1;outline:2px solid var(--ok);outline-offset:1px}
.sb :focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.sb select,.sb input:not([type=checkbox]),.sb textarea{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:4px 8px;min-height:30px;min-width:0;max-width:100%}
.sb input[type=checkbox]{width:16px;height:16px;margin:0;accent-color:var(--acc);flex:none;cursor:pointer}
.sb a{color:var(--acc)}
.sb-head{display:flex;flex-direction:column;gap:6px;padding:8px 0;background:var(--bg);position:sticky;top:0;z-index:5;border-bottom:1px solid var(--line);margin-bottom:8px}
.sb-bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;min-width:0}
.sb-brand{font-weight:650;font-size:14px}
.sb-live{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--mute)}
.sb-live i{width:7px;height:7px;border-radius:50%;background:var(--ok)}.sb-live.off i{background:var(--mute)}
.sb-stats{display:flex;flex-wrap:wrap;gap:4px;flex:1;min-width:0;align-items:center}
.pill{display:inline-flex;align-items:center;gap:4px;font-size:12px;padding:1px 8px;border-radius:99px;background:var(--hover);color:var(--mute);white-space:nowrap}
.pill.bad{background:var(--badbg);color:var(--bad);font-weight:600}.pill.ok{color:var(--ok)}
.pill.acc{background:var(--accbg);color:var(--acc);font-weight:600}
.pill.warn{background:var(--warnbg);color:var(--warn);font-weight:600}
.pill.ag{background:var(--panel);border:1px solid var(--line);color:var(--ink)}
.pill.ag .w{color:var(--mute)}.pill.ag.run .w{color:var(--acc)}.pill.ag.lim{border-color:var(--warn)}.pill.ag.lim .w{color:var(--warn)}.pill.ag.out{border-color:var(--bad)}.pill.ag.out .w{color:var(--bad)}
.sb button.pill{min-height:0;padding:1px 8px;font-size:12px;border-radius:99px;border:1px solid var(--line);background:var(--panel);color:var(--ink);display:inline-flex;gap:4px;align-items:center;white-space:nowrap}
.sb-sep{width:1px;height:16px;background:var(--line);margin:0 2px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--mute);flex:none}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}
.sb-banner{background:var(--warnbg);color:var(--warn);border:1px solid var(--warn);border-radius:var(--r);padding:6px 10px;font-weight:600}
.sb.down .sb-body{opacity:.6}
.sb h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:0;font-weight:600}
.sb h3{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:12px 0 4px;font-weight:600}
.sb .mute{color:var(--mute);font-size:12px}
.sb .err{color:var(--bad);font-weight:600}.sb .okc{color:var(--ok)}
.ic{flex:none;width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;color:var(--mute)}
.ic svg{width:15px;height:15px;vertical-align:0}
.ic.bad{color:var(--bad)}.ic.ok{color:var(--ok)}.ic.acc{color:var(--acc)}.ic.warn{color:var(--warn)}
.spin svg{animation:sbspin 1.4s linear infinite}
@keyframes sbspin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.spin svg{animation:none}}
.one{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.sb details>summary{list-style:none;cursor:pointer}
.sb details>summary::-webkit-details-marker{display:none}
/* the queue's controls, the job form, the filters and the message box, under the counts */
.sb-ctl{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px}
.sb-ctl label{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--mute)}
.sb .sb-ctl button{display:inline-flex;align-items:center;gap:5px}
.pool{display:inline-flex;flex-wrap:wrap;align-items:center;gap:4px 10px;border:0;margin:0;padding:0;font-size:12px;color:var(--mute);min-width:0}
.pool legend{float:left;padding:0;margin-right:4px}.pool label{display:inline-flex;align-items:center;gap:4px}
.jobf{border:1px solid var(--line);border-radius:var(--r);background:var(--panel)}
.jobf>summary{display:flex;align-items:center;gap:6px;padding:5px 10px;font-weight:600;font-size:12.5px}
.sb-job{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:4px 10px 10px}
.sb-job label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--mute);min-width:0}
.sb-job .wide{grid-column:1/-1}
.sb-job textarea{resize:vertical;min-height:72px;line-height:1.4}
.sb-job .go{grid-column:1/-1;display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.sb-flt{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.sb-flt select{max-width:22ch}.sb-flt input{flex:1 1 16ch;max-width:40ch}
.sb-cmp{display:grid;grid-template-columns:minmax(130px,230px) minmax(0,1fr) auto;gap:6px;align-items:start}
.sb-cmp select,.sb-cmp textarea{min-height:32px;padding:5px 8px;width:100%}
.sb-cmp textarea{resize:none;max-height:132px;line-height:1.4;display:block}
.sb-cmp .def{min-height:32px;padding:4px 14px}
.sb-cs,.sb-qn{font-size:12px;color:var(--mute);min-height:16px;overflow-wrap:anywhere}
/* the board: six columns, each scrolling on its own */
.sb-tabs{display:none}
.sb-cols{display:grid;grid-template-columns:repeat(6,minmax(176px,1fr));gap:8px;align-items:start;min-width:0}
.sb-body{overflow-x:auto}
.col{background:var(--hover);border:1px solid var(--line);border-radius:10px;min-width:0;display:flex;flex-direction:column}
.col.over{outline:2px dashed var(--acc);outline-offset:-2px}
.colh{display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;padding:8px 8px 4px;min-height:34px}
.colh .n{font-size:12px;color:var(--mute);font-weight:600}
.colh .sub{flex-basis:100%;font-size:11.5px;color:var(--mute)}
.sb .colh button{font-size:11.5px;padding:1px 7px;min-height:22px;margin-left:auto;display:inline-flex;gap:4px;align-items:center}
.cards{padding:2px 6px 8px;max-height:calc(100vh - var(--headh,200px) - 64px);overflow-y:auto;min-height:48px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:7px 8px;margin:0 0 6px;cursor:pointer;min-width:0;position:relative}
.card:hover{border-color:var(--mute)}
.card.sel{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.card.alert{box-shadow:inset 3px 0 var(--bad)}
.card.calm{opacity:.75}
.card[draggable=true]{cursor:grab}.card.drag{opacity:.4}.card.over{box-shadow:0 -3px 0 var(--acc)}
.card .top{display:flex;gap:6px;align-items:flex-start;min-width:0}
.card .t{font-weight:600;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;min-width:0;flex:1}
.card .meta{display:flex;flex-wrap:wrap;gap:3px 6px;align-items:center;font-size:11.5px;color:var(--mute);margin-top:3px;min-width:0}
.card .step{font-size:12px;color:var(--mute);margin-top:3px;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden}
.card .why{font-size:12px;margin-top:3px;overflow-wrap:anywhere}
.card .acts{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}
.sb .card .acts button{font-size:11.5px;padding:1px 7px;min-height:24px;display:inline-flex;gap:4px;align-items:center}
.sb .card button.ib{width:26px;height:24px;min-height:0;padding:0;display:inline-flex;align-items:center;justify-content:center;color:var(--mute);border-color:transparent;background:none;flex:none}
.sb .card button.ib:hover{border-color:var(--line);color:var(--acc)}
.chip{display:inline-flex;align-items:center;gap:3px;font-size:11.5px;padding:0 6px;border-radius:99px;border:1px solid var(--line);white-space:nowrap;max-width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;line-height:18px;background:var(--panel)}
.sb button.chip{min-height:0;padding:0 6px;font-size:11.5px;border-radius:99px;max-width:22ch;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:inline-block}
.sb button.chip.sel{border-color:var(--acc);color:var(--acc);background:var(--accbg)}
.chip.bad{border-color:var(--bad);color:var(--bad)}.chip.ok{color:var(--ok)}
.chip.warn{border-color:var(--warn);color:var(--warn);background:var(--warnbg);font-weight:600}
.chip.acc{border-color:var(--acc);color:var(--acc)}
.chip.msg{border-style:dashed;color:var(--acc);max-width:30ch}
.chip.msg span{overflow:hidden;text-overflow:ellipsis}
.sb .chip.msg button{min-height:0;padding:0 2px;border:0;background:none;color:inherit;font-size:13px;line-height:1}
.kids{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px;min-width:0}
.pips{display:inline-flex;gap:2px;align-items:center}
.pips i{width:6px;height:10px;border-radius:2px;border:1.5px solid var(--mute)}
.pips i.on{background:var(--ok);border-color:var(--ok)}.pips i.now{height:13px;border:2px solid var(--acc)}
.bar{display:inline-block;width:48px;height:6px;border-radius:3px;background:var(--line);overflow:hidden;vertical-align:middle}.bar i{display:block;height:100%;background:var(--ok)}
.stc{font-size:11px;padding:0 6px;border-radius:99px;border:1px solid var(--line);white-space:nowrap;line-height:17px;color:var(--mute)}
.stc.ready{border-color:var(--ok);color:var(--ok)}.stc.blocked{border-color:var(--warn);color:var(--warn)}
.stc.waits{border-color:var(--acc);color:var(--acc)}.stc.ended{border-color:var(--bad);color:var(--bad)}
.grp>summary{display:flex;align-items:center;gap:6px;padding:5px 2px;font-weight:650;font-size:12.5px;min-width:0}
.grp .grp>summary{font-weight:600;font-size:12px;color:var(--mute);padding-left:8px}
.grp .grp>.card{margin-left:8px}
.sb details.grp>summary::before,.sb details.more>summary::before,.sb details.cks>summary::before{content:"";flex:none;width:6px;height:6px;border-right:1.5px solid var(--mute);border-bottom:1.5px solid var(--mute);transform:rotate(-45deg);margin:0 3px 0 1px;transition:transform .12s}
.sb details[open].grp>summary::before,.sb details[open].more>summary::before,.sb details[open].cks>summary::before{transform:rotate(45deg)}
.more>summary{display:flex;align-items:center;gap:4px;font-size:12px;color:var(--mute);padding:4px 2px}
.empty{padding:10px 4px;color:var(--mute);font-size:12px}
.menu{position:relative;flex:none}
.menu>summary{width:26px;height:24px;display:inline-flex;align-items:center;justify-content:center;border-radius:6px;color:var(--mute)}
.menu>summary:hover,.menu[open]>summary{background:var(--hover);color:var(--acc)}
.mnl{position:absolute;right:0;top:26px;z-index:4;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:4px;display:flex;flex-direction:column;gap:2px;min-width:150px;box-shadow:0 4px 14px rgba(0,0,0,.12)}
.sb .mnl button{border-color:transparent;font-size:12.5px;display:flex;gap:6px;align-items:center}
.sb .mnl button:hover:not(:disabled){background:var(--hover)}
.cks>summary{font-size:11.5px;color:var(--mute);padding:2px 0;display:flex;align-items:center;gap:2px}
.ck{display:flex;gap:6px;align-items:center;font-size:12px;min-width:0;flex-wrap:wrap}.ck code{overflow-wrap:anywhere;min-width:0}
.sb pre{margin:0 0 4px;padding:4px 6px;font:11px/1.4 var(--mono,ui-monospace,monospace);color:var(--mute);white-space:pre-wrap;overflow-wrap:anywhere;background:var(--hover);border-radius:6px;max-height:240px;overflow:auto}
.lk{display:inline-flex;flex-wrap:wrap;gap:8px;font-size:11.5px}
/* questions */
.qq{overflow-wrap:anywhere;margin-top:2px}
.opts{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.sb .opts button small{font-size:11px;opacity:.85}
.qs{margin-top:4px;display:flex;flex-wrap:wrap;gap:4px 10px;font-size:12px;color:var(--mute)}
.qs .soon{color:var(--warn);font-weight:600}
.cdw{display:inline-flex;align-items:center;gap:3px}
/* the side panel */
.sb-panel{position:fixed;top:0;right:0;bottom:0;width:min(460px,100vw);background:var(--panel);border-left:1px solid var(--line);box-shadow:-6px 0 24px rgba(0,0,0,.14);z-index:20;overflow-y:auto;padding:0 16px 24px}
.pnh{position:sticky;top:0;background:var(--panel);display:flex;align-items:center;gap:8px;padding:10px 0 6px;z-index:1}
.pnh .grow{flex:1}
.sb .pnh button{display:inline-flex;align-items:center;gap:4px}
.sb-panel .ptitle{font-size:15px;font-weight:650;overflow-wrap:anywhere;margin:2px 0 4px}
.sb-panel p,.sb-panel ul{margin:0 0 4px;overflow-wrap:anywhere}
.sb-panel ul{padding-left:18px}
.sb-panel .txt{white-space:pre-wrap;overflow-wrap:anywhere}
.sb-panel code{font:12px var(--mono,ui-monospace,monospace);overflow-wrap:anywhere}
.tr{border-top:1px solid var(--line);padding:5px 0}
.pa{border-top:1px solid var(--line);padding:8px 0;display:flex;flex-direction:column;gap:5px}
.pa label{font-size:12px;color:var(--mute);display:flex;flex-direction:column;gap:3px}
.pa .row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.pa .row>input,.pa .row>select{flex:1 1 12ch}
.pa textarea{min-height:56px;resize:vertical;width:100%}
.cf{background:var(--warnbg);border:1px solid var(--warn);border-radius:8px;padding:6px 8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.cf span{flex-basis:100%;overflow-wrap:anywhere}
.pl{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;padding:3px 0;font-size:12px}
@media(max-width:1100px){.sb-cols{grid-template-columns:repeat(6,minmax(200px,1fr))}}
/* the phone: the same board, one column at a time */
@media(max-width:699px){
  .sb-stats{flex-basis:100%;order:3}
  .pill{white-space:normal;max-width:100%;min-width:0;overflow-wrap:anywhere}
  .sb-cmp{grid-template-columns:minmax(0,1fr) auto}.sb-cmp select{grid-column:1/-1}
  .sb-flt select{flex:1 1 40%;max-width:none}.sb-flt input{flex-basis:100%;max-width:none}
  .sb-head{position:static}
  .sb-ctl{gap:6px 10px}
  .sb-job{grid-template-columns:minmax(0,1fr)}
  .sb-tabs{display:flex;gap:4px;overflow-x:auto;padding:6px 0 8px;scrollbar-width:none;position:sticky;top:0;z-index:5;background:var(--bg)}
  .sb .sb-tabs button{flex:none;border-radius:99px;font-size:12.5px;padding:3px 10px;min-height:32px;white-space:nowrap}
  .sb .sb-tabs button[aria-selected=true]{background:var(--acc);border-color:var(--acc);color:var(--onacc)}
  .sb-body{overflow-x:visible}
  .sb-cols{display:block}
  .sb .col{display:none;border-radius:8px}
  .sb .col.on{display:flex}
  .cards{max-height:none;overflow:visible}
  .sb .card .acts button,.sb .opts button{min-height:36px}
  .opts button{flex:1 1 100%}
  .sb-panel{width:100vw;border-left:0;padding:0 12px 24px}
}`;

// Tabler Icons (tabler.io), MIT licence: the outline set's path data, drawn by svg() below
const ICON = {
  'arrow-back-up': ['M9 14l-4 -4l4 -4', 'M5 10h11a4 4 0 1 1 0 8h-1'],
  dots: ['M4 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0', 'M11 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0', 'M18 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0'],
  'external-link': ['M12 6h-6a2 2 0 0 0 -2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-6', 'M11 13l9 -9', 'M15 4h5v5'],
  eye: ['M10 12a2 2 0 1 0 4 0a2 2 0 0 0 -4 0', 'M21 12c-2.4 4 -5.4 6 -9 6c-3.6 0 -6.6 -2 -9 -6c2.4 -4 5.4 -6 9 -6c3.6 0 6.6 2 9 6'],
  refresh: ['M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4', 'M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4'],
  user: ['M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0', 'M6 21v-2a4 4 0 0 1 4 -4h4a4 4 0 0 1 4 4v2'],
  'alert-triangle': ['M12 9v4', 'M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0', 'M12 16h.01'],
  ban: ['M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0', 'M5.7 5.7l12.6 12.6'],
  bell: ['M10 5a2 2 0 1 1 4 0a7 7 0 0 1 4 6v3a4 4 0 0 0 2 3h-16a4 4 0 0 0 2 -3v-3a7 7 0 0 1 4 -6', 'M9 17v1a3 3 0 0 0 6 0v-1'],
  check: ['M5 12l5 5l10 -10'],
  'chevron-up': ['M6 15l6 -6l6 6'],
  'chevron-down': ['M6 9l6 6l6 -6'],
  'circle-check': ['M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0', 'M9 12l2 2l4 -4'],
  clock: ['M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0', 'M12 7v5l3 3'],
  'device-gamepad-2': ['M12 5h3.5a5 5 0 0 1 0 10h-5.5l-4.015 4.227a2.3 2.3 0 0 1 -3.923 -2.035l1.634 -8.173a5 5 0 0 1 4.904 -4.019h3.4', 'M14 15l4.07 4.284a2.3 2.3 0 0 0 3.925 -2.023l-1.6 -8.232', 'M8 9v2', 'M7 10h2', 'M14 10h2'],
  'file-text': ['M14 3v4a1 1 0 0 0 1 1h4', 'M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2', 'M9 9l1 0', 'M9 13l6 0', 'M9 17l6 0'],
  flask: ['M9 3l6 0', 'M10 9l4 0', 'M10 3v6l-4 11a.7 .7 0 0 0 .5 1h11a.7 .7 0 0 0 .5 -1l-4 -11v-6'],
  'git-branch': ['M5 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0', 'M5 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0', 'M15 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0', 'M7 8l0 8', 'M9 18h6a2 2 0 0 0 2 -2v-5', 'M14 14l3 -3l3 3'],
  'git-commit': ['M9 12a3 3 0 1 0 6 0a3 3 0 1 0 -6 0', 'M12 3l0 6', 'M12 15l0 6'],
  hammer: ['M11.414 10l-7.383 7.418a2.091 2.091 0 0 0 0 2.967a2.11 2.11 0 0 0 2.976 0l7.407 -7.385', 'M18.121 15.293l2.586 -2.586a1 1 0 0 0 0 -1.414l-7.586 -7.586a1 1 0 0 0 -1.414 0l-2.586 2.586a1 1 0 0 0 0 1.414l7.586 7.586a1 1 0 0 0 1.414 0'],
  'help-circle': ['M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0', 'M12 16v.01', 'M12 13a2 2 0 0 0 .914 -3.782a1.98 1.98 0 0 0 -2.414 .483'],
  'list-numbers': ['M11 6h9', 'M11 12h9', 'M12 18h8', 'M4 16a2 2 0 1 1 4 0c0 .591 -.5 1 -1 1.5l-3 2.5h4', 'M6 10v-6l-2 2'],
  'loader-2': ['M12 3a9 9 0 1 0 9 9'],
  lock: ['M5 13a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v6a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2v-6', 'M11 16a1 1 0 1 0 2 0a1 1 0 0 0 -2 0', 'M8 11v-4a4 4 0 1 1 8 0v4'],
  mail: ['M3 7a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v10a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-10', 'M3 7l9 6l9 -6'],
  message: ['M8 9h8', 'M8 13h6', 'M18 4a3 3 0 0 1 3 3v8a3 3 0 0 1 -3 3h-5l-5 3v-3h-2a3 3 0 0 1 -3 -3v-8a3 3 0 0 1 3 -3h12'],
  pencil: ['M4 20h4l10.5 -10.5a2.828 2.828 0 1 0 -4 -4l-10.5 10.5v4', 'M13.5 6.5l4 4'],
  'player-pause': ['M6 6a1 1 0 0 1 1 -1h2a1 1 0 0 1 1 1v12a1 1 0 0 1 -1 1h-2a1 1 0 0 1 -1 -1l0 -12', 'M14 6a1 1 0 0 1 1 -1h2a1 1 0 0 1 1 1v12a1 1 0 0 1 -1 1h-2a1 1 0 0 1 -1 -1l0 -12'],
  'player-play': ['M7 4v16l13 -8l-13 -8'],
  robot: ['M6 6a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v4a2 2 0 0 1 -2 2h-8a2 2 0 0 1 -2 -2l0 -4', 'M12 2v2', 'M9 12v9', 'M15 12v9', 'M5 16l4 -2', 'M15 14l4 2', 'M9 18h6', 'M10 8v.01', 'M14 8v.01'],
  search: ['M3 10a7 7 0 1 0 14 0a7 7 0 1 0 -14 0', 'M21 21l-6 -6'],
  server: ['M3 7a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v2a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3v-2', 'M3 15a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v2a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3l0 -2', 'M7 8l0 .01', 'M7 16l0 .01'],
  'terminal-2': ['M8 9l3 3l-3 3', 'M13 15l3 0', 'M3 6a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2l0 -12'],
  ticket: ['M15 5l0 2', 'M15 11l0 2', 'M15 17l0 2', 'M5 5h14a2 2 0 0 1 2 2v3a2 2 0 0 0 0 4v3a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-3a2 2 0 0 0 0 -4v-3a2 2 0 0 1 2 -2'],
  tool: ['M7 10h3v-3l-3.5 -3.5a6 6 0 0 1 8 8l6 6a2 2 0 0 1 -3 3l-6 -6a6 6 0 0 1 -8 -8l3.5 3.5'],
  world: ['M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0', 'M3.6 9h16.8', 'M3.6 15h16.8', 'M11.5 3a17 17 0 0 0 0 18', 'M12.5 3a17 17 0 0 1 0 18'],
  x: ['M18 6l-12 12', 'M6 6l12 12'],
  zzz: ['M4 12h6l-6 8h6', 'M14 4h6l-6 8h6']
};
const svg = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${(Object.prototype.hasOwnProperty.call(ICON, n) ? ICON[n] : []).map(d => `<path d="${d}"/>`).join('')}</svg>`;

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = n => Number.isFinite(+n) ? +n : 0;
const own = (o, k) => o && typeof o == 'object' && typeof k == 'string' && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined;
const dur = s => { s = Math.max(0, Math.floor(s)); return s < 60 ? s + 's' : s < 3600 ? Math.floor(s / 60) + 'm' : s < 86400 ? Math.floor(s / 3600) + 'h' : Math.floor(s / 86400) + 'd'; };
const ago = (now, t) => dur(now - num(t)) + ' ago';
const plural = (n, w, ws) => n + ' ' + (n == 1 ? w : ws || w + 's');
const short = id => String(id ?? '').slice(0, 6);
const proj = p => String(p || '').split('/').filter(Boolean).pop() || '';
const hm = sec => new Date(num(sec) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
// state: [icon, word, colour]; a needs-you bell and a your-turn speech bubble do not read as the same thing
const ST = {working: ['loader-2', 'working', 'acc spin'], done: ['circle-check', 'done', 'ok'], blocked: ['ban', 'blocked', 'bad'],
  'needs you': ['bell', 'needs you', 'bad'], 'your turn': ['message', 'your turn', 'acc'], waiting: ['player-pause', 'waiting', ''], idle: ['zzz', 'idle', '']};
const RANK = {'needs you': 0, blocked: 0, 'your turn': 1, working: 2, waiting: 2, idle: 3, done: 4};
const rank = a => own(RANK, a.state) ?? 2;
const TOOL = {Bash: 'terminal-2', run_command: 'terminal-2', Read: 'file-text', read_file: 'file-text', view_file: 'file-text',
  Edit: 'pencil', edit_file: 'pencil', Write: 'pencil', write_file: 'pencil', Grep: 'search', grep_search: 'search', Glob: 'search',
  Agent: 'robot', Task: 'robot', invoke_subagent: 'robot', WebFetch: 'world', WebSearch: 'world', search_web: 'world'};
const dot = lv => `<i class="dot ${lv == 'ok' || lv == 'warn' || lv == 'bad' ? lv : ''}" aria-hidden="true"></i>`;
const PICON = {git: 'git-branch', tests: 'flask', unity: 'device-gamepad-2', build: 'hammer', server: 'server'};
const HOW = {PostToolUse: 'mid-turn', Stop: 'at the end of its turn', SubagentStop: 'at the end of its run', UserPromptSubmit: 'with your next prompt'};
// what a session is doing: [icon name or '', text]
const act = a => { const m = /^(\w+)(?:: ?(.*))?$/.exec(a.note || ''); return m && own(TOOL, m[1]) ? [TOOL[m[1]], m[2] || m[1]] : ['', a.note || '']; };
const tnum = t => /^\d+$/.test(String(t)) ? 'ticket ' + t : String(t);
// one label for an agent everywhere: title, else ticket, else name, else a short id (raw text: esc it where used)
const lbl = a => String(a.title || (a.ticket ? tnum(a.ticket) : '') || a.name || short(a.agent));
const stOf = st => own(ST, st) || ['help-circle', String(st || 'unknown'), ''];
const stIc = st => { const [g, w, c] = stOf(st); return `<span class="ic ${c}" role="img" aria-label="${esc(w)}" title="${esc(w)}">${svg(g)}</span>`; };
const icon = (n, label, c) => `<span class="ic ${c || ''}" role="img" aria-label="${esc(label)}" title="${esc(label)}">${svg(n)}</span>`;
const store = () => { try { return window.localStorage; } catch (e) { return null; } };
const loadSet = k => { try { return new Set(JSON.parse(store().getItem(k) || '[]')); } catch (e) { return new Set(); } };
const saveSet = (k, s) => { try { store().setItem(k, JSON.stringify([...s])); } catch (e) { /* private window: per view only */ } };
// when a queued message lands, by the receiver's state
const whenFor = a => !a ? '' : a.state == 'working' ? 'Delivers after its next tool call.'
  : a.state == 'done' ? 'It has finished; it will not read this.'
  : rank(a) == 0 ? 'Delivers once it continues.'
  : 'It is idle: delivers when its next turn starts.';

// ---- the queue's words ----
const EST = 5400;  // a ticket's estimate: 1.5 h
const tkey = t => String(t.map) + '#' + parseInt(t.num, 10);
// a map's wayfinder project, as the hub names it: the folder prefix, else the name before a dash
const projOf = m => { const p = String(m || '').split('/'); return p.length > 1 ? p[0] : p[0].split('-')[0]; };
const ENDED = {done: ['circle-check', 'done', 'ok'], failed: ['x', 'failed', 'bad'], skipped: ['ban', 'skipped', 'warn']};
const firstLine = t => String(t || '').split('\n').map(x => x.trim()).find(Boolean) || '';
const agyWords = 'Antigravity: emergencies and mechanical work';

const WEEK = 7 * 86400;  // Done shows what ended in the last 7 days; older ones stay in the vault
const COLS = [['needs', 'Needs you'], ['ready', 'Ready'], ['queued', 'Queued'], ['running', 'Running'], ['done', 'Done'], ['failed', 'Failed']];
const COLNAME = Object.fromEntries(COLS);
const TABS = ['needs', 'queued', 'running', 'done', 'failed', 'ready'];  // the phone's order
// a side-panel action: [button, what the confirmation says it does, the yes button]
const ACTS = {done: ['Done…', 'Mark it done with this line', 'Yes, mark it done'], drop: ['Drop…', 'Drop it, out of scope, with this reason', 'Yes, drop it'],
  release: ['Release the claim…', 'Release the claim: it goes back to open', 'Yes, release it'], comment: ['Comment…', 'Add this comment', 'Yes, add it'],
  tier: ['Set the tier…', 'Run it on this tier', 'Yes, set it'], checks: ["Set the map's checks…", "Set its map's checks (every ticket of the map)", 'Yes, set them']};
const obs = u => /^obsidian:\/\//.test(String(u || '')) ? String(u) : '';
// the worker's own self-checks from its report (## Self-checks), else the copy the hub keeps under its checks
function selfChecksOf(text) {
  const ls = String(text || '').split('\n'), out = []; let on = false;
  for (const l of ls) {
    if (!on) { on = /^#{2,3} (Self-checks|The worker's self-checks)/.test(l); continue; }
    if (/^#{1,3} /.test(l)) break;
    out.push(l);
  }
  return out.join('\n').trim();
}
const readHash = () => { let p; try { p = new URLSearchParams(location.hash.slice(1)); } catch (e) { p = new URLSearchParams(); }
  return {p: p.get('p') || '', m: p.get('m') || '', q: p.get('q') || '', t: p.get('t') || '', c: p.get('c') || ''}; };
const loadObj = k => { try { const o = JSON.parse(store().getItem(k) || '{}'); return o && typeof o == 'object' ? o : {}; } catch (e) { return {}; } };
const saveObj = (k, o) => { try { store().setItem(k, JSON.stringify(o)); } catch (e) { /* private window: per view only */ } };

window.SBBoard = function (root, io) {
  if (!document.getElementById('sb-css')) {
    const st = document.createElement('style'); st.id = 'sb-css'; st.textContent = STYLE; document.head.appendChild(st);
  }
  root.classList.add('sb', 'page');
  const RO = !!io.readonly, hasQ = typeof io.queue == 'function', canQ = hasQ && !RO, canAct = typeof io.act == 'function', canGet = typeof io.get == 'function';
  root.innerHTML = `<div class="sb-head">
<div class="sb-bar"><span class="sb-brand">sb hub</span><span class="sb-live off"><i></i><span>connecting</span></span>${RO ? `<span class="pill" title="This page shows the board only. It can clear finished items and quiet sessions, nothing else.">${svg('eye')} read-only</span>` : ''}<span class="sb-stats" data-region="strip"></span></div>
<div class="sb-banner" role="alert" hidden></div>${canQ ? `
<div class="sb-ctl" data-region="ctl"></div>
<details class="jobf" data-k="jobform"><summary>${svg('terminal-2')} New job <span class="mute">a one-off prompt, run headless like a ticket</span></summary>
<form class="sb-job" autocomplete="off">
<label class="wide">Project<input name="project" list="sb-projects" required maxlength="500" placeholder="a wayfinder project or a path to a git checkout, e.g. sb-workflow or /Users/me/code/app"></label>
<datalist id="sb-projects"></datalist>
<label class="wide">Prompt<textarea name="prompt" rows="4" required maxlength="20000" placeholder="What the agent should do; it runs alone, with no one to ask"></textarea></label>
<label>Agent<select name="agent"></select></label>
<label>Model<input name="model" maxlength="80" placeholder="optional, e.g. opus"></label>
<label>Name<input name="name" maxlength="80" placeholder="optional; names its run folder"></label>
<label>Not before<input name="at" type="time" title="optional: the job never starts before this time"></label>
<div class="go"><button type="submit" class="def">Queue the job</button><span class="sb-jn mute" aria-live="polite"></span></div>
</form></details>` : ''}
<div class="sb-flt"><select data-f="p" aria-label="Project"><option value="">Every project</option></select><select data-f="m" aria-label="Map"><option value="">Every map</option></select><input type="search" data-f="q" maxlength="200" placeholder="Find a ticket by its title" aria-label="Find a ticket by its title"></div>${RO ? '' : `
<form class="sb-cmp" autocomplete="off"><select class="sb-to" aria-label="Send to"><option value="">To…</option></select><textarea class="sb-msg" rows="1" maxlength="4000" aria-label="Message" placeholder="Message a session or worker · Enter sends"></textarea><button type="submit" class="def">Send</button></form>
<div class="sb-cs" aria-live="polite"></div>`}
<div class="sb-qn" aria-live="polite"></div></div>
<div class="sb-tabs" role="tablist" aria-label="Columns" data-region="tabs"></div>
<div class="sb-body"><div class="sb-cols">${COLS.map(([k]) => `<section class="col" data-col="${k}" aria-label="${esc(COLNAME[k])}"><header class="colh" data-region="h-${k}"></header><div class="cards" data-region="${k}"></div></section>`).join('')}</div></div>
<aside class="sb-panel" hidden aria-label="Details"><div class="pnh"><span class="grow"></span><button type="button" data-close="1" aria-label="Close the panel">${svg('x')} Close</button></div><div data-region="pinfo"></div><div data-region="pact"></div></aside>`;
  const $ = c => root.querySelector(c);
  const head = $('.sb-head'), body = $('.sb-body'), panel = $('.sb-panel'), qn = $('.sb-qn');
  const sel = $('.sb-to'), msg = $('.sb-msg'), cs = $('.sb-cs'), form = $('.sb-cmp');
  const fP = $('[data-f=p]'), fM = $('[data-f=m]'), fQ = $('[data-f=q]');
  const job = $('.sb-job'), jn = $('.sb-jn');
  const R = {}; root.querySelectorAll('[data-region]').forEach(el => { R[el.dataset.region] = el; });
  const sending = {}, fails = {}, lastH = {}, dirty = new Set(), opened = new Set(), DT = new Map(), selfCk = new Map();
  const groups = loadObj('sbhub.groups');
  const F = readHash();
  let S = null, O = {}, gotAt = 0, csNote = null, deferred = false, qbusy = false, qnote = null, drag = null, tab = F.c;
  let P = F.t ? (F.t.startsWith('p:') ? {kind: 'project', key: F.t.slice(2)} : {kind: 'ticket', key: F.t}) : null;
  let pend = null, pbusy = false, pnote = null;
  fQ.value = F.q;

  const agentOf = id => { if (!S || typeof id != 'string') return null; return own(S.agents, own(S.aliases, id) || id) || null; };
  const who = id => { const a = agentOf(id); return a ? lbl(a) : short(id); };
  const whereOf = id => { const a = agentOf(id); return a ? proj(a.project) : ''; };
  const target = id => {
    if (!sel) return;
    sel.value = [...sel.options].some(o => o.value === id) ? id : '';
    csNote = null; hint();
    root.querySelectorAll('[data-row]').forEach(r => r.classList.toggle('sel', r.dataset.row === sel.value));
    root.querySelectorAll('button.chip[data-to]').forEach(b => b.classList.toggle('sel', b.dataset.to === sel.value));
  };

  // ---- the queue and the tickets, read from S and the ticket rows ----
  const Q = () => (S && S.queue && typeof S.queue == 'object') ? S.queue : null;
  const items = () => { const q = Q(); return q && Array.isArray(q.items) ? q.items.filter(i => i && typeof i == 'object') : []; };
  const cleared = () => { const q = Q(); return q && Array.isArray(q.cleared) ? q.cleared.filter(i => i && typeof i == 'object') : []; };
  const installed = () => Object.entries((S && S.installed && typeof S.installed == 'object') ? S.installed : {}).filter(([, e]) => e && typeof e == 'object');
  const tickets = () => Array.isArray(O.tickets) ? O.tickets.filter(t => t && typeof t == 'object') : null;
  let byKey = new Map();
  const tOf = k => byKey.get(k) || null;
  // a title, never a bare id: the ticket's own, else what the hub stored, else its map and number
  function titleOf(i) {
    const t = tOf(i.key);
    if (t) return String(t.title);
    if (i.title) return String(i.title);
    if (i.kind == 'job') return String(i.name || 'job');
    const m = /^(.*)#(\d+)$/.exec(String(i.key)); return m ? `${m[1]} ticket ${m[2]}` : String(i.key);
  }
  const projItem = i => { const t = tOf(i.key); return i.kind == 'job' ? proj(i.project) || String(i.project || '') : t ? projOf(t.map) : projOf(String(i.key).split('#')[0]); };
  const mapItem = i => i.kind == 'job' ? '' : String(i.key).replace(/#\d+$/, '');
  const itemOf = k => items().find(i => i.key === k) || cleared().filter(i => i.key === k).pop() || null;
  const blockersOf = t => (Array.isArray(t.blocked_by_open) ? t.blocked_by_open : []).map(b => typeof b == 'number' ? String(t.map) + '#' + b : null);
  const bTitle = (t, b) => { const k = typeof b == 'number' ? String(t.map) + '#' + b : null, o = k && tOf(k); return o ? String(o.title) : typeof b == 'number' ? 'ticket ' + b : String(b); };
  const poolOf = () => { const q = Q(); return !q ? [] : Array.isArray(q.agents) && q.agents.length ? q.agents.map(String) : q.agent ? [String(q.agent)] : []; };
  const poolWord = () => { const p = poolOf(); return p.length ? `tonight's agents (${p.join(', ')})` : "tonight's agents"; };
  const liveKeys = () => new Set(items().filter(i => i.state == 'queued' || i.state == 'running').map(i => i.key));
  const queuedTickets = () => items().filter(i => i.kind == 'ticket' && i.state == 'queued').map(i => i.key);
  const want = (pj, map, title) => (!F.p || pj === F.p) && (!F.m || map === F.m) && (!F.q || String(title).toLowerCase().includes(F.q.toLowerCase()));
  const wantI = i => want(projItem(i), mapItem(i), titleOf(i));
  // the worker's report and log, served read-only by the hub
  const fileLinks = i => [i.kind == 'ticket' ? i.run && 'report' : i.result && 'report', i.log && 'log'].filter(Boolean)
    .map(w => `<a href="${esc('api/item/' + w + '?key=' + encodeURIComponent(i.key))}" target="_blank" rel="noopener">${w == 'log' ? "worker's log" : "worker's report"}</a>`).join('');
  function checksOf(i, open) {
    const cs = Array.isArray(i.checks) ? i.checks.filter(c => c && typeof c == 'object') : [];
    if (!cs.length) return '';
    const bad = cs.filter(c => c.code !== 0).length, k = 'ck:' + i.key + (open ? ':p' : '');
    return `<details class="cks" data-k="${esc(k)}"${open || opened.has(k) ? ' open' : ''}><summary data-key="${esc('d:' + k)}">${bad ? `<span class="err">${bad} of ${plural(cs.length, 'check')} failed</span>` : `<span class="okc">${plural(cs.length, 'check')} passed</span>`}</summary>`
      + cs.map(c => `<div class="ck">${c.code === 0 ? icon('circle-check', 'passed', 'ok') : icon('x', 'failed', 'bad')}<code dir="ltr">${esc(c.cmd)}</code><span class="mute">${c.code == null ? 'timed out' : 'exit ' + esc(c.code)} · ${esc(num(c.secs))} s</span></div>${c.tail ? `<pre>${esc(c.tail)}</pre>` : ''}`).join('')
      + '</details>';
  }
  function selfOf(i, open) {
    if (i.kind != 'ticket' || !i.run) return '';
    const k = 'sc:' + i.key + (open ? ':p' : ''), v = selfCk.get(i.key);
    return `<details class="cks" data-k="${esc(k)}" data-self="${esc(i.key)}"${open || opened.has(k) ? ' open' : ''}><summary data-key="${esc('d:' + k)}">Self-checks</summary>${v == null ? (selfCk.has(i.key) ? '<div class="mute">Reading the report…</div>' : '') : `<pre>${esc(v)}</pre>`}</details>`;
  }
  function agentState(name, e) {
    if (e.login == 'expired') return ['out', 'signed out'];
    const run = items().find(i => i.state == 'running' && i.runner === name);
    if (run) return ['run', 'running ' + titleOf(run)];
    if (num(e.limited_until) > S.now) return ['lim', 'limited until ' + hm(e.limited_until)];
    return ['', 'signed in'];
  }
  // an account's 5-hour use and reset, and what it learned a ticket costs, from the hub's readings
  const usageOf = e => { const u = e.usage && typeof e.usage == 'object' ? e.usage : null; return u && num(u.five_hour_resets) > S.now ? `${Math.round(100 * num(u.five_hour))}% · resets ${hm(u.five_hour_resets)}` : ''; };
  const costsOf = e => Object.entries(e.costs && typeof e.costs == 'object' ? e.costs : {}).filter(([, c]) => c && typeof c == 'object').map(([t, c]) => `${t} about ${Math.round(100 * num(c.avg))}%`).join(', ');
  // when the queue should end: each repo runs its items one after another, repos side by side, and all of
  // them share the accounts' worker slots (roughly: 2 for an account with a learned cost, else 1)
  function ends() {
    const live = items().filter(i => i.state == 'running' || i.state == 'queued');
    if (!live.length) return 0;
    const by = new Map();
    for (const i of live) { const t = tOf(i.key), r = i.repo || (t && t.repo) || projItem(i) || i.key; if (!by.has(r)) by.set(r, []); by.get(r).push(i); }
    let end = S.now;
    for (const list of by.values()) {
      const run = list.filter(i => i.state == 'running'), from = run.length ? Math.min(...run.map(i => num(i.started) || S.now)) : S.now;
      end = Math.max(end, from + EST * list.length);
    }
    const inst = S && S.installed && typeof S.installed == 'object' ? S.installed : {};
    const slots = poolOf().map(n => inst[n]).filter(e => e && typeof e == 'object' && e.login != 'expired')
      .reduce((n, e) => n + (e.costs && Object.keys(e.costs).length ? 2 : 1), 0);
    return Math.max(end, S.now + EST * live.filter(i => i.state == 'queued').length / Math.max(1, slots));
  }
  // can a ticket be queued: ready, or blocked by tickets that are queued or can be queued too
  const doneKeys = () => new Set(items().filter(i => i.kind == 'ticket' && i.state == 'done').map(i => i.key));
  function addable(t, seen) {
    if (doneKeys().has(tkey(t))) return false;
    if (t.state == 'ready') return true;
    if (t.state != 'blocked') return false;
    seen = seen || new Set([tkey(t)]);
    const live = liveKeys();
    return blockersOf(t).every(k => { if (!k) return false; if (live.has(k)) return true; const o = tOf(k);
      if (!o || seen.has(k)) return false; seen.add(k); return addable(o, seen); });
  }
  function withBlockers(k, out) {
    if (out.includes(k)) return out;
    const t = tOf(k), live = liveKeys();
    if (t) for (const b of blockersOf(t)) if (b && !live.has(b)) withBlockers(b, out);
    out.push(k); return out;
  }

  // ---- small pieces ----
  function prog(d, t) {
    const label = `${d} of ${t} tickets done`;
    if (t > 20) { const pc = Math.max(0, Math.min(100, 100 * d / t)); return `<span title="${esc(label)}"><span class="bar"><i style="width:${pc}%"></i></span> ${d}/${t}</span>`; }
    let h = ''; for (let i = 0; i < t; i++) h += `<i class="${i < d ? 'on' : i == d ? 'now' : ''}"></i>`;
    return `<span title="${esc(label)}"><span class="pips" role="img" aria-label="${esc(label)}">${h}</span> ${d}/${t}</span>`;
  }
  function kid(a) {
    const [ic] = act(a), [g, w] = stOf(a.state), c = rank(a) == 0 ? 'bad' : a.state == 'done' ? 'ok' : '';
    const tip = `${lbl(a)} · ${w} · ${a.note || ''} · active ${ago(S.now, a.at)}`;
    if (a.state == 'done' || RO) return `<span class="chip ${c}" dir="auto" title="${esc(tip)}"><span role="img" aria-label="${esc(w)}">${svg(g)}</span> ${esc(lbl(a))}</span>`;
    return `<button type="button" class="chip ${c}${sel && sel.value === a.agent ? ' sel' : ''}" data-to="${esc(a.agent)}" data-key="${esc('to:' + a.agent)}" dir="auto" title="${esc('Message this worker · ' + tip)}"><span role="img" aria-label="${esc(w)}">${svg(g)}</span> ${esc(lbl(a))}${ic ? ' ' + svg(ic) : ''}</button>`;
  }
  const queuedFor = id => Object.entries(S.messages || {}).filter(([, m]) => m && m.to === id && m.delivered == null && !m.lost);
  const qchip = ([mid, m]) => `<span class="chip msg" dir="auto" title="${esc('Queued ' + ago(S.now, m.at) + ': ' + m.text)}">${svg('mail')} <span>${esc(m.text)}</span>${RO ? '' : `<button type="button" data-unsend="${esc(mid)}" data-key="${esc('un:' + mid)}" aria-label="Take back this message" title="Take back">${svg('x')}</button>`}</span>`;
  function widget(w) {
    const label = esc(w.label);
    if (w.kind == 'status') return `<span class="chip" title="${label}">${dot(w.level)} ${esc(String(w.value).slice(0, 40))}</span>`;
    if (w.kind == 'progress') { const v = num(w.value), m = num(w.max), pc = Math.max(0, Math.min(100, 100 * v / (m || 1)));
      return `<span class="bar" title="${label} ${v}/${m}"><i style="width:${pc}%"></i></span><span class="mute">${v}/${m}</span>`; }
    if (w.kind == 'counts' && w.items && typeof w.items == 'object') return Object.entries(w.items).map(([k, v]) => `<span class="chip ${k == 'fail' && num(v) ? 'bad' : k == 'pass' ? 'ok' : ''}" title="${label}">${k == 'pass' ? `<span role="img" aria-label="passed">${svg('circle-check')}</span>` : k == 'fail' ? `<span role="img" aria-label="failed">${svg('x')}</span>` : esc(k)} ${esc(v)}</span>`).join('');
    return '';
  }
  const wlist = p => Array.isArray(p.widgets) ? p.widgets.filter(w => w && typeof w == 'object') : [];
  const provsOf = path => { const p = S && S.providers && own(S.providers, path); return Array.isArray(p) ? p.filter(x => x && typeof x == 'object') : []; };
  const worst = list => { let lv = 'ok'; for (const p of list) for (const w of wlist(p)) if (w.level == 'bad') lv = 'bad'; else if (w.level == 'warn' && lv != 'bad') lv = 'warn'; return lv; };
  const menu = (key, title, btns) => !btns.length ? '' : `<details class="menu" data-k="${esc('mn:' + key)}"><summary data-key="${esc('mn:' + key)}" aria-label="${esc('Actions: ' + title)}" title="Move it">${svg('dots')}</summary><div class="mnl">${btns.join('')}</div></details>`;
  const mbtn = (attr, key, label, ic, off) => `<button type="button" ${attr}="${esc(key)}" data-key="${esc(attr + ':' + key)}"${off ? ' disabled' : ''}>${svg(ic)} ${esc(label)}</button>`;
  const cardOpen = (key, extra, drag) => `<article class="card${P && P.key === key ? ' sel' : ''}${extra || ''}" data-open="${esc(key)}" data-key="${esc('card:' + key)}" tabindex="0"${drag ? ` draggable="true" data-drag="${drag}"` : ''}>`;

  // ---- the cards ----
  function ticketCard(t, off) {
    const key = tkey(t), st = String(t.state || ''), can = addable(t), meta = [];
    const cls = st == 'ready' ? 'ready' : st == 'blocked' ? 'blocked' : st == 'waits for you' ? 'waits' : '';
    meta.push(`<span class="one" title="${esc(t.map_title || t.map)}">${esc(projOf(t.map))} · ${esc(t.map_title || t.map)}</span>`);
    if (st != 'ready') meta.push(`<span class="stc ${cls}">${esc(st)}</span>`);
    const bs = (Array.isArray(t.blocked_by_open) ? t.blocked_by_open : []).map(b => bTitle(t, b));
    if (bs.length) meta.push(`<span dir="auto">after ${esc(bs.join(', '))}</span>`);
    else if (st == 'claimed' || st == 'not ready') meta.push(`<span dir="auto">${esc(t.reason)}</span>`);
    if (t.tier && t.tier != 'sonnet') meta.push(`<span class="chip" title="the model it runs on">${esc(t.tier)}</span>`);
    const e = items().concat(cleared()).filter(i => i.key === key && ENDED[i.state]).pop();
    if (e && e.state != 'done') meta.push(`<span class="stc ended" title="${esc(firstLine(e.note))}">${esc(e.state)} ${esc(ago(S.now, e.ended))}</span>`);
    const mn = canQ && can ? menu(key, t.title, [mbtn('data-add', key, 'Queue', 'list-numbers', off)]) : '';
    return cardOpen(key, '', canQ && can && !off ? 'add' : '') + `<div class="top"><span class="t" dir="auto">${esc(t.title)}</span>${mn}</div><div class="meta">${meta.join('')}</div></article>`;
  }
  function queuedCard(i, n, qt, off) {
    const t = tOf(i.key), title = titleOf(i), isT = i.kind == 'ticket', at = isT ? qt.indexOf(i.key) : -1, meta = [], pj = projItem(i);
    if (pj) meta.push(`<span class="one">${esc(pj)}</span>`);
    if (i.kind == 'job') meta.push(`<span class="one" dir="auto" title="${esc(i.prompt)}">${esc(firstLine(i.prompt))}</span>`);
    if (t) { const bs = (Array.isArray(t.blocked_by_open) ? t.blocked_by_open : []).map(b => bTitle(t, b)); if (bs.length) meta.push(`<span dir="auto">after ${esc(bs.join(', '))}</span>`); }
    const tier = i.model || (t && t.tier);
    if (tier) meta.push(`<span class="chip" title="the model it runs on">${esc(tier)}</span>`);
    if (i.agent) meta.push(`<span class="chip acc" title="this item's own agent">${svg('robot')} ${esc(i.agent)}</span>`);
    if (i.tries) meta.push(`<span class="chip warn">second try</span>`);
    if (i.not_before && num(i.not_before) > S.now) meta.push(`<span class="chip" title="a timed job">${svg('clock')} at ${esc(hm(i.not_before))}</span>`);
    if (i.note) meta.push(`<span class="one" dir="auto" title="${esc(i.note)}">${esc(firstLine(i.note))}</span>`);
    const btns = !canQ ? [] : isT ? [mbtn('data-up', i.key, 'Move up', 'chevron-up', off || at <= 0), mbtn('data-dn', i.key, 'Move down', 'chevron-down', off || at < 0 || at >= qt.length - 1), mbtn('data-back', i.key, 'Back to Ready', 'arrow-back-up', off)]
      : [mbtn('data-rmjob', i.key, 'Remove the job', 'x', off)];
    return cardOpen(i.key, '', canQ && isT && !off ? 'q' : '') + `<div class="top"><span class="mute" title="its place in the queue">${n}</span><span class="t" dir="auto">${esc(title)}</span>${menu(i.key, title, btns)}</div><div class="meta">${meta.join('')}</div></article>`;
  }
  function runningCard(i) {
    const a = agentOf(i.key), [ti, txt] = a ? act(a) : ['', ''], step = txt || firstLine(i.note) || 'starting', q = Q() || {}, pj = projItem(i), meta = [];
    if (pj) meta.push(`<span class="one">${esc(pj)}</span>`);
    meta.push(`<span class="chip acc" title="the account it runs on">${svg('robot')} ${esc(i.runner || i.agent || q.agent || '')} · ${esc(dur(S.now - num(i.started)))}</span>`);
    if (i.model) meta.push(`<span class="chip">${esc(i.model)}</span>`);
    const lk = fileLinks(i), mail = a && !RO ? `<button type="button" class="ib" data-to="${esc(i.key)}" data-key="${esc('to:' + i.key)}" aria-label="${esc('Message the worker on ' + titleOf(i))}" title="Message this worker">${svg('mail')}</button>` : '';
    return cardOpen(i.key) + `<div class="top">${icon('loader-2', 'running', 'acc spin')}<span class="t" dir="auto">${esc(titleOf(i))}</span>${mail}</div>`
      + `<div class="step" dir="auto" title="${esc(i.note || step)}">${ti ? svg(ti) + ' ' : ''}${esc(step)}</div><div class="meta">${meta.join('')}${lk ? `<span class="lk">${lk}</span>` : ''}</div></article>`;
  }
  function sessionCard(a, kids) {
    const id = a.agent, [ti, txt] = act(a), t = num(a.total), silent = S.now - num(a.at), name = lbl(a), pn = proj(a.project), meta = [];
    const turn = a.state == 'your turn' && a.asked, line = turn ? `You asked: “${a.asked}”` : txt;
    meta.push(`<span class="chip" title="a session you run by hand, not a queue worker">${svg('user')} yours</span>`);
    if (pn) meta.push(`<span class="one" title="${esc(a.project)}">${esc(pn)}</span>`);
    if (a.ticket && tnum(a.ticket) !== name) meta.push(`<span class="one" dir="auto" title="ticket: ${esc(a.ticket)}">${svg('ticket')} ${esc(tnum(a.ticket))}</span>`);
    if (t > 0) meta.push(prog(num(a.done), t));
    if (a.state == 'working' && silent >= 600) meta.push(`<span class="chip warn">${svg('alert-triangle')} quiet for ${esc(dur(silent))}</span>`);
    meta.push(`<span title="active ${esc(ago(S.now, a.at))}">${esc(dur(silent))}</span>`);
    const q = queuedFor(id), cls = (a.state == 'idle' || a.state == 'done' ? ' calm' : '') + (rank(a) == 0 ? ' alert' : '') + (sel && sel.value === id ? ' sel' : '');
    const btns = (RO ? '' : `<button type="button" class="ib" data-to="${esc(id)}" data-key="${esc('to:' + id)}" aria-label="${esc('Message ' + name)}" title="Message this session">${svg('mail')}</button>`)
      + (canAct ? `<button type="button" class="ib" data-dismiss="${esc(id)}" data-key="${esc('dm:' + id)}" aria-label="${esc('Dismiss ' + name)}" title="Dismiss: take it off the board; the session keeps running">${svg('x')}</button>` : '');
    return `<article class="card${cls}" data-row="${esc(id)}"><div class="top">${stIc(a.state)}<span class="t" dir="auto" title="${esc(name + (a.asked ? '\nYou asked: ' + a.asked : ''))}">${esc(name)}</span>${btns}</div>`
      + (line ? `<div class="step" dir="auto" title="${esc(line)}">${!turn && ti ? svg(ti) + ' ' : ''}${esc(line)}</div>` : '')
      + `<div class="meta">${meta.join('')}</div>`
      + (kids.length || q.length ? `<div class="kids">${kids.map(kid).join('')}${q.map(qchip).join('')}</div>` : '') + '</article>';
  }
  function endedCard(i, live) {
    const [g, w, c] = ENDED[i.state], pj = projItem(i), meta = [], isT = i.kind == 'ticket';
    if (pj) meta.push(`<span class="one">${esc(pj)}</span>`);
    meta.push(`<span title="${esc(w + ' at ' + hm(i.ended))}">${esc(w)} ${esc(ago(S.now, i.ended))}</span>`);
    if (i.state == 'done' && i.commit) meta.push(`<span class="chip ok" title="${esc(i.commit)}">${svg('git-commit')} ${esc(String(i.commit).slice(0, 9))}</span>`);
    const why = i.state == 'done' ? (i.kind == 'job' && i.result ? 'result in ' + i.result : '') : firstLine(i.note) || 'no reason recorded';
    const again = i.state != 'done' && isT && canQ && tOf(i.key) && !live.has(i.key) && !items().some(x => x.key === i.key && x.state == 'done')
      ? `<div class="acts"><button type="button" data-again="${esc(i.key)}" data-key="${esc('ag:' + i.key)}"${qbusy || O.down ? ' disabled' : ''}>${svg('refresh')} Tick again</button></div>` : '';
    const lk = fileLinks(i);
    return cardOpen(i.key) + `<div class="top">${icon(g, w, c)}<span class="t" dir="auto">${esc(titleOf(i))}</span></div><div class="meta">${meta.join('')}</div>`
      + (why ? `<div class="why${i.state == 'done' ? ' mute' : ''}" dir="auto">${esc(why)}</div>` : '')
      + checksOf(i) + selfOf(i) + (lk ? `<div class="lk">${lk}</div>` : '') + again + '</article>';
  }
  function questionCard(id, q) {
    const decided = q.answer != null, left = num(q.deadline) - S.now, pending = !decided && left <= 0, busy = own(sending, id);
    const off = RO || decided || pending || !!O.down || busy != null, pn = whereOf(q.agent);
    const btn = (o, i) => `<button type="button" data-q="${esc(id)}" data-i="${i}" data-key="${esc('q:' + id + ':' + i)}" class="${o == q.default && !RO ? 'def' : ''}${decided && o == q.answer ? ' chosen' : ''}"${off ? ' disabled' : ''} dir="auto">${busy === i ? 'Sending…' : (decided && o == q.answer ? svg('check') + ' ' : '') + esc(o)}${o == q.default ? '<small> · default</small>' : ''}</button>`;
    const status = decided ? `<span>${q.by == 'default' ? 'Default applied' : q.by == 'you' ? 'You chose this' : 'Chosen by ' + esc(q.by)}</span>`
      : pending ? '<span class="soon">deciding…</span>'
      : `<span class="cdw${left < 60 ? ' soon' : ''}" title="the default applies then">${svg('clock')}<span class="cd" data-dl="${num(q.deadline)}">${esc(dur(left))} left</span></span>`;
    return `<article class="card${decided ? ' calm' : ' alert'}" data-qr="${esc(id)}"><div class="top">${icon('help-circle', 'question', 'acc')}<span class="mute one"><b dir="auto">${esc(who(q.agent))}</b>${pn ? ' · ' + esc(pn) : ''} · asked ${esc(ago(S.now, q.asked))}</span></div>`
      + `<div class="qq" dir="auto">${esc(q.q)}</div><div class="opts">${(Array.isArray(q.options) ? q.options : []).map(btn).join('')}</div>`
      + `<div class="qs">${status}${!decided && own(fails, id) ? `<span class="err" role="alert">Not sent: ${esc(fails[id])}</span>` : ''}${RO && !decided ? '<span>answer it on the Mac</span>' : ''}</div></article>`;
  }
  const empty = words => `<div class="empty">${esc(words)}</div>`;
  const grp = (k, label, n, open, inner, cls) => `<details class="grp${cls || ''}" data-k="${esc(k)}"${open ? ' open' : ''}><summary data-key="${esc('d:' + k)}"><span class="one" dir="auto">${esc(label)}</span><span class="mute">${n}</span></summary>${inner}</details>`;
  const isOpen = (k, dflt) => Object.prototype.hasOwnProperty.call(groups, k) ? !!groups[k] : dflt;
  // Ready: what can be queued, by project, then map; the rest of the open tickets folded underneath
  function readyCol(rows, off) {
    const can = rows.filter(t => addable(t)), not = rows.filter(t => !addable(t)), many = can.length > 30 && !F.q && !F.m;
    const byP = new Map();
    for (const t of can) { const p = projOf(t.map); if (!byP.has(p)) byP.set(p, new Map()); const m = byP.get(p); if (!m.has(t.map)) m.set(t.map, []); m.get(t.map).push(t); }
    let h = '';
    for (const [p, maps] of [...byP].sort((x, y) => x[0].localeCompare(y[0]))) {
      let inner = '', n = 0;
      for (const [m, list] of [...maps].sort((x, y) => x[0].localeCompare(y[0]))) {
        n += list.length;
        inner += grp('g:m:' + m, list[0].map_title || m, list.length, isOpen('g:m:' + m, !many), list.map(t => ticketCard(t, off)).join(''));
      }
      h += grp('g:p:' + p, p, n, isOpen('g:p:' + p, true), inner);
    }
    if (!can.length) h += empty(tickets() ? (rows.length ? 'Nothing here can run yet.' : 'No open tickets match.') : 'Reading the maps…');
    if (not.length) h += `<details class="more" data-k="g:more"${isOpen('g:more', !!F.q) ? ' open' : ''}><summary data-key="d:g:more">${plural(not.length, 'more open ticket')} cannot run yet</summary>${not.map(t => ticketCard(t, off)).join('')}</details>`;
    return h;
  }
  const endedCol = (now, old, live, word) => (now.length ? now.map(i => endedCard(i, live)).join('') : empty(old.length ? 'The list is clear.' : word))
    + (old.length ? `<details class="more" data-k="${esc('g:old:' + word)}"${isOpen('g:old:' + word, false) ? ' open' : ''}><summary data-key="${esc('d:g:old:' + word)}">${plural(old.length, 'earlier one')}, cleared from the list</summary>${old.map(i => endedCard(i, live)).join('')}</details>` : '');

  // ---- the side panel ----
  function panelTicket(key) {
    const t = tOf(key), i = itemOf(key), d = DT.get(key) || null, isJob = i && i.kind == 'job';
    const title = t ? t.title : i ? titleOf(i) : d && d.title ? d.title : 'Ticket';
    const where = t ? `${projOf(t.map)} · ${t.map_title || t.map}` : i ? projItem(i) : '';
    const word = t ? t.state : d && d.open === false ? 'closed' : '';
    let h = `<div class="ptitle" dir="auto">${esc(title)}</div><div class="mute">${esc(where)}${where && word ? ' · ' : ''}${word ? `<span class="stc">${esc(word)}</span>` : ''}</div>`;
    if (i) {
      const run = i.state == 'running', a = run ? agentOf(i.key) : null, step = a ? act(a)[1] : '';
      const st = run ? `running on ${i.runner || i.agent || ''} for ${dur(S.now - num(i.started))}${step || i.note ? ': ' + (step || firstLine(i.note)) : ''}`
        : i.state == 'queued' ? `queued, number ${queuedTickets().indexOf(i.key) + 1 || '–'} in line` + (i.agent ? `, on ${i.agent}` : '')
        : ENDED[i.state] ? `${ENDED[i.state][1]} ${ago(S.now, i.ended)}` + (i.commit ? `, commit ${String(i.commit).slice(0, 9)}` : '') : String(i.state);
      h += `<h3>In the queue</h3><p dir="auto">${esc(st)}</p>`
        + (i.state == 'failed' || i.state == 'skipped' ? `<p class="txt" dir="auto">${esc(i.note || 'no reason recorded')}</p>` : '')
        + checksOf(i, true) + selfOf(i, true) + (fileLinks(i) ? `<div class="lk">${fileLinks(i)}</div>` : '');
      if (isJob) h += `<h3>Prompt</h3><p class="txt" dir="auto">${esc(i.prompt)}</p>`;
    }
    if (t) {
      if (t.why) h += `<h3>Why</h3><p dir="auto">${esc(t.why)}</p>`;
      if (t.question) h += `<h3>Question</h3><p class="txt" dir="auto">${esc(t.question)}</p>`;
      h += `<h3>Done when</h3><p class="txt" dir="auto">${t.done_when ? esc(t.done_when) : '<span class="mute">not written yet</span>'}</p>`;
      const ps = Array.isArray(t.paths) ? t.paths : [];
      h += `<h3>Paths</h3>${ps.length ? `<ul>${ps.map(p => `<li><code dir="ltr">${esc(p)}</code></li>`).join('')}</ul>` : '<p class="mute">none listed</p>'}`;
      const ck = Array.isArray(t.checks) ? t.checks : [];
      h += `<h3>Checks</h3>${ck.length ? `<ul>${ck.map(c => `<li><code dir="ltr">${esc(c)}</code></li>`).join('')}</ul>` : '<p class="mute">none: it cannot be queued until it has some</p>'}`;
      const bs = (Array.isArray(t.blocked_by_open) ? t.blocked_by_open : []).map(b => bTitle(t, b));
      if (bs.length) h += `<h3>After</h3><p dir="auto">${esc(bs.join(', '))}</p>`;
    }
    if (!isJob) {
      if (!d || d.loading && !d.key) h += `<p class="mute">Reading its comments and handoffs…</p>`;
      else if (d.error) h += `<p class="err">Its details could not be read: ${esc(d.error)}</p>`;
      else {
        const cm = Array.isArray(d.comments) ? d.comments : [];
        h += `<h3>Comments</h3>${cm.length ? cm.map(c => `<div class="tr txt" dir="auto">${esc(String(c).replace(/^- /, ''))}</div>`).join('') : '<p class="mute">none yet</p>'}`;
        const tr = Array.isArray(d.trail) ? d.trail.filter(x => x && typeof x == 'object') : [];
        h += `<h3>Handoff, checkpoint and newest run</h3>${tr.length ? tr.map(x => `<div class="tr"><div><b>${esc(x.name)}</b> <span class="mute">${esc(ago(S.now, x.at))}</span>${obs(x.uri) ? ` · <a href="${esc(obs(x.uri))}">Open in Obsidian</a>` : ''}</div><div class="mute" dir="auto">${esc(x.first)}</div></div>`).join('') : '<p class="mute">none for its map</p>'}`;
        const links = [obs(d.uri) && `<a href="${esc(obs(d.uri))}">${svg('external-link')} Open the ticket in Obsidian</a>`, obs(d.map_uri) && `<a href="${esc(obs(d.map_uri))}">${svg('external-link')} Open its map in Obsidian</a>`].filter(Boolean);
        if (links.length) h += `<h3>Open in Obsidian</h3><div class="lk">${links.join('')}</div>`;
      }
    }
    return h;
  }
  function panelActions(key) {
    if (RO || !canAct) return '';
    const t = tOf(key), i = itemOf(key), d = DT.get(key) || {}, run = !!i && i.state == 'running', off = pbusy || !!O.down;
    if (i && i.kind == 'job') return '';
    let h = `<h3>Actions</h3>${pnote ? `<div class="sb-qn" role="alert">${pnote}</div>` : ''}`;
    if (run) return h + '<p class="mute">A worker is running this ticket: its actions wait until it ends.</p>';
    if (canQ && t) {
      const live = liveKeys(), queued = i && i.state == 'queued', qt = queuedTickets(), at = qt.indexOf(key), qoff = off || qbusy;
      const btns = queued ? [mbtn('data-up', key, 'Move up', 'chevron-up', qoff || at <= 0), mbtn('data-dn', key, 'Move down', 'chevron-down', qoff || at < 0 || at >= qt.length - 1), mbtn('data-back', key, 'Back to Ready', 'arrow-back-up', qoff)]
        : !live.has(key) && addable(t) ? [mbtn('data-add', key, 'Queue it', 'list-numbers', qoff)] : [];
      if (queued && installed().length) btns.push(`<select data-ia="${esc(key)}" data-key="${esc('ia:' + key)}" aria-label="Agent for this item"${qoff ? ' disabled' : ''}><option value="">${esc(poolWord())}</option>${installed().map(([n]) => `<option value="${esc(n)}"${n === i.agent ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select>`);
      if (btns.length) h += `<div class="pa"><div class="row">${btns.join('')}</div></div>`;
    }
    const k = s => esc('pin:' + s + ':' + key);
    const confirm = a => pend && pend.action == a ? `<div class="cf" role="alert"><span dir="auto">${esc(ACTS[a][1])}${pend.text ? ': “' + esc(pend.text) + '”' : ''}${pend.commit ? ', commit ' + esc(pend.commit) : ''}?</span><button type="button" class="def" data-pyes="1"${off ? ' disabled' : ''}>${pbusy ? 'Working…' : esc(ACTS[a][2])}</button><button type="button" data-pno="1"${pbusy ? ' disabled' : ''}>Cancel</button></div>` : '';
    const go = (a, cls) => confirm(a) || `<div class="row"><button type="button" data-pa="${a}" class="${cls || ''}"${off ? ' disabled' : ''}>${esc(ACTS[a][0])}</button></div>`;
    if (t) {
      h += `<div class="pa"><label>Done: what was done, in one line<input data-pin="done" data-key="${k('done')}" maxlength="300" placeholder="e.g. fixed by hand in the editor"></label><input data-pin="commit" data-key="${k('commit')}" maxlength="40" placeholder="its commit, optional" aria-label="Its commit, optional">${go('done')}</div>`;
      h += `<div class="pa"><label>Drop: why it is out of scope<input data-pin="drop" data-key="${k('drop')}" maxlength="300" placeholder="e.g. replaced by another ticket"></label>${go('drop', 'danger')}</div>`;
      if (t.status == 'claimed') h += `<div class="pa"><span class="mute" dir="auto">${esc(t.reason || 'claimed')}</span>${go('release')}</div>`;
    }
    if (t || d.file) h += `<div class="pa"><label>Comment<textarea data-pin="comment" data-key="${k('comment')}" maxlength="4000" placeholder="Added under the ticket's Comments, dated today"></textarea></label>${go('comment')}</div>`;
    if (t) {
      h += `<div class="pa"><label>Tier: the model it runs on<select data-pin="tier" data-key="${k('tier')}">${['sonnet', 'opus'].map(x => `<option value="${x}"${x === t.tier ? ' selected' : ''}>${x}</option>`).join('')}</select></label>${go('tier')}</div>`;
      const mc = Array.isArray(d.map_checks) ? d.map_checks.join('; ') : '';
      h += `<div class="pa"><label>Checks of its map, separated by ;<input data-pin="checks" data-key="${k('checks')}" maxlength="2000" value="${esc(mc)}" placeholder="e.g. pnpm typecheck; pnpm test"></label>${go('checks')}</div>`;
    }
    return h;
  }
  function panelProject(path) {
    const pl = provsOf(path), ss = (S ? Object.values(S.agents || {}) : []).filter(a => a && a.project === path && a.role != 'worker');
    let h = `<div class="ptitle" dir="auto">${esc(proj(path) || 'No project')}</div><div class="mute" dir="ltr">${esc(path)}</div>`;
    h += pl.length ? pl.map(p => { const ws = wlist(p), logs = ws.filter(w => w.kind == 'log' && Array.isArray(w.lines));
      return `<h3>${icon(own(PICON, p.icon) || 'tool', p.title)} ${esc(p.title)}</h3><div class="pl">${ws.map(widget).join('')}</div>`
        + logs.map(l => `<div class="mute">${esc(l.label)}</div><pre>${l.lines.map(esc).join('\n')}</pre>`).join(''); }).join('')
      : '<p class="mute">No repo, Unity or provider widgets for it yet.</p>';
    if (ss.length) h += `<h3>Its sessions</h3>${ss.map(a => `<div class="tr">${stIc(a.state)} <span dir="auto">${esc(lbl(a))}</span> <span class="mute">${esc(stOf(a.state)[1])}</span></div>`).join('')}`;
    return h;
  }
  function loadDetail(key) {
    if (!canGet || !/#\d+$/.test(key)) return;
    const had = DT.get(key);
    if (!had) DT.set(key, {loading: true});
    Promise.resolve(io.get('api/ticket?key=' + encodeURIComponent(key))).then(d => { DT.set(key, d && typeof d == 'object' ? d : {error: 'no details'}); },
      e => { if (!had || had.loading) DT.set(key, {error: String(e && e.message || e)}); }).then(() => { if (S && P && P.key === key) render(S, O, true); });
  }
  function loadSelf(key) {
    if (!canGet || selfCk.has(key)) return;
    selfCk.set(key, null);
    Promise.resolve(io.get('api/item/report?key=' + encodeURIComponent(key), true)).then(t => { selfCk.set(key, selfChecksOf(t) || 'none reported'); },
      () => { selfCk.set(key, 'no report to read yet'); }).then(() => { if (S) render(S, O, true); });
  }
  function openPanel(kind, key) {
    P = {kind, key}; pend = null; pnote = null; F.t = kind == 'project' ? 'p:' + key : key; writeHash();
    if (kind == 'ticket') { loadDetail(key); const i = itemOf(key); if (i && ENDED[i.state]) loadSelf(key); }
    if (S) render(S, O, true);
    const x = panel.querySelector('[data-close]'); if (x) x.focus({preventScroll: true});
  }
  function closePanel() {
    const k = P && P.key; P = null; pend = null; pnote = null; F.t = ''; writeHash();
    if (S) render(S, O, true);
    const c = k && root.querySelector(`[data-open="${CSS.escape(k)}"]`); if (c) c.focus({preventScroll: true});
  }
  function writeHash() {
    const p = new URLSearchParams(); for (const k of ['p', 'm', 'q', 't', 'c']) if (F[k]) p.set(k, F[k]);
    const h = p.toString();
    try { history.replaceState(null, '', h ? '#' + h : location.pathname + location.search); } catch (e) { /* a sandboxed frame */ }
  }

  // ---- the "To" list, the filters and the job form: drawn once, their lists follow the state ----
  function fillTo(tops, kids) {
    if (!sel || document.activeElement === sel) return;  // rebuilding an open list closes it
    const v = sel.value, gs = new Map();
    for (const a of tops) { const k = proj(a.project) || (a.parent == 'queue' ? 'Queue workers' : 'No project'); if (!gs.has(k)) gs.set(k, []); gs.get(k).push(a); }
    const frag = document.createDocumentFragment(), first = document.createElement('option');
    first.value = ''; first.textContent = 'To…'; frag.appendChild(first);
    for (const [name, list] of gs) {
      const g = document.createElement('optgroup'); g.label = name;
      for (const a of list) {
        const o = document.createElement('option'); o.value = a.agent; o.textContent = `${lbl(a)} (${stOf(a.state)[1]})`; g.appendChild(o);
        for (const w of kids(a)) { if (w.state == 'done') continue;
          const x = document.createElement('option'); x.value = w.agent; x.textContent = `   ↳ ${lbl(w)}`; g.appendChild(x); }
      }
      frag.appendChild(g);
    }
    sel.replaceChildren(frag);
    sel.value = [...sel.options].some(o => o.value === v) ? v : '';
  }
  function fillFilters() {
    const T = tickets() || [], ps = new Set(T.map(t => projOf(t.map))), maps = new Map();
    for (const i of items().concat(cleared())) { const p = projItem(i); if (p) ps.add(p); }
    for (const t of T) if (!F.p || projOf(t.map) === F.p) maps.set(t.map, t.map_title || t.map);
    if (F.p) ps.add(F.p); if (F.m && !maps.has(F.m)) maps.set(F.m, F.m);
    const opt = (v, l, on) => `<option value="${esc(v)}"${on ? ' selected' : ''}>${esc(l)}</option>`;
    const wp = opt('', 'Every project', !F.p) + [...ps].sort().map(p => opt(p, p, p === F.p)).join('');
    const wm = opt('', 'Every map', !F.m) + [...maps].sort((x, y) => x[1].localeCompare(y[1])).map(([m, l]) => opt(m, l, m === F.m)).join('');
    if (document.activeElement !== fP && fP.dataset.h !== wp) { fP.innerHTML = wp; fP.dataset.h = wp; }
    if (document.activeElement !== fM && fM.dataset.h !== wm) { fM.innerHTML = wm; fM.dataset.h = wm; }
  }
  const agentOpts = (chosen, first) => first + installed().map(([n, e]) => {
    const [, w] = agentState(n, e);
    return `<option value="${esc(n)}"${n === chosen ? ' selected' : ''}>${esc(n)}${e.kind == 'agy' ? ' (' + agyWords + ')' : ''}${w == 'signed in' ? '' : ' · ' + esc(w)}</option>`;
  }).join('');
  function fillJob() {
    if (!job) return;
    const a = job.elements.agent, dl = $('#sb-projects');
    if (document.activeElement !== a) {
      const v = a.value;
      a.innerHTML = agentOpts(null, `<option value="">${esc(poolWord())}</option>`);
      a.value = [...a.options].some(o => o.value === v) ? v : '';
    }
    const T = tickets(), ps = new Set(T ? T.map(t => projOf(t.map)) : []);
    const w = [...ps].sort().map(p => `<option value="${esc(p)}"></option>`).join('');
    if (dl.innerHTML !== w) dl.innerHTML = w;
    job.querySelector('button[type=submit]').disabled = !!O.down;
  }
  function ctlHtml() {
    const q = Q(); if (!q) return '';
    const off = qbusy || !!O.down, agents = installed(), stopV = q.stop_at ? new Date(num(q.stop_at) * 1000).toTimeString().slice(0, 5) : '';
    return `<button type="button" class="${q.paused ? 'def' : ''}" data-qact="pause" data-key="qp"${off ? ' disabled' : ''}>${q.paused ? svg('player-play') + ' Resume the queue' : svg('player-pause') + ' Pause the queue'}</button>`
      + (agents.length ? `<fieldset class="pool"><legend>Agents for tonight</legend>${agents.map(([n, e]) => `<label title="${esc(n + ': ' + agentState(n, e)[1])}"><input type="checkbox" data-pool="${esc(n)}" data-key="${esc('pool:' + n)}"${poolOf().includes(n) ? ' checked' : ''}${off ? ' disabled' : ''}> ${esc(n)}${e.kind == 'agy' ? ' (' + esc(agyWords) + ')' : ''}</label>`).join('')}</fieldset>` : '<span class="mute">No agents found yet.</span>')
      + `<button type="button" data-qact="scan" data-key="scan"${off ? ' disabled' : ''}>${svg('search')} Scan for agents</button>`
      + `<label>Stop at<input type="time" data-qs="1" data-key="qs" value="${esc(stopV)}"${off ? ' disabled' : ''}></label>`
      + `<label><input type="checkbox" data-qf="1" data-key="qf"${q.final_review ? ' checked' : ''}${off ? ' disabled' : ''}> Final review after the last ticket</label>`;
  }
  function hint() {
    if (!cs) return;
    if (csNote) { cs.innerHTML = csNote; return; }
    const a = agentOf(sel.value);
    cs.textContent = a ? `To ${lbl(a)} · ${whenFor(a)}` : 'Pick a session or worker (the mail button on its card), then type.';
  }
  function grow() { msg.style.height = 'auto'; msg.style.height = Math.min(msg.scrollHeight + 2, 132) + 'px'; }

  // ---- writes ----
  async function answer(qid, i) {
    const q = S && own(S.questions, qid);
    if (RO || !q || !Array.isArray(q.options) || i >= q.options.length || q.answer != null || own(sending, qid) != null) return;
    delete fails[qid]; sending[qid] = i; render(S, O, true);
    const why = O.down ? 'hub not reachable' : await io.answer(qid, q.options[i]).catch(e => String(e));
    delete sending[qid];
    if (why) fails[qid] = why; else { q.answer = q.options[i]; q.by = 'you'; q.answered = S.now; }
    render(S, O, true); if (io.changed) io.changed();
  }
  async function send(e) {
    e.preventDefault();
    const to = sel.value, text = msg.value.trim();
    if (!to) { csNote = '<span class="err">Pick who it is for first.</span>'; hint(); csNote = null; sel.focus(); return; }
    if (!text) { msg.focus(); return; }
    const a = agentOf(to), go = form.querySelector('button[type=submit]');
    go.disabled = true;
    const why = await io.send(to, text).catch(err => String(err));
    go.disabled = false;
    if (why) { csNote = `<span class="err" role="alert">Not sent: ${esc(why)}</span>`; hint(); return; }
    msg.value = ''; grow();
    csNote = `<span class="okc">${svg('check')} Queued for ${esc(a ? lbl(a) : short(to))}.</span> ${esc(whenFor(a))}`; hint();
    setTimeout(() => { csNote = null; hint(); }, 6000);
    if (io.changed) io.changed();
  }
  const say = (ok, words) => { qnote = ok ? `<span class="okc">${svg('check')} ${esc(words)}</span>` : `<span class="err" role="alert">Not done: ${esc(words)}</span>`;
    const shown = qnote; if (ok) setTimeout(() => { if (qnote === shown) { qnote = null; qn.innerHTML = ''; } }, 5000); };
  // one queue write: it carries the version; a stale answer redraws from the hub's queue
  const CHECKED = new Set(['api/queue/set', 'api/queue/move', 'api/queue/options', 'api/queue/remove_job', 'api/queue/agents', 'api/queue/clear-finished']);
  async function qwrite(path, data, done) {
    const q = Q();
    if (!hasQ || qbusy || O.down || !q) {  // not sent: undo what the click already changed (a disabled box)
      for (const k of Object.keys(lastH)) delete lastH[k];
      if (S) render(S, O, true);
      return null;
    }
    qbusy = true; qnote = '<span class="mute">Saving…</span>'; render(S, O, true);
    const out = await Promise.resolve(io.queue(path, CHECKED.has(path) ? {...data, version: q.version} : data)).catch(e => ({ok: false, error: String(e)})) || {};
    qbusy = false;
    if (out.queue && typeof out.queue == 'object' && S) S.queue = out.queue;
    if (out.installed && typeof out.installed == 'object' && S) S.installed = out.installed;
    if (out.stale) { const shown = qnote = '<span class="err" role="alert">Not done: the list changed, try again.</span>';
      setTimeout(() => { if (qnote === shown) { qnote = null; qn.innerHTML = ''; } }, 10000); }
    else if (out.ok === false || out.error) say(false, out.error || 'the hub refused it');
    else if (done) say(true, done); else qnote = null;
    render(S, O, true);
    if (io.changed) io.changed(true);
    return out;
  }
  async function simple(path, data, done) {
    if (!canAct || O.down) return;
    const out = await Promise.resolve(io.act(path, data)).catch(e => ({ok: false, error: String(e)})) || {};
    say(!(out.ok === false || out.error), out.error || done);
    if (S) render(S, O, true);
    if (io.changed) io.changed();
  }
  function addKeys(key) {
    const keys = queuedTickets(), add = withBlockers(key, []).filter(k => !keys.includes(k));
    return qwrite('api/queue/set', {keys: keys.concat(add)}, add.length > 1 ? `Queued with ${plural(add.length - 1, 'ticket')} it waits on.` : 'Queued.');
  }
  const moveTo = (key, to) => qwrite('api/queue/move', {key, to}, 'Moved.');
  const untick = key => qwrite('api/queue/set', {keys: queuedTickets().filter(k => k !== key)}, 'Back in Ready.');
  async function dropInto(key, idx) {
    const out = await addKeys(key);
    if (out && out.ok && idx != null) { const at = queuedTickets().indexOf(key); if (at >= 0 && at !== idx) moveTo(key, idx); }
  }
  function stopEpoch(v) {
    if (!/^\d\d:\d\d$/.test(v)) return null;
    const d = new Date(S.now * 1000), [hh, mm] = v.split(':').map(Number);
    d.setHours(hh, mm, 0, 0);
    if (d.getTime() / 1000 <= S.now) d.setDate(d.getDate() + 1);  // the next time the clock shows it
    return d.getTime() / 1000;
  }
  const pinOf = name => { const el = R.pact.querySelector(`[data-pin="${name}"]`); return el ? el.value.trim() : ''; };
  async function doAction() {
    if (!pend || !P || pbusy) return;
    const {action, text, commit} = pend, key = P.key;
    pbusy = true; render(S, O, true);
    const out = await Promise.resolve(io.act('api/ticket/' + action, {key, text, commit: commit || null})).catch(e => ({ok: false, error: String(e)})) || {};
    pbusy = false; pend = null;
    if (out.ok === false || out.error) pnote = `<span class="err" role="alert">Not done: ${esc(out.error || 'the hub refused it')}</span>`;
    else {
      pnote = `<span class="okc">${svg('check')} Done: ${esc(ACTS[action][1].toLowerCase())}.</span>`;
      for (const n of [action, action == 'done' ? 'commit' : '']) if (n && n != 'tier' && n != 'checks') { const dk = 'pin:' + n + ':' + key; dirty.delete(dk); const el = R.pact.querySelector(`[data-key="${CSS.escape(dk)}"]`); if (el) el.value = ''; }
      if (action == 'checks') dirty.delete('pin:checks:' + key);
      loadDetail(key);
    }
    render(S, O, true);
    if (io.changed) io.changed(true);
  }

  // ---- events ----
  if (form) {
    form.addEventListener('submit', send);
    msg.addEventListener('input', grow);
    msg.addEventListener('keydown', e => { if (e.key == 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
    sel.addEventListener('change', () => target(sel.value));
  }
  if (job) job.addEventListener('submit', async e => {
    e.preventDefault();
    const f = job.elements, project = f.project.value.trim(), prompt = f.prompt.value;
    if (!project || !prompt.trim()) { jn.innerHTML = '<span class="err">A job needs a project and a prompt.</span>'; return; }
    const go = job.querySelector('button[type=submit]'); go.disabled = true; jn.textContent = 'Queueing…';
    const out = await qwrite('api/queue/job', {project, prompt, agent: f.agent.value || null, model: f.model.value.trim() || null, name: f.name.value.trim() || null, at: f.at.value || null});
    go.disabled = false;
    if (!out) { jn.innerHTML = '<span class="err">Not queued: the hub is busy or not reachable.</span>'; return; }
    if (out.ok) { f.prompt.value = ''; f.name.value = ''; f.at.value = ''; jn.innerHTML = `<span class="okc">${svg('check')} Queued. It runs when the queue reaches it.</span>`; qnote = null; render(S, O, true); }
    else jn.innerHTML = `<span class="err" role="alert">Not queued: ${esc(out.stale ? 'the list changed, try again' : out.error || 'the hub refused it')}</span>`;
  });
  let typing = null;
  fQ.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { F.q = fQ.value.trim(); writeHash(); if (S) render(S, O, true); }, 150); });
  for (const f of [fP, fM]) f.addEventListener('change', () => {
    F[f.dataset.f] = f.value; if (f === fP) F.m = ''; writeHash(); if (S) render(S, O, true);
  });
  document.addEventListener('keydown', e => {
    const t = e.target, typingNow = t && (t.tagName == 'TEXTAREA' || t.tagName == 'INPUT' || t.tagName == 'SELECT' || t.isContentEditable);
    if (e.key == '/' && !typingNow && !e.metaKey && !e.ctrlKey) { e.preventDefault(); fQ.focus(); }
    if (e.key == 'Escape' && P && !typingNow) { closePanel(); return; }
    if (e.key == 'Escape' && msg && t === msg && !msg.value) { target(''); msg.blur(); }
  });
  root.addEventListener('keydown', e => {
    const c = e.target && e.target.dataset && e.target.dataset.open;
    if (c && (e.key == 'Enter' || e.key == ' ')) { e.preventDefault(); openPanel('ticket', c); }
  });
  root.addEventListener('input', e => { const el = e.target; if (el.dataset && el.dataset.key && el.type != 'checkbox' && el.type != 'time') dirty.add(el.dataset.key); });
  root.addEventListener('click', async e => {
    const b = e.target.closest('button');
    if (!b && e.target.closest('a,summary,input,select,textarea,label,.menu')) return;
    if (b) { const m = b.closest('details.menu'); if (m) m.open = false; }
    const d = b ? b.dataset : {};
    if (b && b.disabled) return;
    if (d.q != null) { answer(d.q, +d.i); return; }
    if (d.unsend) { b.disabled = true; const why = await io.unsend(d.unsend).catch(err => String(err));
      if (why) { csNote = `<span class="err" role="alert">Not taken back: ${esc(why)}</span>`; hint(); csNote = null; } if (io.changed) io.changed(); return; }
    if (d.to) { target(d.to); if (msg) msg.focus(); return; }
    if (d.close) { closePanel(); return; }
    if (d.tab) { tab = d.tab; F.c = tab; writeHash(); if (S) render(S, O, true); return; }
    if (d.proj != null) { openPanel('project', d.proj); return; }
    if (d.add) { addKeys(d.add); return; }
    if (d.again) { addKeys(d.again); return; }
    if (d.back) { untick(d.back); return; }
    if (d.up || d.dn) { const k = d.up || d.dn, at = queuedTickets().indexOf(k); if (at >= 0) moveTo(k, d.up ? at - 1 : at + 1); return; }
    if (d.rmjob) { qwrite('api/queue/remove_job', {key: d.rmjob}, 'Job removed. You can queue it again, corrected.'); return; }
    if (d.qact == 'pause') { const q = Q(); if (q) qwrite('api/queue/pause', {paused: !q.paused}, q.paused ? 'Resumed: the queue runs.' : 'Paused: nothing new starts.'); return; }
    if (d.qact == 'scan') { qwrite('api/agents/scan', {}, 'Agents scanned.'); return; }
    if (d.clear) { qwrite('api/queue/clear-finished', {}, 'Finished items cleared from the list; they stay in the vault.'); return; }
    if (d.quiet) { simple('api/agents/clear-quiet', {}, 'Quiet sessions cleared from the board.'); return; }
    if (d.dismiss) { simple('api/agents/dismiss', {agent: d.dismiss}, 'Dismissed: it comes back with its next event.'); return; }
    if (d.pa) {
      const a = d.pa, text = a == 'release' ? '' : pinOf(a), commit = a == 'done' ? pinOf('commit') : '';
      if (a != 'release' && !text) { pnote = '<span class="err" role="alert">Type it first.</span>'; render(S, O, true); return; }
      pend = {action: a, text, commit}; pnote = null; render(S, O, true);
      const y = R.pact.querySelector('[data-pyes]'); if (y) y.focus({preventScroll: true}); return;
    }
    if (d.pyes) { doAction(); return; }
    if (d.pno) { pend = null; render(S, O, true); return; }
    if (b) return;
    if (getSelection().toString()) return;
    const c = e.target.closest('[data-open]');
    if (c) { openPanel('ticket', c.dataset.open); return; }
    const r = e.target.closest('[data-row]');
    if (r && sel) target(r.dataset.row);
  });
  root.addEventListener('change', e => {
    const el = e.target, d = el.dataset || {};
    if (d.ia) { qwrite('api/queue/item_agent', {key: d.ia, name: el.value || null}, 'Agent set for this item.'); return; }
    if (d.pool) {  // the night's pool: checked agents in the order they were added
      const now = poolOf(), names = el.checked ? now.filter(n => n !== d.pool).concat([d.pool]) : now.filter(n => n !== d.pool);
      if (!names.length) { el.checked = true; say(false, 'keep at least one agent for tonight'); render(S, O, true); return; }
      qwrite('api/queue/agents', {names}, `Tonight runs on ${names.join(', ')}.`); return;
    }
    if (d.qs || d.qf) {
      const q = Q(); if (!q) return;
      const stop = d.qs ? stopEpoch(el.value) : q.stop_at ?? null, fin = d.qf ? el.checked : !!q.final_review;
      qwrite('api/queue/options', {stop_at: stop, final_review: fin}, d.qs ? (stop ? `Stops at ${hm(stop)}.` : 'No stop time.') : fin ? 'A final review follows the last ticket.' : 'No final review.');
    }
  });
  // drag a Ready card into Queued (onto a card: that place), a queued card onto another, or back to Ready
  const dropCol = e => { const c = drag && e.target.closest && e.target.closest('.col'); if (!c) return null;
    const k = c.dataset.col; return (k == 'queued' || (k == 'ready' && drag.kind == 'q')) ? c : null; };
  const clearDrag = () => root.querySelectorAll('.drag,.over').forEach(x => x.classList.remove('drag', 'over'));
  root.addEventListener('dragstart', e => {
    const c = e.target.closest && e.target.closest('[data-drag]'); if (!c || !canQ) return;
    drag = {kind: c.dataset.drag, key: c.dataset.open}; c.classList.add('drag');
    try { e.dataTransfer.setData('text/plain', drag.key); e.dataTransfer.effectAllowed = 'move'; } catch (x) { /* old browsers */ }
  });
  root.addEventListener('dragover', e => {
    const c = dropCol(e); if (!c) return;
    e.preventDefault(); root.querySelectorAll('.over').forEach(x => x.classList.remove('over')); c.classList.add('over');
    const card = c.dataset.col == 'queued' && e.target.closest('[data-drag=q]'); if (card) card.classList.add('over');
  });
  root.addEventListener('drop', e => {
    const c = dropCol(e); if (!c) return;
    e.preventDefault();
    const {kind, key} = drag, card = e.target.closest('[data-drag=q]'), qt = queuedTickets(), idx = card ? qt.indexOf(card.dataset.open) : -1;
    drag = null; clearDrag();
    if (c.dataset.col == 'ready') { untick(key); return; }
    if (kind == 'add') { dropInto(key, idx >= 0 ? idx : null); return; }
    const to = idx >= 0 ? idx : qt.length - 1;
    if (to !== qt.indexOf(key)) moveTo(key, to); else render(S, O, true);
  });
  root.addEventListener('dragend', () => { drag = null; clearDrag(); });
  root.addEventListener('focusout', () => { if (deferred) setTimeout(() => { if (deferred && S) render(S, O); }, 0); });
  root.addEventListener('toggle', e => {
    const d = e.target, k = d.dataset && d.dataset.k;
    if (!k) return;
    if (k.startsWith('g:')) { groups[k] = d.open; saveObj('sbhub.groups', groups); return; }
    if (k.startsWith('ck:') || k.startsWith('sc:')) { if (d.open) opened.add(k); else opened.delete(k); }
    if (d.open && d.dataset.self) loadSelf(d.dataset.self);
  }, true);
  setInterval(() => { if (P && P.kind == 'ticket' && S && !O.down && !pbusy) loadDetail(P.key); }, 15000);

  // ---- one render: every region rewritten only when its html changed, keeping focus, scroll and typed text ----
  function typingIn() {
    const ae = document.activeElement;
    if (!ae || !root.contains(ae)) return null;
    const typing = ae.tagName == 'SELECT' || ae.tagName == 'TEXTAREA' || (ae.tagName == 'INPUT' && ae.type != 'checkbox');
    return typing ? ae.closest('[data-region]') : null;
  }
  function put(k, html) {
    const el = R[k]; if (!el || lastH[k] === html) return;
    const vals = [];
    el.querySelectorAll('input[data-key],textarea[data-key],select[data-key]').forEach(x => { if (dirty.has(x.dataset.key)) vals.push([x.dataset.key, x.value]); });
    const top = el.scrollTop;
    el.innerHTML = html; lastH[k] = html;
    for (const [dk, v] of vals) { const x = el.querySelector(`[data-key="${CSS.escape(dk)}"]`); if (x) x.value = v; }
    if (top) el.scrollTop = top;
  }

  function render(s, o, force) {
    S = s; O = o || {}; gotAt = Date.now();
    root.classList.toggle('down', !!O.down);
    const ban = $('.sb-banner'); ban.hidden = !O.down; ban.textContent = O.down || '';
    const live = $('.sb-live'), [ok, word] = O.live || [!O.down, O.down ? 'offline' : 'live'];
    live.classList.toggle('off', !ok); live.lastChild.textContent = word;
    if (form) for (const el of [sel, msg, form.querySelector('button[type=submit]')]) el.disabled = !!O.down;
    const T = tickets(); byKey = new Map((T || []).map(t => [tkey(t), t]));

    const agents = Object.entries(s.agents || {}).map(([k, a]) => ({...a, agent: a.agent || k}));
    const byId = new Map(agents.map(a => [a.agent, a]));
    const parId = a => { const p = byId.get(a.parent); return p && p.role != 'worker' ? p.agent : null; };
    const order = (x, y) => rank(x) - rank(y) || num(y.at) - num(x.at);
    const qworkers = agents.filter(a => a.role == 'worker' && a.parent == 'queue');
    const sessions = agents.filter(a => (a.role != 'worker' || !parId(a)) && !(a.role == 'worker' && a.parent == 'queue')).sort(order);
    const kids = p => agents.filter(a => a.role == 'worker' && parId(a) === p.agent).sort(order);
    const qs = Object.entries(s.questions || {}).filter(([, q]) => q && typeof q == 'object'), locks = Object.entries(s.locks || {});
    const openQ = qs.filter(([, q]) => q.answer == null), recent = qs.filter(([, q]) => q.answer != null && s.now - num(q.answered) < 20);
    const need = sessions.filter(a => rank(a) == 0), wait = sessions.filter(a => a.state == 'your turn'), working = sessions.filter(a => a.state == 'working');
    const provs = s.providers && typeof s.providers == 'object' ? s.providers : {};
    const bad = []; for (const path of Object.keys(provs)) for (const p of provsOf(path)) for (const w of wlist(p)) if (w.level == 'bad') bad.push([path, p, w]);
    const signedOut = installed().filter(([, e]) => e.login == 'expired');
    const its = items(), cl = cleared(), liveK = liveKeys(), q = Q();
    const ended = (list, states, all) => list.filter(i => states.includes(i.state) && (all || s.now - num(i.ended) < WEEK)).sort((x, y) => num(y.ended) - num(x.ended));
    const doneNow = ended(its, ['done']), doneOld = ended(cl, ['done']), failNow = ended(its, ['failed', 'skipped'], true), failOld = ended(cl, ['failed', 'skipped']);
    const running = its.filter(i => i.state == 'running'), queuedI = its.filter(i => i.state == 'queued');
    const alerts = openQ.length + need.length + bad.length + signedOut.length;
    const msgsQ = Object.values(s.messages || {}).filter(m => m && typeof m == 'object' && m.delivered == null && !m.lost).length;
    const end = q ? ends() : 0;

    // the counts strip, one chip per account and one per project (its repo and Unity widgets open in the side panel)
    const ac = installed().map(([n, e]) => {
      const [c, w] = agentState(n, e), u = c == 'out' ? '' : usageOf(e), k = costsOf(e);
      const tip = n + (e.kind == 'agy' ? ' (' + agyWords + ')' : '') + ': ' + w + (u ? ' · ' + u.split(' · ')[0] + ' of its 5-hour window used' : '') + (k ? ' · a ticket costs ' + k : '');
      return `<span class="pill ag ${c}" title="${esc(tip)}">${svg('robot')} ${esc(n)}${u ? ' ' + esc(u) : ''} <span class="w">${esc(w.startsWith('running') ? 'running' : w)}</span></span>`;
    }).join('');
    const pc = Object.keys(provs).sort((x, y) => proj(x).localeCompare(proj(y))).map(path => { const lv = worst(provsOf(path));
      return `<button type="button" class="pill" data-proj="${esc(path)}" data-key="${esc('pj:' + path)}" title="${esc(path + ': its repo, Unity and provider widgets')}">${dot(lv)} ${esc(proj(path) || path)}</button>`; }).join('');
    const strip = (alerts ? `<span class="pill bad">${svg('bell')} ${alerts} need${alerts == 1 ? 's' : ''} you</span>` : `<span class="pill ok">${svg('check')} Nothing needs you</span>`)
      + (wait.length ? `<span class="pill acc" title="Waiting for you: sessions that finished their turn">${svg('message')} ${wait.length} your turn</span>` : '')
      + `<span class="pill${running.length ? ' acc' : ''}" title="queue workers and your sessions working now">${svg('loader-2')} ${running.length + working.length} running</span>`
      + (q ? `<span class="pill" title="queue items waiting">${svg('list-numbers')} ${queuedI.length} queued</span>`
        + `<span class="pill${doneNow.length + doneOld.length ? ' ok' : ''}" title="done in the last 7 days">${svg('circle-check')} ${doneNow.length + doneOld.length} done</span>`
        + (failNow.length ? `<span class="pill bad" title="failed or skipped, still on the list">${svg('x')} ${failNow.length} failed</span>` : '')
        + (end ? (q.paused ? `<span class="pill warn">${svg('player-pause')} paused</span>` : `<span class="pill">${svg('clock')} ends about ${esc(hm(end))}</span>`) : '')
        + (q.stop_at ? `<span class="pill" title="the queue starts nothing after this">stops at ${esc(hm(q.stop_at))}</span>` : '') : '')
      + `<span class="pill">${plural(sessions.length, 'session')}</span>`
      + (locks.length ? `<span class="pill" title="${esc('locks held: ' + locks.map(([k, l]) => k + ' by ' + who(l.by)).join(', '))}">${svg('lock')} ${locks.length}</span>` : '')
      + (msgsQ ? `<span class="pill acc" title="messages waiting for their session's hook">${svg('mail')} ${msgsQ} queued</span>` : '')
      + (ac ? '<span class="sb-sep" aria-hidden="true"></span>' + ac : '') + (pc ? '<span class="sb-sep" aria-hidden="true"></span>' + pc : '');

    if (sel) fillTo(sessions.concat(qworkers), kids);
    fillJob(); fillFilters();

    // the columns
    const off = !canQ || qbusy || !!O.down;
    const rows = (T || []).filter(t => !liveK.has(tkey(t)) && want(projOf(t.map), t.map, t.title));
    const waitsT = rows.filter(t => t.state == 'waits for you'), readyRows = rows.filter(t => t.state != 'waits for you');
    const wantS = a => (!F.p || proj(a.project) === F.p) && !F.m && (!F.q || lbl(a).toLowerCase().includes(F.q.toLowerCase()));
    const needCards = openQ.concat(recent).sort((x, y) => num(x[1].deadline) - num(y[1].deadline)).map(([id, x]) => questionCard(id, x)).join('')
      + signedOut.map(([n]) => `<article class="card alert"><div class="top">${icon('lock', 'signed out', 'bad')}<span class="t">${esc(n)} is signed out</span></div><div class="step">Sign in to it again; until then it is out of tonight's pool.</div></article>`).join('')
      + need.filter(wantS).map(a => sessionCard(a, kids(a))).join('')
      + bad.map(([path, p, w]) => `<article class="card alert" data-proj-card="1"><div class="top">${dot('bad')}<span class="t">${esc(proj(path))} · ${esc(p.title)}: ${esc(w.label)}</span><button type="button" class="ib" data-proj="${esc(path)}" data-key="${esc('pjb:' + path + p.title + w.label)}" aria-label="${esc('Open ' + proj(path))}" title="Open its project">${svg('external-link')}</button></div><div class="step">${esc(String(w.value).slice(0, 160))}</div></article>`).join('')
      + waitsT.map(t => ticketCard(t, off)).join('');
    const qt = queuedTickets(), qShown = queuedI.filter(wantI), runI = running.filter(wantI);
    const handS = sessions.filter(a => rank(a) > 0 && wantS(a));
    const H = {
      strip,
      'h-needs': `<h2>Needs you</h2><span class="n">${openQ.length + signedOut.length + need.length + bad.length + waitsT.length}</span>`,
      needs: needCards || empty('Nothing needs you.'),
      'h-ready': `<h2>Ready</h2><span class="n">${readyRows.filter(t => addable(t)).length}</span>${canQ ? '<span class="sub">drag a card into Queued, or use its menu</span>' : ''}`,
      ready: readyCol(readyRows, off),
      'h-queued': `<h2>Queued</h2><span class="n">${queuedI.length}</span>${q ? `<span class="sub">${q.paused ? (queuedI.length ? 'paused: nothing starts until you resume' : 'paused') : end ? 'ends about ' + esc(hm(end)) : 'running'} · about 1.5 h each</span>` : ''}`,
      queued: qShown.length ? qShown.map(i => queuedCard(i, queuedI.indexOf(i) + 1, qt, off)).join('') : empty(queuedI.length ? 'No queued item matches the filters.' : canQ ? 'Nothing queued. Drag tickets in from Ready, or queue a job.' : 'Nothing queued.'),
      'h-running': `<h2>Running</h2><span class="n">${running.length + handS.filter(a => a.state == 'working').length}</span>${canAct && sessions.length ? `<button type="button" data-quiet="1" data-key="quiet" title="Takes idle sessions (over 2 hours) and finished workers off the board; nothing is stopped">${svg('zzz')} Clear quiet sessions</button>` : ''}`,
      running: runI.map(runningCard).join('') + handS.map(a => sessionCard(a, kids(a))).join('') || empty('Nothing is running.'),
      'h-done': `<h2>Done</h2><span class="n">${doneNow.length + doneOld.length}</span>${hasQ && (doneNow.length || failNow.length) ? `<button type="button" data-clear="1" data-key="clear"${qbusy || O.down ? ' disabled' : ''} title="Takes done, failed and skipped items off the list; they stay in the vault">${svg('check')} Clear finished</button>` : ''}<span class="sub">the last 7 days, newest first</span>`,
      done: endedCol(doneNow.filter(wantI), doneOld.filter(wantI), liveK, 'Nothing finished yet.'),
      'h-failed': `<h2>Failed</h2><span class="n">${failNow.length}</span>${hasQ && (doneNow.length || failNow.length) ? `<button type="button" data-clear="1" data-key="clear2"${qbusy || O.down ? ' disabled' : ''} title="Takes done, failed and skipped items off the list; they stay in the vault">${svg('check')} Clear finished</button>` : ''}`,
      failed: endedCol(failNow.filter(wantI), failOld.filter(wantI), liveK, 'Nothing failed.'),
      pinfo: P ? (P.kind == 'project' ? panelProject(P.key) : panelTicket(P.key)) : '',
      pact: P && P.kind == 'ticket' ? panelActions(P.key) : ''
    };
    if (canQ) H.ctl = ctlHtml();
    const n = {needs: openQ.length + signedOut.length + need.length + bad.length + waitsT.length, ready: readyRows.filter(t => addable(t)).length, queued: queuedI.length,
      running: running.length + handS.filter(a => a.state == 'working').length, done: doneNow.length + doneOld.length, failed: failNow.length};
    if (!tab || !COLNAME[tab]) tab = n.needs ? 'needs' : 'running';
    H.tabs = TABS.map(k => `<button type="button" role="tab" data-tab="${k}" data-key="${esc('tab:' + k)}" aria-selected="${k === tab}">${esc(COLNAME[k])} <b>${n[k]}</b></button>`).join('');
    root.querySelectorAll('.col').forEach(c => c.classList.toggle('on', c.dataset.col === tab));
    panel.hidden = !P;

    // keep what the owner had open, focused and scrolled to across the rewrite
    const hold = force ? null : typingIn();
    const kept = new Set([...root.querySelectorAll('[data-region] details[open]')].map(d => d.dataset.k).filter(k => k && !k.startsWith('g:')));
    const ae = document.activeElement, fk = ae && root.contains(ae) && ae.dataset ? ae.dataset.key : null, y = window.scrollY;
    deferred = false;
    for (const k of Object.keys(H)) { if (hold && R[k] === hold) { deferred = true; continue; } put(k, H[k]); }
    root.querySelectorAll('[data-region] details').forEach(d => { if (kept.has(d.dataset.k)) d.open = true; });
    if (fk && document.activeElement !== ae) { const el = root.querySelector(`[data-key="${CSS.escape(fk)}"]`); if (el && !el.disabled) el.focus({preventScroll: true}); }
    if (window.scrollY !== y) window.scrollTo(0, y);
    if (O.down || RO) root.querySelectorAll('button[data-q]').forEach(b => { b.disabled = true; });
    qn.innerHTML = qnote || '';
    root.style.setProperty('--headh', head.offsetHeight + 'px');
    hint();
    return alerts;
  }

  // countdowns move every second between renders; under a minute they count seconds
  setInterval(() => {
    if (!S || O.down) return;
    const est = S.now + (Date.now() - gotAt) / 1000;
    root.querySelectorAll('.cd[data-dl]').forEach(el => {
      const left = num(el.dataset.dl) - est;
      if (left > 0) { el.textContent = dur(left) + ' left'; el.parentNode.classList.toggle('soon', left < 60); }
      else { el.textContent = 'deciding…'; el.removeAttribute('data-dl'); el.parentNode.classList.add('soon');
        const r = el.closest('[data-qr]'); if (r) r.querySelectorAll('button').forEach(b => { b.disabled = true; }); }
    });
  }, 1000);
  if (P && P.kind == 'ticket') loadDetail(P.key);

  return {render, target, esc, live(ok, word) { const l = $('.sb-live'); l.classList.toggle('off', !ok); l.lastChild.textContent = word; }};
};
})();
