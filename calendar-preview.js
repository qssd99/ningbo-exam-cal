'use strict';
const FLOWUS_HISTORY = new Set(["[\"鄞州区\",\"鄞州区815公告\"]", "[\"市属\",\"市属627公告\"]", "[\"海曙区\",\"海曙区人才引进公告\"]", "[\"象山县\",\"象山县人才引进516公告\"]", "[\"鄞州区\",\"鄞州区425公告\"]", "[\"宁海县\",\"宁海县人才引进425公告\"]", "[\"镇海区\",\"镇海区510公告\"]", "[\"镇海区\",\"镇海区人才引进4.8公告\"]", "[\"市属\",\"市属411公告\"]", "[\"高新区\",\"高新区人才引进411公告\"]"]);

function parseCalendar(text) {
  const unfolded = text.replace(/\r?\n[ \t]/g, '');
  const unescape = value => value.replace(/\\([nN,;\\])/g, (_, c) => /[nN]/.test(c) ? '\n' : c);
  return [...unfolded.matchAll(/BEGIN:VEVENT\r?\n([\s\S]*?)END:VEVENT/g)].map(match => {
    const event = {};
    for (const line of match[1].split(/\r?\n/)) {
      const colon = line.indexOf(':');
      if (colon < 0) continue;
      const name = line.slice(0, colon).split(';')[0];
      if (['SUMMARY', 'DTSTART', 'DTEND', 'URL', 'UID'].includes(name)) event[name] = unescape(line.slice(colon + 1));
    }
    return event;
  }).filter(e => /^2026\d{4}(T\d{6})?$/.test(e.DTSTART || '') && e.SUMMARY)
    .sort((a, b) => a.DTSTART.localeCompare(b.DTSTART) || a.SUMMARY.localeCompare(b.SUMMARY, 'zh-CN'));
}
function displayDate(value) {
  return `${value.slice(4,6)}月${value.slice(6,8)}日` + (value.includes('T') ? ` ${value.slice(9,11)}:${value.slice(11,13)}` : '（全天）');
}
function displayRange(event) {
  if (!event.DTSTART.includes('T')) return displayDate(event.DTSTART); // DATE end is exclusive; do not display it as an inclusive deadline.
  return displayDate(event.DTSTART) + (event.DTEND && event.DTEND !== event.DTSTART ? ' — ' + displayDate(event.DTEND) : '');
}
function instant(value) {
  if (!value) return NaN;
  const time = value.includes('T') ? `${value.slice(9,11)}:${value.slice(11,13)}:${value.slice(13,15)}` : '00:00:00';
  return Date.parse(`${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}T${time}+08:00`);
}
function bounds(event) {
  const start = instant(event.DTSTART);
  const end = event.DTEND ? instant(event.DTEND) : start + (event.DTSTART.includes('T') ? 0 : 86400000);
  return {start, end, exclusive: !event.DTSTART.includes('T')};
}
function isActive(event, now) {
  const b = bounds(event), t = +now;
  return b.start <= t && (b.exclusive ? t < b.end : t <= b.end);
}
function label(event) {
  const match = event.SUMMARY.match(/^【(.+?)】(.+?)｜(.+)$/);
  return match ? {region:match[1], stage:match[2], title:match[3]} : {region:'其他',stage:'时间节点',title:event.SUMMARY};
}
function buildView(events, now = new Date()) {
  const localDay = new Date(+now + 8*3600000).toISOString().slice(0,10);
  const cutoff = Date.parse(`${localDay}T00:00:00+08:00`) - 15*86400000;
  const all = events.map(e => ({...e, ...label(e)}));
  const recent = all.filter(e => bounds(e).end >= cutoff).sort((a,b) => {
    const category = e => isActive(e,now) ? 0 : bounds(e).start > +now ? 1 : 2;
    const c = category(a)-category(b);
    return c || (category(a) === 2 ? bounds(b).start-bounds(a).start : bounds(a).start-bounds(b).start);
  });
  const groups = new Map();
  for (const e of all) {
    // Never combine distinct titled exams just because their dates or regions coincide.
    const key = JSON.stringify([e.region,e.title,e.URL || '']);
    if (!groups.has(key)) groups.set(key,{key,title:e.title,region:e.region,events:[]});
    groups.get(key).events.push(e);
  }
  const exams = [...groups.values()].map(g => {
    g.events.sort((a,b)=>bounds(a).start-bounds(b).start);
    const ongoing = g.events.filter(e=>isActive(e,now));
    const written = g.events.filter(e=>e.stage==='笔试');
    g.featured = ongoing.length ? ongoing : written;
    g.active = ongoing.length>0;
    g.next = g.events.filter(e=>bounds(e).start>+now)[0];
    g.latest = Math.max(...g.events.map(e=>bounds(e).end));
    g.status = g.active ? '进行中' : g.next ? '待进行' : '已收录节点均已结束';
    return g;
  }).sort((a,b)=>{
    const cat = g=>g.active?0:g.next?1:2;
    return cat(a)-cat(b) || (cat(a)===2 ? b.latest-a.latest : (a.next?bounds(a.next).start:a.latest)-(b.next?bounds(b.next).start:b.latest));
  });
  // Historical cards follow the ten curated FlowUs exams; current/future exams remain visible.
  const visibleExams = exams.filter(g => g.active || g.next || FLOWUS_HISTORY.has(JSON.stringify([g.region,g.title])));
  return {recent,exams:visibleExams};
}
function node(tag, cls, text) {
  const e=document.createElement(tag); if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;
}
function eventRow(event, now, withExam=false) {
  const row=node('div','timeline-row');
  const title=node('div','node-title',`${isActive(event,now)?'进行中 · ':''}${event.stage}`);
  row.append(title,node('div','event-date',displayRange(event)));
  if(withExam) row.append(node('div','event-exam',`【${event.region}】${event.title}`));
  return row;
}
function renderCalendar(events, now = new Date()) {
  const model=buildView(events,now);
  const status=document.getElementById('calendar-status');
  status.textContent=`2026年 · ${model.exams.length}场已收录考试 · ${model.exams.reduce((n,g)=>n+g.events.length,0)}个展示节点 · 北京时间`;
  const recent=document.getElementById('recent-events');recent.replaceChildren();
  if(!model.recent.length) recent.append(node('p','empty','过去15天及未来暂无已收录节点'));
  else {
    const first=node('div');model.recent.slice(0,5).forEach(e=>first.append(eventRow(e,now,true)));recent.append(first);
    if(model.recent.length>5){const more=node('details','recent-more');more.append(node('summary','',`查看其余${model.recent.length-5}个近期节点`));model.recent.slice(5).forEach(e=>more.append(eventRow(e,now,true)));recent.append(more);}
  }
  const container=document.getElementById('calendar-events');container.replaceChildren();
  for(const exam of model.exams){
    const card=node('section','exam-card');
    const header=node('div','card-header');header.append(node('span','region',exam.region),node('span',exam.active?'badge active':'badge',exam.status));card.append(header);
    card.append(node('div','exam-title',exam.title));
    const featured=node('div','featured');
    if(exam.featured.length)exam.featured.forEach(e=>featured.append(eventRow(e,now)));
    else featured.append(node('div','event-date','笔试日期未收录'));
    card.append(featured);
    const details=node('details','exam-details');details.append(node('summary','',`完整时间线 · ${exam.events.length}个节点`));
    exam.events.forEach(e=>details.append(eventRow(e,now)));card.append(details);
    const url=exam.events.find(e=>/^https?:\/\//i.test(e.URL||''));
    if(url){const a=node('a','source-link','公告原文');a.href=url.URL;a.target='_blank';a.rel='noopener noreferrer';card.append(a);}
    container.append(card);
  }
}
async function loadCalendar() {
  try {
    const response=await fetch('ningbo-exam.ics',{cache:'no-cache'});if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const text=await response.text();if(!text.includes('BEGIN:VCALENDAR'))throw new Error('不是日历文件');
    const events=parseCalendar(text);renderCalendar(events);
    // Re-evaluate ongoing nodes while the page remains open.
    setInterval(()=>{if(!document.querySelector('details[open]'))renderCalendar(events);},60000);
  } catch(error){document.getElementById('calendar-status').textContent='日历加载失败，请刷新页面或下载订阅文件。';console.error(error);}
}
if(typeof document!=='undefined')loadCalendar();
if(typeof module!=='undefined')module.exports={parseCalendar,displayDate,displayRange,buildView,isActive};
