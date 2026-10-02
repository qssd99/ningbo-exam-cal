'use strict';
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
async function loadCalendar() {
  const status = document.getElementById('calendar-status');
  const container = document.getElementById('calendar-events');
  try {
    const response = await fetch('ningbo-exam.ics', {cache: 'no-cache'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    if (!text.includes('BEGIN:VCALENDAR')) throw new Error('不是日历文件');
    const events = parseCalendar(text);
    status.textContent = `2026 年已收录 ${events.length} 个时间节点；按开始月份展示，全部时间为北京时间。`;
    const groups = new Map();
    for (const event of events) {
      const month = event.DTSTART.slice(0, 6);
      if (!groups.has(month)) groups.set(month, []);
      groups.get(month).push(event);
    }
    container.replaceChildren();
    for (const [month, rows] of groups) {
      const details = document.createElement('details');
      details.open = true;
      const summary = document.createElement('summary');
      summary.textContent = `${month.slice(0,4)}年${Number(month.slice(4))}月 · ${rows.length}个节点`;
      details.append(summary);
      for (const event of rows) {
        const row = document.createElement('div'); row.className = 'calendar-event';
        const title = document.createElement('div'); title.className = 'event-title'; title.textContent = event.SUMMARY;
        const date = document.createElement('div'); date.className = 'event-date'; date.textContent = displayRange(event);
        row.append(title, date);
        if (event.URL && /^https?:\/\//i.test(event.URL)) {
          const link = document.createElement('a'); link.href = event.URL; link.textContent = '公告原文'; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link);
        }
        details.append(row);
      }
      container.append(details);
    }
  } catch (error) {
    status.textContent = '日历预览加载失败，请刷新页面或使用上方订阅文件。';
    console.error('日历预览加载失败', error);
  }
}
if (typeof document !== 'undefined') loadCalendar();
if (typeof module !== 'undefined') module.exports = {parseCalendar, displayDate, displayRange};
