/* sbhub_board.js: one renderer for the hub page (sbhub.html, served as /board.js) and the board
   widget in chat (sbhub_widget.html; sbhub_mcp.py inlines this file there). It fetches nothing.
   A host calls SBBoard(root, io) once, then board.render(state, opts) on every new state.
     io.answer(qid, option) / io.send(to, text) / io.unsend(id) -> Promise of null, or why it failed
     io.queue(path, body)  optional: post a queue write (/api/queue/..., /api/agents/scan) -> Promise of
                           the hub's answer, {ok, stale, queue, error, ...}; without it the queue is read-only.
                           Only set, move, options and remove_job carry the queue's version: the hub checks it
                           there; pause, agent, item_agent, job and scan are not about the list's order
     io.changed(tickets)   optional: refresh now (tickets true: the open tickets too);  io.page  true on the hub page
     opts: {live: [ok, text], down: banner text or '', skipQ: a question the host draws itself,
            canSend: false when this host cannot send, tickets: /api/tickets rows or null while unread}
   Every state value goes through esc; no inline handlers; nothing external is loaded.
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
.sb button:disabled{cursor:default;opacity:.5}
.sb button.chosen{opacity:1;outline:2px solid var(--ok);outline-offset:1px}
.sb :focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.sb select,.sb input:not([type=checkbox]),.sb textarea{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:4px 8px;min-height:30px;min-width:0;max-width:100%}
.sb input[type=checkbox]{width:16px;height:16px;margin:0;accent-color:var(--acc);flex:none;cursor:pointer}
.sb input[type=checkbox]:disabled{cursor:default}
.sb-head{display:flex;flex-direction:column;gap:6px;padding:8px 0 8px;background:var(--bg)}
.sb.page .sb-head{position:sticky;top:0;z-index:5;border-bottom:1px solid var(--line);margin-bottom:10px}
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
.sb-sep{width:1px;height:16px;background:var(--line);margin:0 2px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--mute);flex:none}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}
.sb .sb-fold{font-size:12px;padding:2px 8px;min-height:24px;color:var(--mute)}
.sb-cmp{display:grid;grid-template-columns:minmax(130px,230px) minmax(0,1fr) auto;gap:6px;align-items:start}
.sb-cmp select,.sb-cmp textarea{min-height:32px;padding:5px 8px;width:100%}
.sb-cmp textarea{resize:none;max-height:132px;line-height:1.4;display:block}
.sb-cmp .def{min-height:32px;padding:4px 14px}
.sb-cs{font-size:12px;color:var(--mute);min-height:16px;overflow-wrap:anywhere}
.sb-cs .err,.sb .err{color:var(--bad);font-weight:600}.sb-cs .okc,.sb .okc{color:var(--ok)}
.sb-banner{background:var(--warnbg);color:var(--warn);border:1px solid var(--warn);border-radius:var(--r);padding:6px 10px;font-weight:600}
.sb.down .sb-body{opacity:.6}
.sb h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:0 0 4px;font-weight:600}
.sb .mute{color:var(--mute);font-size:12px}
.sb .box{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);margin-bottom:6px}
.sb .box.q{border-color:var(--acc)}
.sb .sec{margin-bottom:14px}
.ic{flex:none;width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;color:var(--mute)}
.ic svg{width:15px;height:15px;vertical-align:0}
.ic.bad{color:var(--bad)}.ic.ok{color:var(--ok)}.ic.acc{color:var(--acc)}.ic.warn{color:var(--warn)}
.spin svg{animation:sbspin 1.4s linear infinite}
@keyframes sbspin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.spin svg{animation:none}}
.one{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
/* a session row: icon | title | what it is doing | meta | age | message button */
.r{display:grid;grid-template-columns:18px minmax(0,1.1fr) minmax(0,1fr) auto 3.2ch 28px;gap:0 8px;align-items:center;padding:3px 6px 3px 10px;min-height:32px;border-top:1px solid var(--line);cursor:pointer}
.r:hover{background:var(--hover)}
.r.sel{background:var(--accbg);box-shadow:inset 3px 0 var(--acc)}
.r.alert{box-shadow:inset 3px 0 var(--bad)}
.r .t{font-weight:600;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:1;line-clamp:1;overflow:hidden;min-width:0}
.r.calm .t{color:var(--mute);font-weight:500}
.r .nt{font-size:12px;color:var(--mute)}
.r .mt{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--mute);white-space:nowrap;min-width:0}
.r .age{font-size:12px;color:var(--mute);text-align:right;white-space:nowrap}
.sb .r button.to{width:28px;height:26px;min-height:0;padding:0;border-color:transparent;background:none;color:var(--mute);text-align:center;font-size:14px;line-height:1}
.r:hover button.to,.r.sel button.to{border-color:var(--line);color:var(--acc)}
.kids{display:flex;flex-wrap:wrap;gap:4px;padding:0 10px 5px 36px;min-width:0}
.r+.kids{border-top:0}
.chip{display:inline-flex;align-items:center;gap:3px;font-size:12px;padding:0 7px;border-radius:99px;border:1px solid var(--line);white-space:nowrap;max-width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;line-height:20px;background:var(--panel)}
.sb button.chip{min-height:0;padding:0 7px;font-size:12px;border-radius:99px;max-width:22ch;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:inline-block}
.sb button.chip.sel{border-color:var(--acc);color:var(--acc);background:var(--accbg)}
.chip.bad{border-color:var(--bad);color:var(--bad)}.chip.ok{color:var(--ok)}
.chip.warn{border-color:var(--warn);color:var(--warn);background:var(--warnbg);font-weight:600}
.chip.acc{border-color:var(--acc);color:var(--acc)}
.chip.msg{border-style:dashed;color:var(--acc);max-width:30ch}
.chip.msg span{overflow:hidden;text-overflow:ellipsis}
.sb .chip.msg button{min-height:0;padding:0 2px;border:0;background:none;color:inherit;font-size:13px;line-height:1}
.pips{display:inline-flex;gap:2px;align-items:center}
.pips i{width:6px;height:10px;border-radius:2px;border:1.5px solid var(--mute)}
.pips i.on{background:var(--ok);border-color:var(--ok)}.pips i.now{height:13px;border:2px solid var(--acc)}
.bar{display:inline-block;width:48px;height:6px;border-radius:3px;background:var(--line);overflow:hidden;vertical-align:middle}.bar i{display:block;height:100%;background:var(--ok)}
/* a project: a disclosure whose folded line still says what is going on */
.sb details>summary{list-style:none;cursor:pointer}
.sb details>summary::-webkit-details-marker{display:none}
.pj>summary{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:6px 10px;min-height:34px;min-width:0}
.pj>summary:hover{background:var(--hover)}
.sb details>summary::before{content:"";flex:none;width:6px;height:6px;border-right:1.5px solid var(--mute);border-bottom:1.5px solid var(--mute);transform:rotate(-45deg);margin:0 4px 0 1px;transition:transform .12s}
.sb details[open]>summary::before{transform:rotate(45deg)}
.pn{font-weight:650;overflow-wrap:anywhere}
.cnt{display:inline-flex;gap:6px;font-size:12px;color:var(--mute)}
.cnt>span{display:inline-flex;align-items:center;gap:2px}
.cnt b{font-weight:600;color:var(--ink)}
.pj .grow{flex:1}
.prov>summary{display:flex;align-items:center;gap:6px;padding:3px 10px 3px 36px;font-size:12px;color:var(--mute);border-top:1px solid var(--line)}
.pl{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;padding:3px 10px 3px 36px;font-size:12px}
.sb pre{margin:0;padding:0 10px 6px 50px;font:11px/1.4 var(--mono,ui-monospace,monospace);color:var(--mute);white-space:pre-wrap;overflow-wrap:anywhere}
.lgs>summary{padding:2px 10px 2px 36px;font-size:12px;color:var(--mute);display:flex;align-items:center}
/* questions and log lines */
.qr{padding:8px 10px;border-top:1px solid var(--line)}
.qr:first-child,.ln:first-child,.box>.r:first-child{border-top:0}
.qh{display:flex;gap:8px;align-items:flex-start}.qt{min-width:0;flex:1}
.qq{overflow-wrap:anywhere;margin-top:1px}
.opts{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 0 26px}
.sb .opts button small{font-size:11px;opacity:.85}
.qs{margin:4px 0 0 26px;display:flex;flex-wrap:wrap;gap:4px 10px;font-size:12px;color:var(--mute)}
.qs .soon{color:var(--warn);font-weight:600}.settled .qq{color:var(--mute)}
.cdw{display:inline-flex;align-items:center;gap:3px}
.ln{display:flex;gap:8px;align-items:flex-start;padding:5px 10px;border-top:1px solid var(--line);min-width:0}
.ln .lm{flex:1;min-width:0}
.ln .chip{max-width:40%}
.lg>summary{display:flex;align-items:center;gap:8px;padding:6px 10px}
.lg>summary h2{margin:0}
.lg[open]>summary{border-bottom:1px solid var(--line)}
.empty{padding:12px;color:var(--mute)}
/* tonight's queue and what is available */
.sb-qh{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin-bottom:4px}
.sb-qh h2{margin:0}
.qctl{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;padding:8px 10px}
.qctl label{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--mute)}
.qctl select{max-width:30ch}
.sb .qctl button{display:inline-flex;align-items:center;gap:5px}
.sb-qn{font-size:12px;min-height:16px;margin:0 0 4px;overflow-wrap:anywhere}
.ql{list-style:none;margin:0 0 6px;padding:0}
.qi{display:grid;grid-template-columns:2.4ch 18px minmax(0,1fr) auto auto;gap:2px 8px;align-items:center;padding:4px 6px 4px 8px;border-top:1px solid var(--line);min-height:34px}
.qi:first-child{border-top:0}
.qi[draggable=true]{cursor:grab}
.qi.drag{opacity:.45}.qi.over{box-shadow:inset 0 2px var(--acc)}
.qi.running{background:var(--accbg)}
.qi .qn{color:var(--mute);font-size:12px;text-align:right}
.qi .t{font-weight:600;overflow-wrap:anywhere;min-width:0}
.qi .qm{grid-column:3;display:flex;flex-wrap:wrap;gap:3px 8px;align-items:center;font-size:12px;color:var(--mute);min-width:0}
.qi .qa{grid-column:4;grid-row:1/span 2}
.qi .qa select{font-size:12px;min-height:26px;padding:2px 6px;max-width:20ch}
.qi .mv{grid-column:5;grid-row:1/span 2;display:flex;gap:2px}
.sb .mv button{width:28px;height:26px;min-height:0;padding:0;display:inline-flex;align-items:center;justify-content:center;color:var(--mute)}
.av{display:grid;grid-template-columns:18px minmax(0,1fr) auto;gap:2px 8px;align-items:center;padding:4px 10px;border-top:1px solid var(--line);min-height:32px}
.pj>.av:nth-child(2){border-top:0}
.av .t{overflow-wrap:anywhere;min-width:0}
.av .why{grid-column:2/-1;font-size:12px;color:var(--mute);overflow-wrap:anywhere}
.av.off .t{color:var(--mute)}
.stc{font-size:11.5px;padding:0 7px;border-radius:99px;border:1px solid var(--line);white-space:nowrap;line-height:19px;color:var(--mute)}
.stc.ready{border-color:var(--ok);color:var(--ok)}.stc.blocked{border-color:var(--warn);color:var(--warn)}
.stc.waits{border-color:var(--acc);color:var(--acc)}.stc.ended{border-color:var(--bad);color:var(--bad)}
.jobf>summary{display:flex;align-items:center;gap:6px;padding:6px 10px;font-weight:600}
.sb-job{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:4px 10px 10px}
.sb-job label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--mute);min-width:0}
.sb-job .wide{grid-column:1/-1}
.sb-job textarea{resize:vertical;min-height:72px;line-height:1.4}
.sb-job .go{grid-column:1/-1;display:flex;flex-wrap:wrap;align-items:center;gap:8px}
@media(max-width:599px){
  .sb-stats{flex-basis:100%;order:3}.sb .sb-fold{margin-left:auto}
  .sb-cmp{grid-template-columns:minmax(0,1fr) auto}.sb-cmp select{grid-column:1/-1}
  .r{grid-template-columns:18px minmax(0,1fr) auto 28px;row-gap:1px;align-items:start;padding:5px 6px 5px 10px}
  .r .ic{grid-row:1/span 3}
  .r .t{grid-column:2;-webkit-line-clamp:2;line-clamp:2}
  .r .age{grid-column:3;grid-row:1}.r button.to{grid-column:4;grid-row:1/span 2}
  .r .nt,.r .mt{grid-column:2/4}.r .mt{flex-wrap:wrap}
  .kids{padding-left:36px}
  .opts{margin-left:0}.opts button{flex:1 1 100%;min-height:42px}.qs{margin-left:0}
  .qi{grid-template-columns:2.4ch 18px minmax(0,1fr) auto;align-items:start}
  .qi .qa{grid-column:3/-1;grid-row:auto}.qi .qa select{max-width:100%;width:100%}
  .qi .mv{grid-column:4;grid-row:1}
  .sb .mv button{width:36px;height:34px}
  .qctl label,.qctl select{width:100%}.qctl label select{flex:1}
  .sb-job{grid-template-columns:minmax(0,1fr)}
}`;

// Tabler Icons (tabler.io), MIT licence: the outline set's path data, drawn by svg() below
const ICON = {
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
const NIGHT = 18 * 3600;  // "tonight": what ended in the last 18 hours
const tkey = t => String(t.map) + '#' + parseInt(t.num, 10);
// a map's wayfinder project, as the hub names it: the folder prefix, else the name before a dash
const projOf = m => { const p = String(m || '').split('/'); return p.length > 1 ? p[0] : p[0].split('-')[0]; };
const ENDED = {done: ['circle-check', 'done', 'ok'], failed: ['x', 'failed', 'bad'], skipped: ['ban', 'skipped', 'warn']};
const firstLine = t => String(t || '').split('\n').map(x => x.trim()).find(Boolean) || '';
const agyWords = 'Antigravity: emergencies and mechanical work';

window.SBBoard = function (root, io) {
  if (!document.getElementById('sb-css')) {
    const st = document.createElement('style'); st.id = 'sb-css'; st.textContent = STYLE; document.head.appendChild(st);
  }
  root.classList.add('sb'); if (io.page) root.classList.add('page');
  const canQ = typeof io.queue == 'function';
  root.innerHTML = `<div class="sb-head">
