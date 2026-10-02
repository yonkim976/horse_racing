document.querySelectorAll('[data-course-explorer]').forEach((root) => {
  const steps = [...root.querySelectorAll('[data-course-select]')];
  const closing = [...root.querySelectorAll('[data-course-closing]')];
  const reset = root.querySelector('[data-course-reset]');
  const summary = root.querySelector('[data-course-summary]');
  const focus = root.querySelector('[data-course-focus]');
  const note = root.querySelector('[data-course-selection-note]');
  const previews = [...root.querySelectorAll('[data-jeju-preview], [data-seoul-distance]')];
  const current = root.dataset.distance;
  const isJeju = root.dataset.racecourseMap === 'jeju';
  const previewDistance = button => button.dataset.jejuPreview || button.dataset.seoulDistance;
  function currentRoute() {
    const button = previews.find(button => previewDistance(button) === current);
    if (button && button.getAttribute('aria-pressed') !== 'true') button.click();
  }
  function highlight(start, span) {
    if (!focus) return;
    focus.toggleAttribute('hidden', !(span > 0));
    focus.setAttribute('stroke-dasharray', `${span} ${Number(current) + 1}`);
    focus.setAttribute('stroke-dashoffset', String(-start));
  }
  function clear() {
    steps.forEach(button => { button.setAttribute('aria-pressed', 'false'); button.classList.remove('is-closing'); });
    closing.forEach(button => button.setAttribute('aria-pressed', 'false'));
    root.querySelectorAll('[data-course-detail], [data-course-closing-detail]').forEach(panel => { panel.hidden = true; });
    root.querySelectorAll('[data-course-point]').forEach(point => point.setAttribute('aria-pressed', 'false'));
    summary.hidden = false;
    reset.setAttribute('aria-pressed', 'true');
    highlight(0, 0);
  }
  steps.forEach(button => {
    button.addEventListener('click', currentRoute, true);
    button.addEventListener('click', () => {
      clear();
      button.setAttribute('aria-pressed', 'true');
      reset.setAttribute('aria-pressed', 'false');
      summary.hidden = true;
      const detail = root.querySelector(`[data-course-detail="${button.dataset.courseSelect}"]`);
      detail.hidden = false;
      note.textContent = [...detail.querySelector('.course-selected-interval').children].map(item => item.textContent.trim()).join(' · ');
      root.querySelectorAll('[data-course-point]').forEach(point => point.setAttribute('aria-pressed', String(point.dataset.coursePoint === button.dataset.courseSelect)));
      highlight(Number(button.dataset.start), Number(button.dataset.span));
    });
  });
  reset?.addEventListener('click', () => {
    clear();
    note.textContent = '지도는 주로 배치, 순서도는 기록 측정 순서를 보여줍니다.';
  });
  closing.forEach(button => button.addEventListener('click', () => {
    currentRoute();
    // Reset also clears any course-specific map focus.
    reset.click();
    reset.setAttribute('aria-pressed', 'false');
    summary.hidden = true;
    button.setAttribute('aria-pressed', 'true');
    root.querySelector(`[data-course-closing-detail="${button.dataset.courseClosing}"]`).hidden = false;
    const metres = Number(button.dataset.courseClosing);
    const code = metres === 600 ? 'G3F' : 'G1F';
    const start = steps.findIndex(step => step.querySelector('strong').textContent.split('/').includes(code));
    if (start >= 0) steps.forEach((step, index) => step.classList.toggle('is-closing', index > start));
    if (isJeju) highlight(Number(current) - metres, metres);
    note.textContent = `${code} → 결승 · 마지막 ${metres}m. 연속 구간과 겹치는 기록입니다.`;
  }));
  root.querySelectorAll('[data-course-point]').forEach(point => {
    const choose = () => steps.find(step => step.dataset.courseSelect === point.dataset.coursePoint)?.click();
    point.addEventListener('click', choose);
    point.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); }
    });
  });
  previews.forEach(button => button.addEventListener('click', () => reset.click()));
  root.querySelectorAll('[data-course-layer]').forEach(input => {
    input.addEventListener('change', () => {
      if (input.checked) root.querySelectorAll('[data-course-layer]').forEach(other => {
        if (other !== input) { other.checked = false; root.querySelector(`[data-course-overlay="${other.dataset.courseLayer}"]`).setAttribute('hidden', ''); }
      });
      root.querySelector(`[data-course-overlay="${input.dataset.courseLayer}"]`).toggleAttribute('hidden', !input.checked);
    });
  });
  root.querySelector('[data-course-zoom]')?.addEventListener('click', event => {
    const zoom = root.querySelector('[data-course-viewport]').classList.toggle('zoomed');
    event.currentTarget.setAttribute('aria-pressed', String(zoom));
    event.currentTarget.textContent = zoom ? '전체 보기' : '확대 보기';
  });
  if (!isJeju) return;
  const official = root.querySelector('[data-jeju-official]');
  const officialImage = official?.querySelector('img');
  const officialFallback = official?.querySelector('[data-jeju-official-fallback]');
  const officialCaption = official?.querySelector('[data-jeju-official-caption]');
  function showOfficialFallback() {
    officialImage.hidden = true;
    officialCaption.hidden = true;
    officialFallback.hidden = false;
    root.querySelector('[data-course-viewport]').classList.remove('with-source');
  }
  officialImage?.addEventListener('error', showOfficialFallback);
  root.querySelector('[data-jeju-source]')?.addEventListener('click', event => {
    const show = official.hidden;
    official.hidden = !show;
    root.querySelector('[data-course-viewport]').classList.toggle('with-source', show);
    event.currentTarget.setAttribute('aria-pressed', String(show));
    if (show && officialImage.complete && !officialImage.naturalWidth) showOfficialFallback();
  });
  const arrows = root.querySelector('[data-jeju-arrows]');
  function drawArrows() {
    const line = root.querySelector('[data-jeju-route]');
    const length = line.getTotalLength();
    const gate = root.querySelector('[data-jeju-start] circle');
    const occupied = [...root.querySelectorAll('[data-course-point]:not([hidden])')]
      .map(point => point.getAttribute('transform').match(/-?[\d.]+/g).map(Number))
      .concat([[Number(gate.getAttribute('cx')), Number(gate.getAttribute('cy'))]]);
    const clear = at => {
      const p = line.getPointAtLength(length * at);
      return occupied.every(([x, y]) => Math.hypot(x - p.x, y - p.y) > 26);
    };
    arrows.replaceChildren();
    for (let slot = .13; slot < .96; slot += .24) {
      const fraction = [0, .04, -.04, .08, -.08].map(shift => slot + shift).find(clear);
      if (fraction === undefined) continue;
      const point = line.getPointAtLength(length * fraction);
      const next = line.getPointAtLength(length * fraction + 2);
      const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      arrow.setAttribute('d', 'M -5 -4 L 1 0 L -5 4');
      arrow.setAttribute('transform', `translate(${point.x} ${point.y}) rotate(${Math.atan2(next.y - point.y, next.x - point.x) * 180 / Math.PI})`);
      arrows.appendChild(arrow);
    }
  }
  drawArrows();
  previews.forEach(button => button.addEventListener('click', () => {
    const distance = button.dataset.jejuPreview;
    const own = distance === current;
    previews.forEach(other => other.setAttribute('aria-pressed', String(other === button)));
    root.querySelector('[data-jeju-route]').setAttribute('d', button.dataset.route);
    root.querySelector('[data-jeju-halo]').setAttribute('d', button.dataset.route);
    const focus = root.querySelector('[data-course-focus]');
    focus.setAttribute('d', button.dataset.route);
    focus.setAttribute('pathLength', distance);
    const early = ['1110', '1610'].includes(distance) ? 210 : 200;
    root.querySelector('[data-course-early-label]').textContent = early;
    root.querySelectorAll('[data-jeju-band]').forEach(path => {
      const code = path.dataset.jejuBand;
      const span = code === 'early' ? early : code === 'middle' ? 400 : 200;
      const start = code === 'early' ? 0 : Number(distance) - (code === 'middle' ? 600 : 200);
      path.setAttribute('d', button.dataset.route);
      path.setAttribute('pathLength', distance);
      path.setAttribute('stroke-dasharray', `${span} ${Number(distance) + 1}`);
      path.setAttribute('stroke-dashoffset', -start);
    });
    const x = Number(button.dataset.x), y = Number(button.dataset.y);
    const start = root.querySelector('[data-jeju-start]');
    start.setAttribute('aria-label', `출발 ${Number(distance).toLocaleString('ko-KR')}m`);
    start.querySelector('circle').setAttribute('cx', x);
    start.querySelector('circle').setAttribute('cy', y);
    start.querySelector('circle').setAttribute('r', distance === '1610' ? 4 : 7);
    start.querySelector('path').setAttribute('d', `M ${x} ${y} l ${y > 0 ? 78 : 0} ${y > 0 ? 48 : -40}`);
    start.querySelector('text').setAttribute('x', x + (y > 0 ? 78 : 0));
    start.querySelector('text').setAttribute('y', y + (y > 0 ? 65 : -49));
    start.querySelector('text').textContent = `${Number(distance).toLocaleString('ko-KR')}m 출발`;
    const label = Number(distance).toLocaleString('ko-KR') + 'm';
    root.querySelectorAll('[data-other-start]').forEach(marker => marker.toggleAttribute('hidden', marker.dataset.otherStart.replace(/[^0-9]/g, '') === distance));
    const viewLabel = root.querySelector('[data-course-view-label]');
    if (viewLabel) viewLabel.textContent = (own ? '' : '경로 미리보기 · ') + label;
    root.querySelector('[data-jeju-distance]').textContent = label;
    root.querySelector('[data-jeju-direction]').textContent = '시계 방향 ↻' + (Number(distance) > 1600 ? ' · 결승선 첫 통과 후 한 바퀴' : '');
    root.querySelector('[data-jeju-route-title]').textContent = `${own ? '' : '경로 미리보기 · '}${label}`;
    root.querySelector('[data-jeju-route-description]').textContent = own
      ? '제주 시계 방향 경로입니다. 아래 기록은 현재 경주의 기록입니다.'
      : `다른 거리 출발점과 경로의 미리보기입니다. 아래 기록은 현재 ${Number(current).toLocaleString('ko-KR')}m 경주에 해당합니다.`;
    root.querySelector('.course-map').setAttribute('aria-label', `제주 ${label} 주행 경로`);
    root.querySelector('.course-map title').textContent = `제주 ${label} 주행 경로`;
    root.querySelectorAll('[data-course-point]').forEach(point => { point.toggleAttribute('hidden', !own); point.setAttribute('tabindex', own ? '0' : '-1'); });
    root.querySelector('[data-course-map-note]').textContent = own ? '지도 지점을 선택하면 직전 구간과 말별 기록을 확인합니다.' : `다른 거리의 경로 미리보기입니다. 아래 기록은 현재 ${Number(current).toLocaleString('ko-KR')}m 경주의 기록입니다.`;
    drawArrows();
  }));
});
