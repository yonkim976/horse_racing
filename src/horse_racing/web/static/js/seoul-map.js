document.querySelectorAll('[data-seoul-map]').forEach((root) => {
  const buttons = [...root.querySelectorAll('[data-seoul-distance]')];
  const routes = [...root.querySelectorAll('[data-seoul-route]')];
  const current = root.dataset.distance;
  const viewport = root.querySelector('[data-seoul-viewport]');
  const svg = root.querySelector('.seoul-plan');
  const source = root.querySelector('[data-seoul-official]');
  const sourceButton = root.querySelector('[data-seoul-source]');
  routes.forEach((route) => {
    const line = route.querySelector('[data-route-line]');
    const length = line.getTotalLength();
    const arrows = route.querySelector('[data-route-arrows]');
    for (let fraction = .13; fraction < .96; fraction += .24) {
      const point = line.getPointAtLength(length * fraction);
      const next = line.getPointAtLength(length * fraction + 2);
      const angle = Math.atan2(next.y - point.y, next.x - point.x) * 180 / Math.PI;
      const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      arrow.setAttribute('d', 'M -5 -4 L 1 0 L -5 4');
      arrow.setAttribute('transform', `translate(${point.x} ${point.y}) rotate(${angle})`);
      arrows.appendChild(arrow);
    }
  });
  buttons.forEach((button) => button.addEventListener('click', () => {
    const distance = button.dataset.seoulDistance;
    buttons.forEach((other) => other.setAttribute('aria-pressed', String(other === button)));
    routes.forEach((route) => {
      const selected = route.dataset.seoulRoute === distance;
      route.setAttribute('aria-hidden', String(!selected));
      route.querySelectorAll('[data-seoul-marker]').forEach((marker) => marker.setAttribute('tabindex', selected ? '0' : '-1'));
      if (selected) route.removeAttribute('hidden');
      else route.setAttribute('hidden', '');
    });
    const label = Number(distance).toLocaleString('ko-KR') + 'm';
    root.querySelector('[data-seoul-view-label]').textContent = (distance === current ? '현재 경주 · ' : '경로 미리보기 · ') + label;
    root.querySelector('[data-seoul-center-distance]').textContent = label;
    root.querySelector('[data-seoul-route-title]').textContent = button.dataset.routeTitle;
    root.querySelector('[data-seoul-route-description]').textContent = button.dataset.routeDescription;
    svg.setAttribute('aria-label', `${root.dataset.courseName || "서울"} ${label} 표준 경로 구조도`);
    svg.querySelector('title').textContent = `${root.dataset.courseName || "서울"} ${label} 표준 경로 구조도`;
  }));
  sourceButton.addEventListener('click', () => {
    const show = source.hidden;
    source.hidden = !show;
    viewport.classList.toggle('with-source', show);
    sourceButton.setAttribute('aria-pressed', String(show));
  });
  root.querySelector('[data-seoul-zoom]').addEventListener('click', (event) => {
    const zoom = viewport.classList.toggle('zoomed');
    event.currentTarget.setAttribute('aria-pressed', String(zoom));
    event.currentTarget.textContent = zoom ? '전체 보기' : '확대 보기';
  });
});

document.querySelectorAll('[data-seoul-map]').forEach((root) => {
  const reset = root.querySelector('[data-course-reset]');
  const steps = [...root.querySelectorAll('[data-course-select]')];
  const note = root.querySelector('[data-seoul-map-note]');
  const current = root.dataset.distance;
  function focus(action) {
    root.querySelectorAll('[data-seoul-interval]').forEach((path) => path.setAttribute('hidden', ''));
    root.querySelectorAll('[data-seoul-focus]').forEach((path) => {
      const selected = path.closest('[data-seoul-route]').dataset.seoulRoute === current && path.dataset.seoulFocus === action;
      path.toggleAttribute('hidden', !selected);
    });
    root.querySelectorAll('[data-seoul-marker]').forEach((point) => point.setAttribute('aria-pressed', String(point.dataset.markerDistance === current && point.dataset.seoulMarker === action)));
  }
  reset.addEventListener('click', () => {
    focus(null);
    note.textContent = root.dataset.courseName === "부경" ? "지도 지점은 거리 기준 개략 위치이며, 코너 이름은 구역 안내입니다." : "지도 지점을 선택하면 기록을 확인합니다. 코너 점은 기록 대조 참고 위치입니다.";
  });
  root.querySelectorAll('[data-course-closing]').forEach((button) => button.addEventListener('click', () => {
    focus(button.dataset.courseClosing);
    note.textContent = `현재 경주 · 마지막 ${button.dataset.courseClosing}m를 강조했습니다.`;
  }));
  steps.forEach((step, index) => step.addEventListener('click', () => {
    const codes = step.querySelector('strong').textContent.split('/');
    const route = root.querySelector(`[data-seoul-route="${current}"]`);
    if (!route) return;
    const positions = { START: 0, FIN: Number(current) };
    route.querySelectorAll('[data-seoul-marker]').forEach((marker) => {
      marker.dataset.markerCodes.split('/').forEach((code) => { positions[code] = Number(marker.dataset.markerMetres); });
    });
    const previous = index ? steps[index - 1].querySelector('strong').textContent.split('/') : ['START'];
    const start = positions[previous[0]], end = positions[codes[0]];
    focus(null);
    route.querySelectorAll('[data-seoul-marker]').forEach((marker) => {
      marker.setAttribute('aria-pressed', String(marker.dataset.markerCodes.split('/').some((code) => codes.includes(code))));
    });
    const interval = route.querySelector(`[data-seoul-interval][data-start="${start}"][data-end="${end}"]`);
    if (interval) {
      interval.removeAttribute('hidden');
      note.textContent = `${previous.join('/')} → ${codes.join('/')} · ${root.dataset.courseName === "부경" ? "" : "약 "}${end - start}m 구간입니다. ${root.dataset.courseName === "부경" ? "지도 위치는 공식 도면을 재구성한 개략 위치입니다." : "코너 위치는 기록 대조에 따른 개략 위치입니다."}`;
    } else {
      note.textContent = end !== undefined ? `${codes.join('/')} · 출발 후 약 ${end}m 참고 위치입니다. 직전 구간의 거리는 확정하지 않았습니다.` : '이 코너는 위치 확인이 더 필요해 지도 강조 없이 기록을 표시합니다.';
    }
  }));
  root.querySelectorAll('[data-seoul-marker]').forEach((marker) => {
    function choose() {
      if (marker.dataset.markerDistance !== current) {
        note.textContent = '다른 거리의 측정 위치 미리보기입니다. 말별 기록은 현재 경주에서 확인하세요.';
        return;
      }
      const control = steps.find((step) => step.querySelector('strong').textContent.split('/').some((code) => marker.dataset.markerCodes.split('/').includes(code)));
      if (control) control.click();
      else note.textContent = '이 경주에는 해당 구간 기록이 등록되지 않았습니다.';
    }
    marker.addEventListener('click', choose);
    marker.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); }
    });
  });
});
