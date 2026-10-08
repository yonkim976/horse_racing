(() => {
  const tabs = document.querySelector('[data-course-view-tabs]');
  const initialContent = document.querySelector('[data-course-view-content]');
  const status = document.querySelector('[data-course-view-status]');
  if (!tabs || !initialContent || !status) return;

  const course = tabs.dataset.course;
  if (!new Set(['seoul', 'busan', 'yeongcheon', 'jeju']).has(course)) return;

  const meetNavigation = document.querySelector('[data-course-meet-nav]');
  const stylesheetLoads = new Map();
  const rememberedViewUrls = new Map();
  let activeContent = initialContent;
  let sequence = 0;
  let controller = null;
  let pendingStage = null;
  let committedUrl = window.location.href;
  rememberedViewUrls.set(course + '|' + activeContent.dataset.view, committedUrl);

  function routeFor(value) {
    let url;
    try {
      url = new URL(value, window.location.href);
    } catch {
      return null;
    }
    if (url.origin !== window.location.origin) return null;
    const match = url.pathname.match(/^\/racecourses\/(seoul|busan|yeongcheon|jeju)\/(distances|course)$/);
    return match ? {
      url,
      course: match[1],
      view: match[2] === 'course' ? 'course' : 'distances'
    } : null;
  }

  function distanceRouteFor(value) {
    const route = routeFor(value);
    if (!route || route.course !== course || route.view !== 'course' || route.url.hash) return null;
    const entries = [...route.url.searchParams.entries()];
    if (entries.length !== 1 || entries[0][0] !== 'distance') return null;
    if (!/^\d{2,5}$/.test(entries[0][1]) || Number(entries[0][1]) > 10000) return null;
    return route;
  }

  function setTabs(view) {
    tabs.querySelectorAll('[data-course-view-link]').forEach((link) => {
      if (link.dataset.courseView === view) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function setBusy(isBusy, message, view) {
    if (activeContent) {
      if (isBusy) activeContent.setAttribute('aria-busy', 'true');
      else activeContent.removeAttribute('aria-busy');
    }
    if (isBusy) tabs.setAttribute('aria-busy', 'true');
    else tabs.removeAttribute('aria-busy');
    tabs.querySelectorAll('[data-course-view-link]').forEach((link) => {
      if (isBusy && link.dataset.courseView === view) {
        link.setAttribute('aria-busy', 'true');
      } else {
        link.removeAttribute('aria-busy');
      }
    });
    status.textContent = message || '';
    status.hidden = !message;
    status.classList.toggle('is-visually-hidden', isBusy);
    if (isBusy && view) {
      status.dataset.loadingView = view;
      setTabs(view);
    } else {
      delete status.dataset.loadingView;
    }
    if (isBusy || !message) delete status.dataset.failedView;
  }

  function clearPendingStage() {
    if (!pendingStage) return;
    pendingStage.animations.forEach((animation) => {
      try {
        animation.cancel();
      } catch {
        // Canceled transitions have no remaining effect.
      }
    });
    pendingStage.element.remove();
    pendingStage.owner.style.position = pendingStage.originalPosition;
    pendingStage.owner.style.overflow = pendingStage.originalOverflow;
    pendingStage.owner.style.minHeight = pendingStage.originalMinHeight;
    pendingStage = null;
  }

  function cancelPending() {
    sequence += 1;
    controller?.abort();
    controller = null;
    clearPendingStage();
    setBusy(false, '');
  }

  function sanitize(fragment) {
    fragment.querySelectorAll('script, iframe, object, embed, base, link, meta, style')
      .forEach((node) => node.remove());
    const urlAttributes = new Set(['href', 'src', 'action', 'formaction', 'xlink:href']);
    [fragment, ...fragment.querySelectorAll('*')].forEach((node) => {
      [...node.attributes].forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        if (name.startsWith('on')) {
          node.removeAttribute(attribute.name);
        } else if (
          urlAttributes.has(name)
          && /^\s*(?:javascript|vbscript|data)\s*:/i.test(attribute.value)
        ) {
          node.removeAttribute(attribute.name);
        }
      });
    });
  }

  function ensureStylesheet(path) {
    const url = new URL(path, window.location.origin).href;
    const existing = [...document.querySelectorAll('link[rel="stylesheet"]')]
      .find((link) => link.href === url);
    if (existing && existing.parentNode !== document.head) document.head.appendChild(existing);
    if (existing?.sheet) return Promise.resolve();
    if (stylesheetLoads.has(url)) return stylesheetLoads.get(url);
    const promise = new Promise((resolve, reject) => {
      const link = existing || document.createElement('link');
      link.rel = 'stylesheet';
      link.href = url;
      link.onload = resolve;
      link.onerror = () => reject(new Error('지도 스타일을 불러오지 못했습니다.'));
      if (!existing) document.head.appendChild(link);
    });
    stylesheetLoads.set(url, promise);
    return promise.catch((error) => {
      stylesheetLoads.delete(url);
      throw error;
    });
  }

  function prepareMapStyles(fragment) {
    if (!fragment.querySelector('[data-course-explorer]')) return Promise.resolve();
    return Promise.all([
      ensureStylesheet('/static/css/course-explorer.css?v=15'),
      ensureStylesheet('/static/css/seoul-map.css?v=17')
    ]);
  }

  function executeMapScript(path) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = new URL(path, window.location.origin).href;
      script.async = true;
      script.onload = () => {
        script.remove();
        resolve();
      };
      script.onerror = () => {
        script.remove();
        reject(new Error('경주로 지도를 초기화하지 못했습니다.'));
      };
      document.head.appendChild(script);
    });
  }

  async function initializeMap(fragment) {
    if (!fragment.querySelector('[data-course-explorer]')) return;
    await executeMapScript('/static/js/course-explorer.js?v=17');
    if (fragment.querySelector('[data-seoul-map]')) {
      await executeMapScript('/static/js/seoul-map.js?v=17');
    }
  }

  function updateMeetLinks(parsedDocument, view) {
    if (!meetNavigation) return;
    const incoming = parsedDocument.querySelector('[data-course-meet-nav]');
    if (!incoming) return;
    meetNavigation.querySelectorAll('[data-course-meet]').forEach((link) => {
      const slug = link.dataset.courseMeet;
      const candidate = incoming.querySelector('[data-course-meet="' + slug + '"]');
      if (!candidate) return;
      const target = routeFor(candidate.href);
      if (target && target.course === slug && target.view === view) {
        link.href = target.url.href;
      }
    });
  }

  function stageContent(incomingContent, transitionMode = 'page') {
    const stage = {
      element: incomingContent,
      owner: activeContent,
      originalClassName: incomingContent.className,
      originalPosition: activeContent.style.position,
      originalOverflow: activeContent.style.overflow,
      originalMinHeight: activeContent.style.minHeight,
      animations: [],
      view: incomingContent.dataset.view,
      course: incomingContent.dataset.course,
      transitionMode
    };
    incomingContent.removeAttribute('data-course-view-content');
    incomingContent.setAttribute('data-course-view-staging', '');
    incomingContent.setAttribute('aria-hidden', 'true');
    incomingContent.setAttribute('inert', '');
    incomingContent.style.position = 'absolute';
    incomingContent.style.top = '0';
    incomingContent.style.left = '0';
    incomingContent.style.right = '0';
    incomingContent.style.opacity = '0';
    incomingContent.style.pointerEvents = 'none';
    incomingContent.style.transformOrigin = '50% 0';
    incomingContent.style.zIndex = '1';

    activeContent.style.position = 'relative';
    activeContent.style.overflow = window.CSS?.supports('overflow', 'clip') ? 'clip' : 'hidden';
    activeContent.appendChild(incomingContent);
    pendingStage = stage;
    return stage;
  }

  async function crossfade(stage) {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion || typeof stage.element.animate !== 'function') return;

    if (stage.transitionMode === 'distance') {
      const outgoingViewport = activeContent.querySelector('.seoul-viewport');
      const incomingViewport = stage.element.querySelector('.seoul-viewport');
      if (!outgoingViewport || !incomingViewport || typeof outgoingViewport.animate !== 'function') {
        throw new Error('지도 화면을 전환하지 못했습니다.');
      }
      stage.element.style.opacity = '1';
      stage.element.classList.add('course-view-map-stage');
      const outgoingOpacity = window.getComputedStyle(outgoingViewport).opacity || '1';
      stage.animations.push(outgoingViewport.animate(
        [{ opacity: outgoingOpacity }, { opacity: '0' }],
        { duration: 260, easing: 'ease-in-out', fill: 'forwards' }
      ));
      stage.animations.push(incomingViewport.animate(
        [{ opacity: '0' }, { opacity: '1' }],
        { duration: 260, easing: 'ease-in-out', fill: 'forwards' }
      ));
      await Promise.all(stage.animations.map((animation) => (
        animation.finished.catch(() => undefined)
      )));
      return;
    }

    const outgoing = [...activeContent.children].filter((element) => (
      element !== stage.element
      && !['SCRIPT', 'LINK', 'STYLE'].includes(element.tagName)
      && typeof element.animate === 'function'
    ));
    const keyframes = outgoing.map((element) => {
      const currentOpacity = window.getComputedStyle(element).opacity || '1';
      return element.animate(
        [
          { opacity: currentOpacity, transform: 'translateY(0)' },
          { opacity: '0', transform: 'translateY(-3px)' }
        ],
        { duration: 145, easing: 'ease-out', fill: 'forwards' }
      );
    });
    stage.animations.push(...keyframes);
    stage.animations.push(stage.element.animate(
      [
        { opacity: '0', transform: 'translateY(8px) scale(0.995)' },
        { opacity: '1', transform: 'translateY(0) scale(1)' }
      ],
      { duration: 340, easing: 'cubic-bezier(0.2, 0.75, 0.25, 1)', fill: 'forwards' }
    ));
    await Promise.all(stage.animations.map((animation) => (
      animation.finished.catch(() => undefined)
    )));
  }

  function preserveDistanceChrome(stage) {
    if (stage.transitionMode !== 'distance') return;

    const incomingHeading = stage.element.querySelector('.course-heading');
    const currentHeading = activeContent.querySelector('.course-heading');
    const incomingTitle = incomingHeading?.querySelector('h2 > span');
    const currentTitle = currentHeading?.querySelector('h2 > span');
    if (incomingTitle && currentTitle) currentTitle.textContent = incomingTitle.textContent;
    if (incomingHeading && currentHeading) incomingHeading.replaceWith(currentHeading);

    const incomingPicker = stage.element.querySelector('.course-distance-picker');
    const currentPicker = activeContent.querySelector('.course-distance-picker');
    if (incomingPicker && currentPicker) {
      const incomingByHref = new Map([...incomingPicker.querySelectorAll('a')].map((link) => {
        const target = new URL(link.href, location.href);
        return [target.pathname + target.search, link];
      }));
      currentPicker.querySelectorAll('a').forEach((link) => {
        const target = new URL(link.href, location.href);
        const incoming = incomingByHref.get(target.pathname + target.search);
        if (!incoming) return;
        link.setAttribute('aria-current', incoming.getAttribute('aria-current') || 'false');
        const currentLabel = link.querySelector('span');
        const incomingLabel = incoming.querySelector('span');
        if (currentLabel && incomingLabel) {
          if (incomingLabel.getAttribute('aria-hidden') === 'true') {
            currentLabel.setAttribute('aria-hidden', 'true');
          } else {
            currentLabel.removeAttribute('aria-hidden');
          }
        }
      });
      incomingPicker.replaceWith(currentPicker);
    }

    const incomingViewLabel = stage.element.querySelector('[data-seoul-view-label]');
    const currentViewLabel = activeContent.querySelector('[data-seoul-view-label]');
    if (incomingViewLabel && currentViewLabel) {
      currentViewLabel.textContent = incomingViewLabel.textContent;
      incomingViewLabel.replaceWith(currentViewLabel);
    }
  }

  function commitStage(stage) {
    if (pendingStage !== stage) return false;
    preserveDistanceChrome(stage);
    const children = [...stage.element.childNodes];
    stage.element.classList.remove('course-view-map-stage');
    activeContent.replaceChildren(...children);
    stage.animations.forEach((animation) => animation.cancel());
    stage.animations.length = 0;
    activeContent.dataset.course = stage.course;
    activeContent.dataset.view = stage.view;
    activeContent.className = stage.originalClassName;
    activeContent.style.position = stage.originalPosition;
    activeContent.style.overflow = stage.originalOverflow;
    activeContent.style.minHeight = stage.originalMinHeight;
    pendingStage = null;
    return true;
  }

  async function navigate(target, historyMode, transitionMode = 'page', restoreDistanceFocus = false) {
    const route = routeFor(target);
    if (!route || route.course !== course) return;
    if (transitionMode === 'distance' && route.view !== 'course') return;
    const requestSequence = ++sequence;
    controller?.abort();
    clearPendingStage();
    const requestController = new AbortController();
    controller = requestController;
    const loadingMessage = route.view === 'course'
      ? '지도를 불러오는 중입니다.'
      : '분석 화면을 불러오는 중입니다.';
    setBusy(true, loadingMessage, route.view);

    let stage = null;
    try {
      const response = await fetch(route.url.href, {
        credentials: 'same-origin',
        headers: { Accept: 'text/html' },
        signal: requestController.signal
      });
      if (!response.ok) throw new Error('화면을 불러오지 못했습니다.');
      const responseRoute = routeFor(response.url || route.url.href);
      if (
        !responseRoute
        || responseRoute.course !== course
        || responseRoute.view !== route.view
        || responseRoute.url.pathname !== route.url.pathname
        || responseRoute.url.search !== route.url.search
      ) throw new Error('요청한 화면을 확인하지 못했습니다.');

      const parsedDocument = new DOMParser().parseFromString(
        await response.text(),
        'text/html'
      );
      const candidates = parsedDocument.querySelectorAll('[data-course-view-content]');
      if (candidates.length !== 1) throw new Error('화면 구성을 확인하지 못했습니다.');
      const incomingContent = candidates[0];
      if (
        incomingContent.dataset.course !== course
        || incomingContent.dataset.view !== route.view
      ) throw new Error('요청한 경마장 화면이 아닙니다.');

      sanitize(incomingContent);
      await prepareMapStyles(incomingContent);
      if (requestSequence !== sequence) return;

      stage = stageContent(incomingContent, transitionMode);
      await initializeMap(stage.element);
      if (requestSequence !== sequence) return;

      await crossfade(stage);
      if (requestSequence !== sequence) return;
      const scrollPosition = transitionMode === 'distance'
        ? { left: window.scrollX, top: window.scrollY }
        : null;
      if (!commitStage(stage)) return;
      if (scrollPosition) {
        if (restoreDistanceFocus) {
          activeContent.querySelector('.course-distance-picker a[aria-current="page"]')
            ?.focus({ preventScroll: true });
        }
        if (document.scrollingElement) {
          document.scrollingElement.scrollLeft = scrollPosition.left;
          document.scrollingElement.scrollTop = scrollPosition.top;
        }
      }

      const incomingTitle = parsedDocument.querySelector('title');
      if (incomingTitle) document.title = incomingTitle.textContent;
      updateMeetLinks(parsedDocument, route.view);
      setTabs(route.view);
      rememberedViewUrls.set(course + '|' + route.view, route.url.href);
      if (historyMode === 'push') {
        window.history.pushState({ courseView: true }, '', route.url.href);
      } else if (historyMode === 'replace') {
        window.history.replaceState({ courseView: true }, '', route.url.href);
      }
      committedUrl = route.url.href;
      controller = null;
      setBusy(false, '');
    } catch (error) {
      if (requestSequence !== sequence || error.name === 'AbortError') return;
      if (stage) clearPendingStage();
      controller = null;
      setTabs(activeContent.dataset.view);
      status.dataset.failedView = route.view;
      setBusy(false, route.view === 'course'
        ? '지도를 준비하지 못했습니다. 지도 탭을 다시 선택해 재시도해 주세요.'
        : '화면을 불러오지 못했습니다. 탭을 다시 선택해 재시도해 주세요.');
    }
  }

  activeContent.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const link = target?.closest('.course-distance-picker a');
    if (
      !link
      || !activeContent.contains(link)
      || event.defaultPrevented
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
      || link.target
      || link.hasAttribute('download')
    ) return;

    const route = distanceRouteFor(link.href);
    if (!route) return;
    event.preventDefault();
    const restoreFocus = document.activeElement === link || event.detail === 0;
    if (route.url.href === committedUrl) {
      cancelPending();
      if (window.location.href !== committedUrl) {
        window.history.replaceState(window.history.state, '', committedUrl);
      }
      setTabs('course');
      if (restoreFocus) link.focus({ preventScroll: true });
      return;
    }
    navigate(route.url, 'push', 'distance', restoreFocus);
  });

  tabs.addEventListener('click', (event) => {
    const link = event.target.closest('[data-course-view-link]');
    if (
      !link
      || event.defaultPrevented
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
      || link.target
      || link.hasAttribute('download')
    ) return;

    const route = routeFor(link.href);
    if (!route || route.course !== course || route.view !== link.dataset.courseView) return;
    event.preventDefault();

    if (activeContent.dataset.view === route.view) {
      if (status.dataset.failedView === route.view) {
        navigate(new URL(committedUrl, window.location.origin), 'replace');
        return;
      }
      cancelPending();
      if (window.location.href !== committedUrl) {
        window.history.replaceState(window.history.state, '', committedUrl);
      }
      setTabs(route.view);
      return;
    }

    const remembered = rememberedViewUrls.get(course + '|' + route.view);
    const destination = remembered
      ? new URL(remembered, window.location.origin)
      : route.url;
    navigate(destination, 'push');
  });

  window.addEventListener('popstate', () => {
    const route = routeFor(window.location.href);
    if (!route || route.course !== course) return;
    if (
      activeContent.dataset.view === route.view
      && window.location.href === committedUrl
    ) {
      cancelPending();
      setTabs(route.view);
      return;
    }
    const transitionMode = route.view === 'course' && activeContent.dataset.view === 'course'
      ? 'distance'
      : 'page';
    navigate(route.url, 'none', transitionMode);
  });
})();