<div class="sb-bar"><span class="sb-brand">sb hub</span><span class="sb-live off"><i></i><span>connecting</span></span><span class="sb-stats"></span><button type="button" class="sb-fold" hidden>Collapse all</button></div>
<div class="sb-banner" role="alert" hidden></div>
<form class="sb-cmp" autocomplete="off"><select class="sb-to" aria-label="Send to"><option value="">To…</option></select><textarea class="sb-msg" rows="1" maxlength="4000" aria-label="Message" placeholder="Message a session or worker · Enter sends"></textarea><button type="submit" class="def">Send</button></form>
<div class="sb-cs" aria-live="polite"></div></div><div class="sb-body">
<div data-region="needs"></div><div data-region="run"></div>
<section class="sec" data-region-wrap="queue"><div data-region="queue"></div>${canQ ? `
<details class="box jobf" data-k="jobform"><summary>${svg('terminal-2')} New job <span class="mute">a one-off prompt, run headless like a ticket</span></summary>
<form class="sb-job" autocomplete="off">
<label class="wide">Project<input name="project" list="sb-projects" required maxlength="500" placeholder="a wayfinder project or a path to a git checkout, e.g. sb-workflow or /Users/me/code/app"></label>
<datalist id="sb-projects"></datalist>
<label class="wide">Prompt<textarea name="prompt" rows="4" required maxlength="20000" placeholder="What the agent should do; it runs alone, with no one to ask"></textarea></label>
<label>Agent<select name="agent"></select></label>
<label>Model<input name="model" maxlength="80" placeholder="optional, e.g. opus"></label>
<label>Name<input name="name" maxlength="80" placeholder="optional; names its run folder"></label>
<div class="go"><button type="submit" class="def">Queue the job</button><span class="sb-jn mute" aria-live="polite"></span></div>
</form></details>` : ''}</section>
<div data-region="avail"></div><div data-region="log"></div></div>`;
  const $ = c => root.querySelector(c);
  const body = $('.sb-body'), sel = $('.sb-to'), msg = $('.sb-msg'), cs = $('.sb-cs'), form = $('.sb-cmp'), fold = $('.sb-fold');
  const R = {}; body.querySelectorAll('[data-region]').forEach(el => { R[el.dataset.region] = el; });
  const job = $('.sb-job'), jn = $('.sb-jn');
  const collapsed = loadSet('sbhub.collapsed'), sending = {}, fails = {};
  let S = null, O = {}, gotAt = 0, csNote = null, deferred = false, qbusy = false, qnote = null, dragKey = null;
  const lastH = {};  // what each region was last given: an unchanged region is not rewritten

  const agentOf = id => { if (!S || typeof id != 'string') return null; return own(S.agents, own(S.aliases, id) || id) || null; };
  const who = id => { const a = agentOf(id); return a ? lbl(a) : short(id); };
  const whereOf = id => { const a = agentOf(id); return a ? proj(a.project) : ''; };

  // ---- the queue, read from S and the ticket rows ----
  const Q = () => (S && S.queue && typeof S.queue == 'object') ? S.queue : null;
  const items = () => { const q = Q(); return q && Array.isArray(q.items) ? q.items.filter(i => i && typeof i == 'object') : []; };
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
  const blockersOf = t => (Array.isArray(t.blocked_by_open) ? t.blocked_by_open : []).map(b => typeof b == 'number' ? String(t.map) + '#' + b : null);
  const bTitle = (t, b) => { const k = typeof b == 'number' ? String(t.map) + '#' + b : null, o = k && tOf(k); return o ? String(o.title) : typeof b == 'number' ? 'ticket ' + b : String(b); };
  function agentState(name, e) {
    if (e.login == 'expired') return ['out', 'sign in'];
    const run = items().find(i => i.state == 'running' && i.runner === name);
    if (run) return ['run', 'running ' + titleOf(run)];
    if (num(e.limited_until) > S.now) return ['lim', 'limited until ' + hm(e.limited_until)];
    return ['', 'free'];
  }
  // an account's 5-hour use and reset, and what it learned a ticket costs, from the hub's readings
  const usageOf = e => { const u = e.usage && typeof e.usage == 'object' ? e.usage : null; return u && num(u.five_hour_resets) > S.now ? `${Math.round(100 * num(u.five_hour))}% · resets ${hm(u.five_hour_resets)}` : ''; };
  const costsOf = e => Object.entries(e.costs && typeof e.costs == 'object' ? e.costs : {}).filter(([, c]) => c && typeof c == 'object').map(([t, c]) => `${t} about ${Math.round(100 * num(c.avg))}%`).join(', ');
  function ends() {
    const its = items(), run = its.filter(i => i.state == 'running'), wait = its.filter(i => i.state == 'queued');
    if (!run.length && !wait.length) return 0;
    const from = run.length ? Math.min(...run.map(i => num(i.started) || S.now)) : S.now;
    return Math.max(from + EST * (run.length + wait.length), S.now + EST * wait.length);
  }

  function prog(d, t) {
    const label = `${d} of ${t} tickets done`;
    if (t > 20) { const pc = Math.max(0, Math.min(100, 100 * d / t)); return `<span title="${esc(label)}"><span class="bar"><i style="width:${pc}%"></i></span> ${d}/${t}</span>`; }
    let h = ''; for (let i = 0; i < t; i++) h += `<i class="${i < d ? 'on' : i == d ? 'now' : ''}"></i>`;
    return `<span title="${esc(label)}"><span class="pips" role="img" aria-label="${esc(label)}">${h}</span> ${d}/${t}</span>`;
  }
  function kid(a) {
    const [ic] = act(a), [g, w] = stOf(a.state), c = rank(a) == 0 ? 'bad' : a.state == 'done' ? 'ok' : '';
    const tip = `${lbl(a)} · ${w} · ${a.note || ''} · active ${ago(S.now, a.at)}`;
    if (a.state == 'done') return `<span class="chip ok" dir="auto" title="${esc(tip)}"><span role="img" aria-label="${esc(w)}">${svg(g)}</span> ${esc(lbl(a))}</span>`;
    return `<button type="button" class="chip ${c}${sel.value === a.agent ? ' sel' : ''}" data-to="${esc(a.agent)}" data-key="${esc('to:' + a.agent)}" dir="auto" title="${esc('Message this worker · ' + tip)}"><span role="img" aria-label="${esc(w)}">${svg(g)}</span> ${esc(lbl(a))}${ic ? ' ' + svg(ic) : ''}</button>`;
  }
  const queuedFor = id => Object.entries(S.messages || {}).filter(([, m]) => m && m.to === id && m.delivered == null && !m.lost);
  function qchip([mid, m]) {
    return `<span class="chip msg" dir="auto" title="${esc('Queued ' + ago(S.now, m.at) + ': ' + m.text)}">${svg('mail')} <span>${esc(m.text)}</span><button type="button" data-unsend="${esc(mid)}" data-key="${esc('un:' + mid)}" aria-label="Take back this message" title="Take back">${svg('x')}</button></span>`;
  }
  function row(a, kids, inProj) {
    const id = a.agent, [ti, txt] = act(a), t = num(a.total), silent = S.now - num(a.at), name = lbl(a), pn = proj(a.project), meta = [];
    const turn = a.state == 'your turn' && a.asked;
    const line = turn ? `You asked: “${a.asked}”` : txt;
    if (pn && !inProj) meta.push(`<span class="one" title="${esc(a.project)}">${esc(pn)}</span>`);
    if (a.ticket && a.role != 'worker' && tnum(a.ticket) !== name) meta.push(`<span class="one" style="max-width:22ch" dir="auto" title="ticket: ${esc(a.ticket)}">${svg('ticket')} ${esc(tnum(a.ticket))}</span>`);
    if (t > 0) meta.push(prog(num(a.done), t));
    if (a.state == 'working' && silent >= 600) meta.push(`<span class="chip warn">${svg('alert-triangle')} quiet for ${esc(dur(silent))}</span>`);
    else if (a.state == 'working' && num(a.since) && S.now - num(a.since) >= 60) meta.push(`<span title="working since">${esc(dur(S.now - num(a.since)))}</span>`);
    const q = queuedFor(id), cls = (a.state == 'idle' || a.state == 'done' ? ' calm' : '') + (rank(a) == 0 ? ' alert' : '') + (sel.value === id ? ' sel' : '');
    return `<div class="r${cls}" data-row="${esc(id)}">${stIc(a.state)}`
      + `<span class="t" dir="auto" title="${esc(name + (a.asked ? '\nYou asked: ' + a.asked : ''))}">${esc(name)}</span>`
      + `<span class="nt one" dir="auto" title="${esc(line)}">${!turn && ti ? svg(ti) + ' ' : ''}${esc(line)}</span>`
      + `<span class="mt">${meta.join('')}</span>`
      + `<span class="age" title="active ${esc(ago(S.now, a.at))}">${esc(dur(silent))}</span>`
      + `<button type="button" class="to" data-to="${esc(id)}" data-key="${esc('to:' + id)}" aria-label="${esc('Message ' + name)}" title="Message this session">${svg('mail')}</button></div>`
      + (kids.length || q.length ? `<div class="kids">${kids.map(kid).join('')}${q.map(qchip).join('')}</div>` : '');
  }
  function qrow(id, q) {
    const decided = q.answer != null, left = num(q.deadline) - S.now, pending = !decided && left <= 0, busy = own(sending, id);
    const off = decided || pending || !!O.down || busy != null, pn = whereOf(q.agent);
    const btn = (o, i) => `<button type="button" data-q="${esc(id)}" data-i="${i}" data-key="${esc('q:' + id + ':' + i)}" class="${o == q.default ? 'def' : ''}${decided && o == q.answer ? ' chosen' : ''}"${off ? ' disabled' : ''} dir="auto">${busy === i ? 'Sending…' : (decided && o == q.answer ? svg('check') + ' ' : '') + esc(o)}${o == q.default ? '<small> · default</small>' : ''}</button>`;
    const status = decided ? `<span>${q.by == 'default' ? 'Default applied' : q.by == 'you' ? 'You chose this' : 'Chosen by ' + esc(q.by)} · moving to the log</span>`
      : pending ? '<span class="soon">deciding…</span>'
      : `<span class="cdw${left < 60 ? ' soon' : ''}" title="the default applies then">${svg('clock')}<span class="cd" data-dl="${num(q.deadline)}">${esc(dur(left))} left</span></span>`;
    return `<div class="qr${decided ? ' settled' : ''}" data-qr="${esc(id)}"><div class="qh">${icon('help-circle', 'question', 'acc')}<div class="qt">`
      + `<div class="mute one"><b dir="auto">${esc(who(q.agent))}</b>${pn ? ' · ' + esc(pn) : ''} · asked ${esc(ago(S.now, q.asked))}</div>`
      + `<div class="qq" dir="auto">${esc(q.q)}</div></div></div>`
      + `<div class="opts">${(Array.isArray(q.options) ? q.options : []).map(btn).join('')}</div>`
      + `<div class="qs">${status}${!decided && own(fails, id) ? `<span class="err" role="alert">Not sent: ${esc(fails[id])}</span>` : ''}</div></div>`;
  }
  function widget(w) {
    const label = esc(w.label);
    if (w.kind == 'status') return `<span class="chip" title="${label}">${dot(w.level)} ${esc(String(w.value).slice(0, 40))}</span>`;
    if (w.kind == 'progress') { const v = num(w.value), m = num(w.max), pc = Math.max(0, Math.min(100, 100 * v / (m || 1)));
      return `<span class="bar" title="${label} ${v}/${m}"><i style="width:${pc}%"></i></span><span class="mute">${v}/${m}</span>`; }
    if (w.kind == 'counts' && w.items && typeof w.items == 'object') return Object.entries(w.items).map(([k, v]) => `<span class="chip ${k == 'fail' && num(v) ? 'bad' : k == 'pass' ? 'ok' : ''}" title="${label}">${k == 'pass' ? `<span role="img" aria-label="passed">${svg('circle-check')}</span>` : k == 'fail' ? `<span role="img" aria-label="failed">${svg('x')}</span>` : esc(k)} ${esc(v)}</span>`).join('');
    return '';
  }
  const wlist = p => Array.isArray(p.widgets) ? p.widgets.filter(w => w && typeof w == 'object') : [];
  // the folded line of a project: branch, uncommitted count, test results, anything not ok
  function digest(list) {
    let h = '';
    for (const p of list) for (const w of wlist(p)) {
      if (w.kind == 'status' && w.label == 'Branch') h += `<span class="chip" title="branch">${svg('git-branch')} ${esc(String(w.value).slice(0, 30))}</span>`;
      else if (w.kind == 'status' && w.label == 'Uncommitted files') h += num(w.value) ? `<span class="chip warn" title="uncommitted files">${esc(w.value)} uncommitted</span>` : '';
      else if (w.kind == 'counts') h += widget(w);
      else if (w.kind == 'status' && (w.level == 'bad' || w.level == 'warn')) h += `<span class="chip ${w.level == 'bad' ? 'bad' : ''}" title="${esc(p.title)}">${dot(w.level)} ${esc(w.label)}</span>`;
    }
    return h;
  }
  function provider(p, path) {
    const ws = wlist(p), logs = ws.filter(w => w.kind == 'log' && Array.isArray(w.lines));
    return `<div class="pl">${icon(own(PICON, p.icon) || 'tool', p.title)}<span class="mute">${esc(p.title)}</span>${ws.map(widget).join('')}</div>`
      + logs.map(l => { const k = path + '|' + p.title + '|' + l.label; return `<details class="lgs" data-k="${esc(k)}"><summary data-key="${esc('d:' + k)}">${esc(l.label)}</summary><pre>${l.lines.map(esc).join('\n')}</pre></details>`; }).join('');
  }
  function counts(list) {
    const c = {}; for (const a of list) c[a.state] = (c[a.state] || 0) + 1;
    return Object.keys(ST).filter(k => c[k]).map(k => `<span title="${esc(plural(c[k], 'session') + ' ' + ST[k][1])}">${svg(ST[k][0])}<b>${c[k]}</b></span>`).join('');
  }
  function msgLine([, m]) {
    const st = m.delivered != null ? `delivered ${HOW[m.how] || ''} · ${ago(S.now, m.delivered)}` : m.lost ? '<span class="err">not delivered: the session ended</span>' : `queued · ${ago(S.now, m.at)}`;
    return `<div class="ln">${icon('mail', 'message')}<div class="lm"><div class="one" dir="auto" title="${esc(m.text)}">${esc(m.text)}</div><div class="mute one">to <b dir="auto">${esc(who(m.to))}</b>${whereOf(m.to) ? ' · ' + esc(whereOf(m.to)) : ''} · ${st}</div></div></div>`;
  }

  // ---- tonight's queue ----
  const agentOpts = (chosen, first) => first + installed().map(([n, e]) => {
    const [, w] = agentState(n, e);
    return `<option value="${esc(n)}"${n === chosen ? ' selected' : ''}>${esc(n)}${e.kind == 'agy' ? ' (' + agyWords + ')' : ''}${w == 'free' ? '' : ' · ' + esc(w)}</option>`;
  }).join('');
  function queueRow(i, n, qt, off) {
    const t = tOf(i.key), title = titleOf(i), running = i.state == 'running', isT = i.kind == 'ticket', q = Q();
    const at = isT ? qt.indexOf(i.key) : -1, meta = [];
    const pj = projItem(i);
    if (pj) meta.push(`<span title="${esc(t ? t.map_title || t.map : i.kind == 'job' ? i.project : '')}">${esc(pj)}</span>`);
    if (i.kind == 'job') meta.push(`<span class="one" style="max-width:40ch" dir="auto" title="${esc(i.prompt)}">${esc(firstLine(i.prompt))}</span>`);
    if (t) { const bs = (Array.isArray(t.blocked_by_open) ? t.blocked_by_open : []).map(b => bTitle(t, b)); if (bs.length) meta.push(`<span dir="auto">after ${esc(bs.join(', '))}</span>`); }
    const tier = i.model || (t && t.tier);
    if (tier) meta.push(`<span class="chip" title="model">${esc(tier)}</span>`);
    if (running) meta.push(`<span class="chip acc">${svg('robot')} on ${esc(i.runner || i.agent || q.agent || '')} · ${esc(dur(S.now - num(i.started)))}</span>`);
    else if (i.agent) meta.push(`<span class="chip acc" title="this item's own agent">${svg('robot')} ${esc(i.agent)}</span>`);
    if (i.tries && !running) meta.push(`<span class="chip warn">second try</span>`);
    if (i.note && running) meta.push(`<span class="one" dir="auto" title="${esc(i.note)}">${esc(firstLine(i.note))}</span>`);
    meta.push(`<span title="the estimate">1.5 h</span>`);
    const lead = running ? icon('loader-2', 'running', 'acc spin')
      : isT ? `<input type="checkbox" checked data-tick="${esc(i.key)}" data-key="${esc('tick:' + i.key)}" aria-label="${esc('Run tonight: ' + title)}" title="Untick to leave it out tonight"${off ? ' disabled' : ''}>`
      : icon('terminal-2', 'a one-off job');
    const pick = !running && canQ && installed().length ? `<span class="qa"><select data-ia="${esc(i.key)}" data-key="${esc('ia:' + i.key)}" aria-label="${esc('Agent for ' + title)}"${off ? ' disabled' : ''}>${agentOpts(i.agent, `<option value="">night's agent${q.agent ? ' (' + esc(q.agent) + ')' : ''}</option>`)}</select></span>` : '<span class="qa"></span>';
    const rm = !running && !isT && canQ ? `<span class="mv"><button type="button" data-rmjob="${esc(i.key)}" data-key="${esc('rm:' + i.key)}" aria-label="${esc('Remove the job: ' + title)}" title="Remove this job"${off ? ' disabled' : ''}>${svg('x')}</button></span>` : '';
    const mv = rm || (!running && isT && canQ ? `<span class="mv"><button type="button" data-up="${esc(i.key)}" data-key="${esc('up:' + i.key)}" aria-label="${esc('Move up: ' + title)}" title="Move up"${off || at <= 0 ? ' disabled' : ''}>${svg('chevron-up')}</button><button type="button" data-dn="${esc(i.key)}" data-key="${esc('dn:' + i.key)}" aria-label="${esc('Move down: ' + title)}" title="Move down"${off || at < 0 || at >= qt.length - 1 ? ' disabled' : ''}>${svg('chevron-down')}</button></span>` : '<span class="mv"></span>');
    return `<li class="qi${running ? ' running' : ''}" data-qk="${esc(i.key)}"${!running && isT && canQ && !off ? ' draggable="true"' : ''}>`
      + `<span class="qn">${n}</span>${lead}<span class="t" dir="auto">${esc(title)}</span>${pick}${mv}<span class="qm">${meta.join('')}</span></li>`;
  }
  function queueSection() {
    const q = Q();
    if (!q) return '';
    const its = items(), live = its.filter(i => i.state == 'running' || i.state == 'queued');
    const qt = its.filter(i => i.kind == 'ticket' && i.state == 'queued').map(i => i.key);
    const off = !canQ || qbusy || !!O.down, end = ends(), waiting = its.filter(i => i.state == 'queued').length;
    let sum = waiting ? `${plural(waiting, 'item')} queued · about 1.5 h each` : 'nothing queued';
    if (live.length) sum += q.paused ? ' · paused: nothing starts until you resume' : ` · ends about ${hm(end)}`;
    if (q.stop_at) sum += ` · stops at ${hm(q.stop_at)}`;
    let h = `<div class="sb-qh"><h2>Tonight's queue</h2><span class="mute">${esc(sum)}</span></div>`;
    if (canQ) {
      const agents = installed();
      const stopV = q.stop_at ? new Date(num(q.stop_at) * 1000).toTimeString().slice(0, 5) : '';
      h += `<div class="box qctl">`
        + `<button type="button" class="${q.paused ? 'def' : ''}" data-qact="pause" data-key="qp"${off ? ' disabled' : ''}>${q.paused ? svg('player-play') + ' Resume the queue' : svg('player-pause') + ' Pause the queue'}</button>`
        + (agents.length ? `<label>Agent for tonight<select data-qa="1" data-key="qa"${off ? ' disabled' : ''}>${agentOpts(q.agent, q.agent ? '' : '<option value="" selected disabled>Pick an agent</option>')}</select></label>`
          : '<span class="mute">No agents found yet.</span>')
        + `<button type="button" data-qact="scan" data-key="scan"${off ? ' disabled' : ''}>${svg('search')} Scan for agents</button>`
        + `<label>Stop at<input type="time" data-qs="1" data-key="qs" value="${esc(stopV)}"${off ? ' disabled' : ''}></label>`
        + `<label><input type="checkbox" data-qf="1" data-key="qf"${q.final_review ? ' checked' : ''}${off ? ' disabled' : ''}> Final review after the last ticket</label>`
        + `</div>`;
    }
    h += `<div class="sb-qn" aria-live="polite">${qnote || ''}</div>`;
    h += live.length ? `<ol class="box ql">${live.map((i, n) => queueRow(i, n + 1, qt, off)).join('')}</ol>`
      : `<div class="box"><div class="empty">Nothing queued for tonight.${canQ ? ' Tick tickets under Available, or queue a job.' : ''}</div></div>`;
    return h;
  }
  // can a ticket be ticked: ready, or blocked by tickets that are queued or can be ticked too
  const doneKeys = () => new Set(items().filter(i => i.kind == 'ticket' && i.state == 'done').map(i => i.key));
  function addable(t, seen) {
    if (doneKeys().has(tkey(t))) return false;
    if (t.state == 'ready') return true;
    if (t.state != 'blocked') return false;
    seen = seen || new Set([tkey(t)]);
    const live = new Set(items().filter(i => i.state == 'queued' || i.state == 'running').map(i => i.key));
    return blockersOf(t).every(k => { if (!k) return false; if (live.has(k)) return true; const o = tOf(k);
      if (!o || seen.has(k)) return false; seen.add(k); return addable(o, seen); });
  }
  function withBlockers(k, out) {
    if (out.includes(k)) return out;
    const t = tOf(k), live = new Set(items().filter(i => i.state == 'queued' || i.state == 'running').map(i => i.key));
    if (t) for (const b of blockersOf(t)) if (b && !live.has(b)) withBlockers(b, out);
    out.push(k); return out;
  }
  function availSection() {
    const T = tickets();
    if (!Q()) return '';
    let h = '<section class="sec"><h2>Available</h2>';
    if (!T) return h + '<div class="box"><div class="empty">Reading the maps…</div></div></section>';
    const its = items(), live = new Set(its.filter(i => i.state == 'queued' || i.state == 'running').map(i => i.key));
    const ended = new Map(its.filter(i => i.kind == 'ticket' && ENDED[i.state]).map(i => [i.key, i]));
    const rest = T.filter(t => !live.has(tkey(t))), groups = new Map(), off = !canQ || qbusy || !!O.down;
    for (const t of rest) { const p = projOf(t.map); if (!groups.has(p)) groups.set(p, []); groups.get(p).push(t); }
    if (!groups.size) return h + '<div class="box"><div class="empty">No other open tickets: everything open is queued.</div></div></section>';
    for (const [p, list] of [...groups].sort((x, y) => x[0].localeCompare(y[0]))) {
      const k = 'p:av:' + p, ready = list.filter(t => t.state == 'ready').length;
      h += `<details class="box pj" data-k="${esc(k)}"${collapsed.has(k) ? '' : ' open'}><summary data-key="${esc('d:' + k)}"><span class="pn" dir="auto">${esc(p)}</span><span class="cnt"><span>${plural(list.length, 'open ticket')}</span>${ready ? `<span><b>${ready}</b>&nbsp;ready</span>` : ''}</span></summary>`;
      for (const t of list) {
        const key = tkey(t), e = ended.get(key), can = addable(t), st = String(t.state || '');
        const cls = e ? 'ended' : st == 'ready' ? 'ready' : st == 'blocked' ? 'blocked' : st == 'waits for you' ? 'waits' : '';
        const word = e ? `${e.state} ${ago(S.now, e.ended)}` : st;
        const why = e ? (e.state == 'done' ? (e.commit ? 'commit ' + String(e.commit).slice(0, 9) : '') : (firstLine(e.note) || 'no reason recorded') + (can ? ' · tick it to run it again' : ''))
          : st == 'blocked' && can ? t.reason + ' · ticking it also ticks what it waits on'
          : st == 'blocked' ? t.reason + ', which cannot run tonight' : t.reason && t.reason != st ? t.reason : '';
        h += `<div class="av${can ? '' : ' off'}">`
          + (canQ ? `<input type="checkbox" data-add="${esc(key)}" data-key="${esc('add:' + key)}" aria-label="${esc('Add to tonight: ' + t.title)}"${can && !off ? '' : ' disabled'}>` : '<span></span>')
          + `<span class="t" dir="auto" title="${esc(t.map_title || t.map)}">${esc(t.title)}</span><span class="stc ${cls}">${esc(word)}</span>`
          + (why ? `<span class="why" dir="auto">${esc(why)} · ${esc(t.map_title || t.map)}</span>` : `<span class="why" dir="auto">${esc(t.map_title || t.map)}</span>`)
          + `</div>`;
      }
      h += '</details>';
    }
    return h + '</section>';
  }
  function runningRows() {
    return items().filter(i => i.state == 'running').map(i => {
      const pj = projItem(i);
      return `<div class="r" style="cursor:default">${icon('loader-2', 'running', 'acc spin')}<span class="t" dir="auto" title="${esc(titleOf(i))}">${esc(titleOf(i))}</span>`
        + `<span class="nt one" dir="auto" title="${esc(i.note || '')}">${esc(firstLine(i.note) || 'starting')}</span>`
        + `<span class="mt">${pj ? `<span class="one">${esc(pj)}</span>` : ''}<span class="chip acc">${svg('robot')} ${esc(i.runner || '')}</span></span>`
        + `<span class="age" title="running since ${esc(hm(i.started))}">${esc(dur(S.now - num(i.started)))}</span><span></span></div>`;
    }).join('');
  }
  function logLines() {
    return items().filter(i => ENDED[i.state] && S.now - num(i.ended) < NIGHT).sort((x, y) => num(y.ended) - num(x.ended)).map(i => {
      const [g, w, c] = ENDED[i.state], pj = projItem(i);
      const what = i.state == 'done' && i.commit ? `<span class="chip ok" title="${esc(i.commit)}">${svg('git-commit')} ${esc(String(i.commit).slice(0, 9))}</span>` : '';
      const note = i.state == 'done' && i.kind == 'job' && i.result ? 'result in ' + i.result : i.state != 'done' ? firstLine(i.note) || 'no reason recorded' : '';
      return `<div class="ln">${icon(g, w, c)}<div class="lm"><div class="one" dir="auto" title="${esc(titleOf(i))}">${esc(titleOf(i))}</div><div class="mute" dir="auto">${esc(w)}${pj ? ' · ' + esc(pj) : ''} · ${esc(ago(S.now, i.ended))}${note ? ' · ' + esc(note) : ''}</div></div>${what}</div>`;
    }).join('');
  }

  // the "To" list: sessions by project, each followed by its live workers
  function fillTo(tops, kids) {
    if (document.activeElement === sel) return; // rebuilding an open list closes it
    const v = sel.value, groups = new Map();
    for (const a of tops) { const k = proj(a.project) || 'No project'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(a); }
    const frag = document.createDocumentFragment(), first = document.createElement('option');
    first.value = ''; first.textContent = 'To…'; frag.appendChild(first);
    for (const [name, list] of groups) {
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
  // the job form is drawn once (what is typed survives every render); its lists follow the state
  function fillJob() {
    if (!job) return;
    const a = job.elements.agent, dl = $('#sb-projects');
    if (document.activeElement !== a) {
      const v = a.value, q = Q();
      a.innerHTML = agentOpts(null, `<option value="">night's agent${q && q.agent ? ' (' + esc(q.agent) + ')' : ''}</option>`);
      a.value = [...a.options].some(o => o.value === v) ? v : '';
    }
    const T = tickets(), ps = new Set(T ? T.map(t => projOf(t.map)) : []);
    const want = [...ps].sort().map(p => `<option value="${esc(p)}"></option>`).join('');
    if (dl.innerHTML !== want) dl.innerHTML = want;
    job.querySelector('button[type=submit]').disabled = !!O.down;
  }
  function hint() {
    if (csNote) { cs.innerHTML = csNote; return; }
    const a = agentOf(sel.value);
    cs.textContent = O.canSend === false ? 'This view cannot send; use the hub page.' : a ? `To ${lbl(a)} · ${whenFor(a)}` : 'Pick a session (the mail button on its row) or a worker chip, then type.';
  }
  function target(id) {
    sel.value = [...sel.options].some(o => o.value === id) ? id : '';
    csNote = null; hint();
    body.querySelectorAll('[data-row]').forEach(r => r.classList.toggle('sel', r.dataset.row === sel.value));
    body.querySelectorAll('button.chip[data-to]').forEach(b => b.classList.toggle('sel', b.dataset.to === sel.value));
  }
  function grow() { msg.style.height = 'auto'; msg.style.height = Math.min(msg.scrollHeight + 2, 132) + 'px'; }

  async function answer(qid, i) {
    const q = S && own(S.questions, qid);
    if (!q || !Array.isArray(q.options) || i >= q.options.length || q.answer != null || own(sending, qid) != null) return;
    delete fails[qid]; sending[qid] = i; render(S, O, true);
    const why = O.down ? 'hub not reachable' : await io.answer(qid, q.options[i]).catch(e => String(e));
    delete sending[qid];
    if (why) fails[qid] = why; else { q.answer = q.options[i]; q.by = 'you'; q.answered = S.now; }
    render(S, O, true); if (io.changed) io.changed();
  }
  async function send(e) {
    e.preventDefault();
    const to = sel.value, text = msg.value.trim();
    if (O.canSend === false) return;
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
  // one queue write: it carries the version; a stale answer redraws from the hub's queue
  const CHECKED = new Set(['/api/queue/set', '/api/queue/move', '/api/queue/options', '/api/queue/remove_job']);
  async function qwrite(path, data, done) {
    const q = Q();
    if (!canQ || qbusy || O.down || !q) {  // not sent: undo what the click already changed (a disabled box)
      for (const k of Object.keys(lastH)) delete lastH[k];
      if (S) render(S, O, true);
      return null;
    }
    qbusy = true; qnote = '<span class="mute">Saving…</span>'; render(S, O, true);
    const out = await Promise.resolve(io.queue(path, CHECKED.has(path) ? {...data, version: q.version} : data)).catch(e => ({ok: false, error: String(e)})) || {};
    qbusy = false;
    if (out.queue && typeof out.queue == 'object' && S) S.queue = out.queue;
    if (out.installed && typeof out.installed == 'object' && S) S.installed = out.installed;
    qnote = out.stale ? '<span class="err" role="alert">Not done: the list changed, try again.</span>'
      : out.ok === false || out.error ? `<span class="err" role="alert">Not done: ${esc(out.error || 'the hub refused it')}</span>`
      : done ? `<span class="okc">${svg('check')} ${esc(done)}</span>` : null;
    render(S, O, true);
    const shown = qnote;
    if (qnote && !out.stale && out.ok !== false) setTimeout(() => { if (qnote === shown) { qnote = null; if (S) render(S, O); } }, 5000);
    if (io.changed) io.changed(true);
    return out;
  }
  const queuedTickets = () => items().filter(i => i.kind == 'ticket' && i.state == 'queued').map(i => i.key);
  function moveTo(key, to) { return qwrite('/api/queue/move', {key, to}, 'Moved.'); }
  function stopEpoch(v) {
    if (!/^\d\d:\d\d$/.test(v)) return null;
    const d = new Date(S.now * 1000), [hh, mm] = v.split(':').map(Number);
    d.setHours(hh, mm, 0, 0);
    if (d.getTime() / 1000 <= S.now) d.setDate(d.getDate() + 1);  // the next time the clock shows it
    return d.getTime() / 1000;
  }

  form.addEventListener('submit', send);
  msg.addEventListener('input', grow);
  msg.addEventListener('keydown', e => { if (e.key == 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
  sel.addEventListener('change', () => target(sel.value));
  if (job) job.addEventListener('submit', async e => {
    e.preventDefault();
    const f = job.elements, project = f.project.value.trim(), prompt = f.prompt.value;
    if (!project || !prompt.trim()) { jn.innerHTML = '<span class="err">A job needs a project and a prompt.</span>'; return; }
    const go = job.querySelector('button[type=submit]'); go.disabled = true; jn.textContent = 'Queueing…';
    const out = await qwrite('/api/queue/job', {project, prompt, agent: f.agent.value || null, model: f.model.value.trim() || null, name: f.name.value.trim() || null});
    go.disabled = false;
    if (!out) { jn.innerHTML = '<span class="err">Not queued: the hub is busy or not reachable.</span>'; return; }
    if (out.ok) { f.prompt.value = ''; f.name.value = ''; jn.innerHTML = `<span class="okc">${svg('check')} Queued. It runs when the queue reaches it.</span>`; qnote = null; render(S, O, true); }
    else jn.innerHTML = `<span class="err" role="alert">Not queued: ${esc(out.stale ? 'the list changed, try again' : out.error || 'the hub refused it')}</span>`;
  });
  document.addEventListener('keydown', e => {
    const t = e.target, typing = t && (t.tagName == 'TEXTAREA' || t.tagName == 'INPUT' || t.tagName == 'SELECT' || t.isContentEditable);
    if (e.key == '/' && !typing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); msg.focus(); }
    if (e.key == 'Escape' && t === msg && !msg.value) { target(''); msg.blur(); }
  });
  root.addEventListener('click', async e => {
    const b = e.target.closest('button');
    if (b && b.dataset.q != null && !b.disabled) { answer(b.dataset.q, +b.dataset.i); return; }
    if (b && b.dataset.unsend) {
      b.disabled = true; const why = await io.unsend(b.dataset.unsend).catch(err => String(err));
      if (why) { csNote = `<span class="err" role="alert">Not taken back: ${esc(why)}</span>`; hint(); csNote = null; }
      if (io.changed) io.changed(); return;
    }
    if (b && b.dataset.to) { target(b.dataset.to); msg.focus(); return; }
    if (b && b.dataset.qact == 'pause') { const q = Q(); if (q) qwrite('/api/queue/pause', {paused: !q.paused}, q.paused ? 'Resumed: the queue runs.' : 'Paused: nothing new starts.'); return; }
    if (b && b.dataset.rmjob) { qwrite('/api/queue/remove_job', {key: b.dataset.rmjob}, 'Job removed. You can queue it again, corrected.'); return; }
    if (b && b.dataset.qact == 'scan') { qwrite('/api/agents/scan', {}, 'Agents scanned.'); return; }
    if (b && (b.dataset.up || b.dataset.dn)) {
      const k = b.dataset.up || b.dataset.dn, qt = queuedTickets(), at = qt.indexOf(k);
      if (at >= 0) moveTo(k, b.dataset.up ? at - 1 : at + 1); return;
    }
    if (b === fold) {
      const all = [...body.querySelectorAll('details.pj')], shut = all.some(d => d.open);
      all.forEach(d => { d.open = !shut; shut ? collapsed.add(d.dataset.k) : collapsed.delete(d.dataset.k); });
      saveSet('sbhub.collapsed', collapsed); foldLabel(); return;
    }
    const r = !b && e.target.closest('[data-row]');
    if (r && !getSelection().toString()) target(r.dataset.row);
  });
  body.addEventListener('change', e => {
    const el = e.target, d = el.dataset || {};
    if (d.tick) { el.disabled = true; qwrite('/api/queue/set', {keys: queuedTickets().filter(k => k !== d.tick)}, 'Taken out of tonight.'); return; }
    if (d.add) {
      el.disabled = true; const keys = queuedTickets(), add = withBlockers(d.add, []).filter(k => !keys.includes(k));
      qwrite('/api/queue/set', {keys: keys.concat(add)}, add.length > 1 ? `Added with ${plural(add.length - 1, 'ticket')} it waits on.` : 'Added to tonight.'); return;
    }
    if (d.ia) { qwrite('/api/queue/item_agent', {key: d.ia, name: el.value || null}, 'Agent set for this item.'); return; }
    if (d.qa) { if (el.value) qwrite('/api/queue/agent', {name: el.value}, `Tonight runs on ${el.value}.`); return; }
    if (d.qs || d.qf) {
      const q = Q(); if (!q) return;
      const stop = d.qs ? stopEpoch(el.value) : q.stop_at ?? null, fin = d.qf ? el.checked : !!q.final_review;
      qwrite('/api/queue/options', {stop_at: stop, final_review: fin}, d.qs ? (stop ? `Stops at ${hm(stop)}.` : 'No stop time.') : fin ? 'A final review follows the last ticket.' : 'No final review.');
    }
  });
  // drag a queued ticket onto another to take its place (the hub clamps it after its blockers)
  body.addEventListener('dragstart', e => {
    const li = e.target.closest && e.target.closest('li.qi[draggable=true]'); if (!li) return;
    dragKey = li.dataset.qk; li.classList.add('drag');
    try { e.dataTransfer.setData('text/plain', dragKey); e.dataTransfer.effectAllowed = 'move'; } catch (x) { /* old browsers */ }
  });
  body.addEventListener('dragover', e => {
    const li = dragKey && e.target.closest && e.target.closest('li.qi[draggable=true]'); if (!li) return;
    e.preventDefault(); body.querySelectorAll('li.over').forEach(x => x !== li && x.classList.remove('over')); li.classList.add('over');
  });
  body.addEventListener('drop', e => {
    const li = dragKey && e.target.closest && e.target.closest('li.qi[draggable=true]'); if (!li) return;
    e.preventDefault(); const k = dragKey, to = queuedTickets().indexOf(li.dataset.qk); dragKey = null;
    if (k !== li.dataset.qk && to >= 0) moveTo(k, to); else render(S, O, true);
  });
  body.addEventListener('dragend', () => { dragKey = null; body.querySelectorAll('li.drag,li.over').forEach(x => x.classList.remove('drag', 'over')); });
  body.addEventListener('focusout', () => { if (deferred) setTimeout(() => { if (deferred && S && !holding()) render(S, O); }, 0); });
  body.addEventListener('toggle', e => {
    const d = e.target, k = d.dataset && d.dataset.k;
    if (!k || !k.startsWith('p:')) return;
    if (d.open) collapsed.delete(k); else collapsed.add(k);
    saveSet('sbhub.collapsed', collapsed); foldLabel();
  }, true);
  function foldLabel() {
    const all = [...body.querySelectorAll('details.pj')];
    fold.hidden = all.length < 2; fold.textContent = all.some(d => d.open) ? 'Collapse all' : 'Expand all';
  }
  // a list or a time field the owner is in: a rewrite would close it or lose what is typed
  function holding() {
    const ae = document.activeElement;
    if (!ae || !body.contains(ae) || (job && job.contains(ae))) return false;
    return ae.tagName == 'SELECT' || ae.tagName == 'TEXTAREA' || (ae.tagName == 'INPUT' && ae.type != 'checkbox');
  }

  function render(s, o, force) {
    S = s; O = o || {}; gotAt = Date.now();
    root.classList.toggle('down', !!O.down);
    const ban = $('.sb-banner'); ban.hidden = !O.down; ban.textContent = O.down || '';
    const live = $('.sb-live'), [ok, word] = O.live || [!O.down, O.down ? 'offline' : 'live'];
    live.classList.toggle('off', !ok); live.lastChild.textContent = word;
    const can = O.canSend !== false && !O.down;
    for (const el of [sel, msg, form.querySelector('button[type=submit]')]) el.disabled = !can;
    const T = tickets(); byKey = new Map((T || []).map(t => [tkey(t), t]));

    const agents = Object.entries(s.agents || {}).map(([k, a]) => ({...a, agent: a.agent || k}));
    const byId = new Map(agents.map(a => [a.agent, a]));
    const parId = a => { const p = byId.get(a.parent); return p && p.role != 'worker' ? p.agent : null; };
    const order = (x, y) => rank(x) - rank(y) || num(y.at) - num(x.at);
    const tops = agents.filter(a => a.role != 'worker' || !parId(a)).sort(order);
    const kids = p => agents.filter(a => a.role == 'worker' && parId(a) === p.agent).sort(order);
    const qs = Object.entries(s.questions || {}).filter(([id]) => id !== O.skipQ), locks = Object.entries(s.locks || {}), provs = s.providers || {};
    const open = qs.filter(([, q]) => q.answer == null);
    const recent = qs.filter(([, q]) => q.answer != null && s.now - num(q.answered) < 20);
    const need = tops.filter(a => rank(a) == 0), wait = tops.filter(a => a.state == 'your turn'), working = tops.filter(a => a.state == 'working');
    const bad = []; for (const [path, list] of Object.entries(provs)) for (const p of Array.isArray(list) ? list : []) for (const w of wlist(p)) if (w.level == 'bad') bad.push([path, p, w]);
    const alerts = open.length + need.length + bad.length, msgs = Object.entries(s.messages || {}).filter(([, m]) => m && typeof m == 'object');
    const queued = msgs.filter(([, m]) => m.delivered == null && !m.lost).length, nw = agents.length - tops.length;
    const its = items(), q = Q(), tonight = its.filter(i => ENDED[i.state] && s.now - num(i.ended) < NIGHT);
    const nRun = its.filter(i => i.state == 'running').length, nQ = its.filter(i => i.state == 'queued').length;
    const nDone = tonight.filter(i => i.state == 'done').length, nFail = tonight.filter(i => i.state == 'failed').length, end = q ? ends() : 0;

    $('.sb-stats').innerHTML = (alerts ? `<span class="pill bad">${svg('bell')} ${alerts} need${alerts == 1 ? 's' : ''} you</span>` : `<span class="pill ok">${svg('check')} Nothing needs you</span>`)
      + (wait.length ? `<span class="pill acc" title="Waiting for you: sessions that finished their turn">${svg('message')} ${wait.length} your turn</span>` : '')
      + `<span class="pill" title="sessions working now">${svg('loader-2')} ${working.length} working</span>`
      + (q ? `<span class="pill${nRun ? ' acc' : ''}" title="queue items running now">${svg('robot')} ${nRun} running</span>`
        + `<span class="pill" title="queue items waiting">${svg('list-numbers')} ${nQ} queued</span>`
        + `<span class="pill${nDone ? ' ok' : ''}" title="done in the last 18 hours">${svg('circle-check')} ${nDone} done tonight</span>`
        + (nFail ? `<span class="pill bad" title="failed in the last 18 hours">${svg('x')} ${nFail} failed</span>` : '')
        + (end ? (q.paused ? `<span class="pill warn">${svg('player-pause')} paused</span>` : `<span class="pill">${svg('clock')} ends about ${esc(hm(end))}</span>`) : '') : '')
      + `<span class="pill">${plural(tops.length, 'session')}</span>`
      + (nw ? `<span class="pill">${svg('robot')} ${plural(nw, 'worker')}</span>` : '')
      + (locks.length ? `<span class="pill" title="locks held">${svg('lock')} ${locks.length}</span>` : '')
      + (queued ? `<span class="pill acc" title="messages waiting for their session's hook">${svg('mail')} ${queued} queued</span>` : '')
      + (installed().length ? '<span class="sb-sep" aria-hidden="true"></span>' + installed().map(([n, e]) => {
        const [c, w] = agentState(n, e), u = c == 'out' ? '' : usageOf(e), k = costsOf(e);
        const tip = n + (e.kind == 'agy' ? ' (' + agyWords + ')' : '') + ': ' + w + (u ? ' · ' + u.split(' · ')[0] + ' of its 5-hour window used' : '') + (k ? ' · a ticket costs ' + k : '');
        return `<span class="pill ag ${c}" title="${esc(tip)}">${svg('robot')} ${esc(n)}${u ? ' ' + esc(u) : ''} <span class="w">${esc(w.startsWith('running') ? 'running' : w)}</span></span>`;
      }).join('') : '');

    fillTo(tops, kids); fillJob();
    if (holding() && !force) { deferred = true; foldLabel(); hint(); return alerts; }
    deferred = false;

    const H = {needs: '', run: '', queue: queueSection(), avail: availSection(), log: ''};
    if (alerts || recent.length) H.needs = '<section class="sec"><h2>Needs you</h2><div class="box q">'
      + open.concat(recent).sort((x, y) => num(x[1].deadline) - num(y[1].deadline)).map(([id, q]) => qrow(id, q)).join('')
      + need.map(a => row(a, kids(a))).join('')
      + bad.map(([path, p, w]) => `<div class="ln">${dot('bad')}<div class="lm"><b>${esc(proj(path))}</b> · ${esc(p.title)}: ${esc(w.label)} <span class="mute">${esc(String(w.value).slice(0, 120))}</span></div></div>`).join('')
      + '</div></section>';

    const rest = tops.filter(a => rank(a) > 0), groups = new Map();
    for (const p of Object.keys(provs)) groups.set(p, []);
    for (const a of rest) { const k = typeof a.project == 'string' ? a.project : ''; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(a); }
    const best = l => l.length ? [rank(l[0]), -num(l[0].at)] : [9, 0];
    const gs = [...groups].sort((x, y) => { const a = best(x[1]), b = best(y[1]); return a[0] - b[0] || a[1] - b[1] || x[0].localeCompare(y[0]); });
    const workers = runningRows();
    let h = '<section class="sec"><h2>Running now</h2>';
    if (workers) h += `<div class="box">${workers}</div>`;
    for (const [path, list] of gs) {
      const pl = Array.isArray(own(provs, path)) ? provs[path] : [], k = 'p:' + path, above = need.filter(a => a.project === path).length;
      h += `<details class="box pj" data-k="${esc(k)}"${collapsed.has(k) ? '' : ' open'}><summary data-key="${esc('d:' + k)}">`
        + `<span class="pn" dir="auto" title="${esc(path)}">${esc(proj(path) || 'No project')}</span><span class="cnt">${counts(list)}${above ? `<span title="in Needs you">+${above} above</span>` : ''}</span>`
        + `<span class="grow"></span>${digest(pl)}</summary>`
        + (list.length ? list.map(a => row(a, kids(a), true)).join('') : `<div class="r calm" style="cursor:default"><span></span><span class="nt" style="grid-column:2/-1">${above ? 'Its sessions are in Needs you.' : 'No sessions.'}</span></div>`)
        + (pl.length ? `<details class="prov" data-k="${esc('v:' + path)}"><summary data-key="${esc('d:v:' + path)}">Repo, maps and checks</summary>${pl.map(p => provider(p, path)).join('')}</details>` : '')
        + '</details>';
    }
    if (!tops.length && !workers) h += '<div class="box"><div class="empty">No sessions yet. A Claude Code session with the hub-report mod shows here once it starts.</div></div>';
    H.run = h + '</section>';

    const dec = qs.filter(([, q]) => q.answer != null).sort((x, y) => num(y[1].answered) - num(x[1].answered)).slice(0, 8);
    const sent = msgs.filter(([, m]) => m.delivered != null || m.lost).sort((x, y) => num(y[1].at) - num(x[1].at)).slice(0, 10);
    const ran = logLines();
    if (ran || dec.length || locks.length || sent.length) H.log = `<details class="box lg" data-k="p:log"${collapsed.has('p:log') ? '' : ' open'}><summary data-key="d:p:log"><h2>Log</h2><span class="mute">${[plural(tonight.length, 'result') + ' tonight', plural(dec.length, 'decision'), plural(sent.length, 'message'), plural(locks.length, 'lock')].join(' · ')}</span></summary>`
      + ran
      + dec.map(([, q]) => { const pn = whereOf(q.agent), by = q.by == 'default' ? 'Default applied' : q.by == 'you' ? 'Chosen by you' : 'Chosen by ' + q.by;
        return `<div class="ln">${icon(q.by == 'default' ? 'clock' : 'check', by)}<div class="lm"><div class="one" dir="auto" title="${esc(q.q)}">${esc(q.q)}</div><div class="mute one">${esc(by)} · ${esc(who(q.agent))}${pn ? ' · ' + esc(pn) : ''} · ${esc(ago(s.now, q.answered))}</div></div><span class="chip ok" dir="auto" title="${esc(q.answer)}">${esc(q.answer)}</span></div>`; }).join('')
      + sent.map(msgLine).join('')
      + locks.map(([k, l]) => `<div class="ln">${icon('lock', 'lock')}<div class="lm one" dir="auto">${esc(k)}</div><span class="mute">held by ${esc(who(l.by))} · ${esc(ago(s.now, l.at))}</span></div>`).join('')
      + '</details>';

    // keep what the owner had open, focused and scrolled to across the rewrite
    const kept = new Set([...body.querySelectorAll('details[open]')].map(d => d.dataset.k).filter(k => k && !k.startsWith('p:')));
    const ae = document.activeElement, fk = ae && body.contains(ae) && ae.dataset ? ae.dataset.key : null, y = window.scrollY;
    for (const k of Object.keys(H)) if (R[k] && lastH[k] !== H[k]) { R[k].innerHTML = H[k]; lastH[k] = H[k]; }
    body.querySelectorAll('[data-region] details').forEach(d => { if (kept.has(d.dataset.k)) d.open = true; });
    if (fk && document.activeElement !== ae) { const el = body.querySelector(`[data-key="${CSS.escape(fk)}"]`); if (el && !el.disabled) el.focus({preventScroll: true}); }
    if (window.scrollY !== y) window.scrollTo(0, y);
    if (O.down) body.querySelectorAll('button[data-q]').forEach(b => { b.disabled = true; });
    foldLabel(); hint();
    return alerts;
  }

  // countdowns move every second between renders; under a minute they count seconds
  setInterval(() => {
    if (!S || O.down) return;
    const est = S.now + (Date.now() - gotAt) / 1000;
    body.querySelectorAll('.cd[data-dl]').forEach(el => {
      const left = num(el.dataset.dl) - est;
      if (left > 0) { el.textContent = dur(left) + ' left'; el.parentNode.classList.toggle('soon', left < 60); }
      else { el.textContent = 'deciding…'; el.removeAttribute('data-dl'); el.parentNode.classList.add('soon');
        const r = el.closest('[data-qr]'); if (r) r.querySelectorAll('button').forEach(b => { b.disabled = true; }); }
    });
  }, 1000);

  return {render, target, esc, live(ok, word) { const l = $('.sb-live'); l.classList.toggle('off', !ok); l.lastChild.textContent = word; }};
};
})();
