(() => {
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let scheduleHeaderResizeObserver = null;

  const entityNav = document.querySelector("[data-entity-nav]");
  if (entityNav) {
    document.addEventListener("click", (event) => {
      if (entityNav.open && event.target instanceof Node && !entityNav.contains(event.target)) {
        entityNav.open = false;
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && entityNav.open) {
        entityNav.open = false;
        entityNav.querySelector("summary").focus();
        event.preventDefault();
      }
    });
  }

  /* ------------------------------------------------------------------
     테마 토글 (다크/라이트, localStorage 유지)
     ------------------------------------------------------------------ */
  const THEME_KEY = "hr-theme";

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (error) {
      /* 저장 불가 환경 무시 */
    }
    syncThemeControls(theme);
    window.dispatchEvent(new CustomEvent("hr:themechange", { detail: { theme } }));
  }

  function syncThemeControls(theme) {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", theme === "dark" ? "#0a0f0d" : "#f2f5f2");
    }
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute(
        "aria-label",
        theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"
      );
    });
  }

  syncThemeControls(document.documentElement.dataset.theme);

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
    });
  });

  /* ------------------------------------------------------------------
     숫자만 보기 (홈 카드에서 마번·확률만 크게, localStorage 유지)
     ------------------------------------------------------------------ */
  const EASY_KEY = "hr-easy";

  function applyEasy(on) {
    if (on) document.documentElement.dataset.easy = "1";
    else delete document.documentElement.dataset.easy;
    try {
      localStorage.setItem(EASY_KEY, on ? "1" : "0");
    } catch (error) {
      /* 저장 불가 환경 무시 */
    }
    syncEasyControls();
  }

  function syncEasyControls() {
    const on = document.documentElement.dataset.easy === "1";
    document.querySelectorAll("[data-easy-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.setAttribute("aria-label", on ? "일반모드로 보기" : "큰글씨 모드로 보기");
    });
  }

  syncEasyControls();

  document.querySelectorAll("[data-easy-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      applyEasy(document.documentElement.dataset.easy !== "1");
    });
  });

  /* ------------------------------------------------------------------
     필터 select 변경 시 자동 제출
     ------------------------------------------------------------------ */
  const filterForm = document.querySelector("[data-filter-form]");
  if (filterForm) {
    filterForm.querySelectorAll("select").forEach((select) => {
      select.addEventListener("change", () => filterForm.requestSubmit());
    });
  }

  /* ------------------------------------------------------------------
     경주일 달력 모달
     ------------------------------------------------------------------ */
  function initRaceCalendar() {
    const modal = document.querySelector("[data-calendar-modal]");
    const openButton = document.querySelector("[data-calendar-open]");
    const closeButton = document.querySelector("[data-calendar-close]");
    const prevButton = document.querySelector("[data-calendar-prev]");
    const nextButton = document.querySelector("[data-calendar-next]");
    const yearSelect = document.querySelector("[data-calendar-year]");
    const monthSelect = document.querySelector("[data-calendar-month]");
    const monthStatus = document.querySelector("[data-calendar-month-status]");
    const grid = document.querySelector("[data-calendar-grid]");
    const valueInput = document.querySelector("[data-calendar-value]");
    const dataElement = document.querySelector("#race-calendar-data");
    if (!modal || !openButton || !prevButton || !nextButton || !yearSelect || !monthSelect
      || !monthStatus || !grid || !valueInput || !dataElement || !filterForm) {
      return;
    }

    let records = [];
    try {
      records = JSON.parse(dataElement.textContent || "[]");
    } catch (error) {
      return;
    }

    let dates = new Map(records.map((item) => [item.date, item]));
    if (!dataElement.dataset.minDate || !dataElement.dataset.maxDate) {
      openButton.disabled = true;
      return;
    }

    const parseIso = (value) => {
      const [year, month, day] = value.split("-").map(Number);
      return { year, month, day };
    };
    const toIso = (year, month, day) =>
      `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const minimum = parseIso(dataElement.dataset.minDate);
    const maximum = parseIso(dataElement.dataset.maxDate);
    const selected = parseIso(valueInput.value || dataElement.dataset.maxDate);
    let viewYear = selected.year;
    let viewMonth = selected.month;
    const monthKey = (year, month) => `${year}-${String(month).padStart(2, "0")}`;
    const monthCache = new Map([[monthKey(viewYear, viewMonth), records]]);

    const monthIndex = (year, month) => year * 12 + month - 1;
    const minimumMonth = monthIndex(minimum.year, minimum.month);
    const maximumMonth = monthIndex(maximum.year, maximum.month);
    let monthRequestSequence = 0;

    for (let year = minimum.year; year <= maximum.year; year += 1) {
      const option = document.createElement("option");
      option.value = String(year);
      option.textContent = String(year);
      yearSelect.append(option);
    }
    for (let month = 1; month <= 12; month += 1) {
      const option = document.createElement("option");
      option.value = String(month);
      option.textContent = String(month);
      monthSelect.append(option);
    }

    const clampMonth = (year, month) => Math.max(
      year === minimum.year ? minimum.month : 1,
      Math.min(year === maximum.year ? maximum.month : 12, month),
    );

    const syncControls = (year, month) => {
      yearSelect.value = String(year);
      const lowerMonth = year === minimum.year ? minimum.month : 1;
      const upperMonth = year === maximum.year ? maximum.month : 12;
      [...monthSelect.options].forEach((option) => {
        const value = Number(option.value);
        option.disabled = value < lowerMonth || value > upperMonth;
      });
      const safeMonth = clampMonth(year, month);
      monthSelect.value = String(safeMonth);
      const currentMonth = monthIndex(year, safeMonth);
      prevButton.disabled = currentMonth <= minimumMonth;
      nextButton.disabled = currentMonth >= maximumMonth;
      return safeMonth;
    };

    const render = () => {
      monthStatus.hidden = true;
      monthStatus.textContent = "";
      grid.removeAttribute("aria-busy");
      syncControls(viewYear, viewMonth);
      grid.replaceChildren();

      const firstWeekday = (new Date(viewYear, viewMonth - 1, 1).getDay() + 6) % 7;
      const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
      for (let index = 0; index < firstWeekday; index += 1) {
        const empty = document.createElement("span");
        empty.className = "calendar-day empty";
        grid.appendChild(empty);
      }

      for (let day = 1; day <= daysInMonth; day += 1) {
        const iso = toIso(viewYear, viewMonth, day);
        const record = dates.get(iso);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "calendar-day";
        button.textContent = String(day);
        button.setAttribute("role", "gridcell");
        const dateLabel = `${viewYear}년 ${viewMonth}월 ${day}일`;
        button.setAttribute("aria-label", dateLabel);

        if (!record) {
          button.disabled = true;
        } else {
          button.classList.add("has-event");
          if (record.hasRace) {
            button.classList.add("has-race", record.status);
          }
          if (record.hasTrial) {
            button.classList.add("has-trial");
          }
          const labels = [];
          if (record.hasRace) {
            const raceStatusLabel = {
              scheduled: "공식 경주 예정",
              completed: "공식 경주 종료",
              mixed: "공식 경주 예정·종료",
            }[record.status] || "공식 경주 일정";
            labels.push(raceStatusLabel);
          }
          if (record.hasTrial) {
            labels.push("주행심사");
          }
          button.title = labels.join(" · ");
          button.setAttribute("aria-label", `${dateLabel} · ${labels.join(" · ")}`);
          if (iso === valueInput.value) {
            button.classList.add("selected");
            button.setAttribute("aria-current", "date");
          }
          button.addEventListener("click", () => {
            if (grid.hasAttribute("aria-busy")) {
              return;
            }
            valueInput.value = iso;
            modal.close();
            filterForm.requestSubmit();
          });
        }
        grid.appendChild(button);
      }

    };

    const loadMonth = async (year, month) => {
      const targetYear = Math.max(minimum.year, Math.min(maximum.year, year));
      const targetMonth = clampMonth(targetYear, month);
      const key = monthKey(targetYear, targetMonth);
      const sequence = ++monthRequestSequence;
      syncControls(targetYear, targetMonth);
      monthStatus.textContent = "달력을 불러오는 중입니다.";
      monthStatus.hidden = false;
      grid.setAttribute("aria-busy", "true");

      let monthRecords = monthCache.get(key);
      if (!monthCache.has(key)) {
        try {
          const response = await fetch("/api/calendar?month=" + key);
          if (!response.ok) {
            throw new Error("calendar request failed");
          }
          monthRecords = await response.json();
          if (!Array.isArray(monthRecords)) {
            throw new Error("calendar response was invalid");
          }
          monthCache.set(key, monthRecords);
        } catch (error) {
          if (sequence !== monthRequestSequence) {
            return false;
          }
          syncControls(viewYear, viewMonth);
          grid.removeAttribute("aria-busy");
          monthStatus.textContent = "달력 정보를 불러오지 못했습니다. 다시 선택해 주세요.";
          monthStatus.hidden = false;
          return false;
        }
      }
      if (sequence !== monthRequestSequence) {
        return false;
      }
      dates = new Map(monthRecords.map((item) => [item.date, item]));
      viewYear = targetYear;
      viewMonth = targetMonth;
      render();
      return true;
    };

    openButton.addEventListener("click", () => {
      const current = parseIso(valueInput.value || dataElement.dataset.maxDate);
      modal.showModal();
      loadMonth(current.year, current.month);
    });
    closeButton.addEventListener("click", () => modal.close());
    prevButton.addEventListener("click", () => {
      const next = new Date(Number(yearSelect.value), Number(monthSelect.value) - 2, 1);
      loadMonth(next.getFullYear(), next.getMonth() + 1);
    });
    nextButton.addEventListener("click", () => {
      const next = new Date(Number(yearSelect.value), Number(monthSelect.value), 1);
      loadMonth(next.getFullYear(), next.getMonth() + 1);
    });
    yearSelect.addEventListener("change", () => {
      loadMonth(Number(yearSelect.value), Number(monthSelect.value));
    });
    monthSelect.addEventListener("change", () => {
      loadMonth(Number(yearSelect.value), Number(monthSelect.value));
    });
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        modal.close();
      }
    });
  }

  initRaceCalendar();

  function initScheduleHeaderOffset() {
    const schedule = document.querySelector("[data-dashboard-schedule]");
    const header = document.querySelector(".site-header");
    if (!schedule || !header) {
      return;
    }

    const updateOffset = () => {
      const height = header.getBoundingClientRect().height;
      if (height > 0) {
        document.documentElement.style.setProperty("--dashboard-header-height", `${height}px`);
      }
    };
    updateOffset();
    if (typeof ResizeObserver === "function") {
      scheduleHeaderResizeObserver = new ResizeObserver(updateOffset);
      scheduleHeaderResizeObserver.observe(header);
    } else {
      window.addEventListener("resize", updateOffset, { passive: true });
    }
  }

  initScheduleHeaderOffset();

  function syncScheduleHeadingHeight() {
    const schedule = document.querySelector("[data-dashboard-schedule]");
    const hero = document.querySelector("[data-dashboard-detail] .race-hero");
    if (!schedule) {
      return;
    }
    if (!hero || !window.matchMedia("(min-width: 1101px)").matches) {
      schedule.style.removeProperty("--schedule-toolbar-height");
      return;
    }
    const height = hero.getBoundingClientRect().height;
    if (height > 0) {
      schedule.style.setProperty("--schedule-toolbar-height", `${height}px`);
    }
  }

  let disposeScheduleBodyScroll = null;

  function initScheduleBodyScroll() {
    disposeScheduleBodyScroll?.();
    const schedule = document.querySelector("[data-dashboard-schedule]");
    const fixedHeader = schedule?.querySelector("[data-schedule-fixed-head]");
    const body = schedule?.querySelector("[data-schedule-body-scroll]");
    if (!schedule || !fixedHeader || !body) {
      return;
    }

    const tables = [...body.querySelectorAll("[data-schedule-table-section] table.race-table")];
    if (!tables.length) {
      return;
    }
    const wideLayout = window.matchMedia("(min-width: 1101px)");
    let activeTable = null;
    let observer = null;
    let enabled = false;
    let syncingScroll = false;
    let resizeQueued = false;

    const updateScrollbarGutter = () => {
      const width = Math.max(0, body.offsetWidth - body.clientWidth);
      schedule.style.setProperty("--schedule-scrollbar-width", `${width}px`);
    };

    const cloneHeader = (table) => {
      const visualTable = document.createElement("table");
      visualTable.className = "schedule-fixed-header-table";
      visualTable.setAttribute("aria-hidden", "true");
      visualTable.style.tableLayout = "fixed";
      const head = document.createElement("thead");
      const sourceHead = table.tHead;
      [...(sourceHead?.rows || [])].forEach((sourceRow) => {
        const row = document.createElement("tr");
        [...sourceRow.cells].forEach((sourceCell) => {
          const cell = document.createElement("th");
          cell.textContent = sourceCell.textContent.trim();
          if (sourceCell.colSpan > 1) {
            cell.colSpan = sourceCell.colSpan;
          }
          if (sourceCell.scope) {
            cell.scope = sourceCell.scope;
          }
          row.append(cell);
        });
        head.append(row);
      });
      visualTable.append(head);
      return visualTable;
    };

    const alignHeaderColumns = (table, visualTable) => {
      const sourceRow = [...(table.tBodies[0]?.rows || [])]
        .find((row) => !row.classList.contains("group-row")
          && row.cells.length === visualTable.tHead.rows[0]?.cells.length);
      const sourceCells = sourceRow ? [...sourceRow.cells] : [];
      const headerCells = [...(visualTable.tHead.rows[0]?.cells || [])];
      const widths = headerCells.map((cell, index) => {
        const width = sourceCells[index]?.getBoundingClientRect().width
          || table.tHead?.rows[0]?.cells[index]?.getBoundingClientRect().width
          || cell.getBoundingClientRect().width;
        return Math.max(0, width);
      });
      const width = Math.max(
        table.getBoundingClientRect().width,
        widths.reduce((total, value) => total + value, 0),
      );
      visualTable.style.width = `${width}px`;
      headerCells.forEach((cell, index) => {
        cell.style.width = `${widths[index]}px`;
      });
    };

    const showHeaderFor = (table) => {
      if (!table || table === activeTable) {
        return;
      }
      activeTable = table;
      const visualTable = cloneHeader(table);
      fixedHeader.replaceChildren(visualTable);
      alignHeaderColumns(table, visualTable);
      fixedHeader.scrollLeft = body.scrollLeft;
    };

    const tableAtScrollTop = () => {
      const bodyTop = body.getBoundingClientRect().top;
      let active = tables[0];
      for (const table of tables) {
        if (table.getBoundingClientRect().top <= bodyTop + 1) {
          active = table;
        } else {
          break;
        }
      }
      return active;
    };

    const onBodyScroll = () => {
      if (!syncingScroll && fixedHeader.scrollLeft !== body.scrollLeft) {
        syncingScroll = true;
        fixedHeader.scrollLeft = body.scrollLeft;
        syncingScroll = false;
      }
      showHeaderFor(tableAtScrollTop());
    };

    const onHeaderScroll = () => {
      if (!syncingScroll && body.scrollLeft !== fixedHeader.scrollLeft) {
        syncingScroll = true;
        body.scrollLeft = fixedHeader.scrollLeft;
        syncingScroll = false;
      }
    };

    const queueResize = () => {
      if (resizeQueued) {
        return;
      }
      resizeQueued = true;
      window.requestAnimationFrame(() => {
        resizeQueued = false;
        if (!enabled) {
          return;
        }
        syncScheduleHeadingHeight();
        updateScrollbarGutter();
        activeTable = null;
        showHeaderFor(tableAtScrollTop());
      });
    };

    const enable = () => {
      if (enabled) {
        return;
      }
      enabled = true;
      schedule.classList.add("has-fixed-schedule-head");
      fixedHeader.hidden = false;
      tables.forEach((table) => table.tHead?.classList.add("schedule-semantic-head"));
      body.addEventListener("scroll", onBodyScroll, { passive: true });
      fixedHeader.addEventListener("scroll", onHeaderScroll, { passive: true });
      if (typeof ResizeObserver === "function") {
        observer = new ResizeObserver(queueResize);
        observer.observe(schedule);
        observer.observe(body);
        const detailPanel = document.querySelector("[data-dashboard-detail]");
        if (detailPanel) {
          observer.observe(detailPanel);
        }
        tables.forEach((table) => observer.observe(table));
      } else {
        window.addEventListener("resize", queueResize, { passive: true });
      }
      syncScheduleHeadingHeight();
      updateScrollbarGutter();
      showHeaderFor(tableAtScrollTop());
    };

    const disable = () => {
      if (!enabled) {
        return;
      }
      enabled = false;
      observer?.disconnect();
      observer = null;
      window.removeEventListener("resize", queueResize);
      body.removeEventListener("scroll", onBodyScroll);
      fixedHeader.removeEventListener("scroll", onHeaderScroll);
      schedule.classList.remove("has-fixed-schedule-head");
      schedule.style.removeProperty("--schedule-scrollbar-width");
      schedule.style.removeProperty("--schedule-toolbar-height");
      tables.forEach((table) => table.tHead?.classList.remove("schedule-semantic-head"));
      fixedHeader.replaceChildren();
      fixedHeader.hidden = true;
      activeTable = null;
    };

    const syncMode = () => {
      if (wideLayout.matches) {
        enable();
      } else {
        disable();
      }
    };
    wideLayout.addEventListener("change", syncMode);
    syncMode();
    disposeScheduleBodyScroll = () => {
      disable();
      wideLayout.removeEventListener("change", syncMode);
    };
  }

  initScheduleBodyScroll();

  /* ------------------------------------------------------------------
     클릭 가능한 행 내비게이션
     ------------------------------------------------------------------ */
  let dashboardSelectionController = null;
  let dashboardSelectionSequence = 0;
  const dashboardInitialUrl = new URL(window.location.href);
  const dashboardScheduleAtLoad = document.querySelector("[data-dashboard-schedule]");
  const firstDashboardRace = dashboardScheduleAtLoad?.querySelector("[data-dashboard-race-id]");
  let dashboardFilterUrl = new URL(firstDashboardRace?.dataset.href || dashboardInitialUrl.href,
    window.location.href);
  const dashboardSelectionEnabled = Boolean(
    dashboardScheduleAtLoad && document.querySelector("[data-dashboard-detail]")
  );

  function dashboardFiltersMatch(target, current) {
    const withoutRaceId = (url) => [...url.searchParams.entries()]
      .filter(([key]) => key !== "race_id")
      .sort(([leftKey, leftValue], [rightKey, rightValue]) =>
        leftKey.localeCompare(rightKey) || leftValue.localeCompare(rightValue)
      );
    return JSON.stringify(withoutRaceId(target)) === JSON.stringify(withoutRaceId(current));
  }

  function isDashboardSelectionUrl(value, allowDefault = false) {
    try {
      const target = new URL(value, window.location.href);
      const raceIds = target.searchParams.getAll("race_id");
      const validRaceId = raceIds.length === 1 && /^[1-9]\d*$/.test(raceIds[0]);
      const defaultRace = allowDefault && raceIds.length === 0;
      const matchesFilters = dashboardFiltersMatch(target, dashboardFilterUrl);
      const matchesInitialUrl = defaultRace && dashboardFiltersMatch(target, dashboardInitialUrl);
      return target.origin === window.location.origin
        && target.pathname === dashboardInitialUrl.pathname
        && ((validRaceId && matchesFilters)
          || (defaultRace && (matchesFilters || matchesInitialUrl)));
    } catch (error) {
      return false;
    }
  }

  function safeRaceDetailHref(value) {
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin && /^\/races\/[1-9]\d*$/.test(url.pathname)
        ? url.href
        : null;
    } catch (error) {
      return null;
    }
  }

  function isDashboardVenueUrl(value) {
    try {
      const target = new URL(value, window.location.href);
      const selectedDate = document.querySelector("[data-calendar-value]")?.value;
      return target.origin === window.location.origin
        && target.pathname === dashboardInitialUrl.pathname
        && [...target.searchParams.keys()].every((key) => ["date", "meet", "race_id"].includes(key))
        && [...new Set(target.searchParams.keys())].every((key) => target.searchParams.getAll(key).length === 1)
        && (target.searchParams.get("date") === selectedDate
          || dashboardFiltersMatch(target, dashboardInitialUrl))
        && /^(?:[1-4])?$/.test(target.searchParams.get("meet") || "")
        && (!target.searchParams.has("race_id") || /^[1-9]\d*$/.test(target.searchParams.get("race_id")));
    } catch (error) {
      return false;
    }
  }

  function animateDashboardContent(elements) {
    if (REDUCED_MOTION || typeof Element.prototype.animate !== "function") {
      return;
    }
    elements.filter((element) => element && !element.hidden).forEach((element) => {
      try {
        element.animate([{ opacity: 0.8 }, { opacity: 1 }], {
          duration: 170,
          easing: "ease-out",
        });
      } catch (error) { /* animation is decorative */ }
    });
  }

  function showDashboardSelectionError(panel, href, detailHref, pushHistory, allowDefault) {
    const status = panel.querySelector("[data-dashboard-detail-status]");
    if (!status) {
      return;
    }
    status.replaceChildren(document.createTextNode("출전마 정보를 불러오지 못했습니다. "));
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "다시 시도";
    retry.addEventListener("click", () =>
      loadDashboardRace(href, detailHref, pushHistory, allowDefault)
    );
    status.append(retry);

    const safeDetailHref = safeRaceDetailHref(detailHref);
    if (safeDetailHref) {
      const detail = document.createElement("a");
      detail.href = safeDetailHref;
      detail.textContent = "경주 상세 보기";
      status.append(document.createTextNode(" · "), detail);
    }
    status.hidden = false;
  }

  function sanitizeDashboardPanel(panel) {
    panel.querySelectorAll("script, iframe, object, embed, base, link, meta").forEach((node) => node.remove());
    [panel, ...panel.querySelectorAll("*")].forEach((node) => {
      [...node.attributes].forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        if (name.startsWith("on")) {
          node.removeAttribute(attribute.name);
        } else if (["href", "src", "xlink:href", "formaction"].includes(name)
          && /^\s*javascript:/i.test(attribute.value)) {
          node.removeAttribute(attribute.name);
        }
      });
    });
  }

  async function loadDashboardRace(value, detailHref, pushHistory = true, allowDefault = false, updateSchedule = false) {
    if (!(updateSchedule ? isDashboardVenueUrl(value) : isDashboardSelectionUrl(value, allowDefault))) {
      return false;
    }
    const target = new URL(value, window.location.href);
    const schedule = document.querySelector("[data-dashboard-schedule]");
    const currentPanel = document.querySelector("[data-dashboard-detail]");
    if (!schedule || !currentPanel) {
      return false;
    }

    if (dashboardSelectionController) {
      dashboardSelectionController.abort();
    }
    const controller = new AbortController();
    dashboardSelectionController = controller;
    const sequence = ++dashboardSelectionSequence;
    const raceId = target.searchParams.get("race_id");
    const status = currentPanel.querySelector("[data-dashboard-detail-status]");
    if (status) {
      status.hidden = true;
      status.replaceChildren();
    }
    schedule.setAttribute("aria-busy", "true");
    currentPanel.setAttribute("aria-busy", "true");

    try {
      const response = await fetch(target.href, {
        credentials: "same-origin",
        headers: { Accept: "text/html" },
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error("dashboard selection request failed");
      }
      const responseUrl = new URL(response.url || target.href, window.location.href);
      if (responseUrl.origin !== window.location.origin
        || responseUrl.pathname !== window.location.pathname
        || !dashboardFiltersMatch(responseUrl, target)) {
        throw new Error("dashboard selection response location was invalid");
      }
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, "text/html");
      const incomingSchedule = parsed.querySelector("[data-dashboard-schedule]");
      const incomingPanel = parsed.querySelector("[data-dashboard-detail]");
      const responseRaceId = incomingPanel?.dataset.raceId;
      const raceIsInSchedule = responseRaceId && [...(updateSchedule ? incomingSchedule : schedule)?.querySelectorAll(
        "[data-dashboard-race-id]"
      ) || []].some((row) => row.dataset.dashboardRaceId === responseRaceId);
      if (!incomingPanel || (updateSchedule && !incomingSchedule?.querySelector("[data-schedule-body-scroll]"))
        || (!raceIsInSchedule && !(updateSchedule && incomingPanel.hidden && !responseRaceId))
        || (raceId && responseRaceId !== raceId)) {
        throw new Error("dashboard selection response panel was invalid");
      }
      sanitizeDashboardPanel(incomingPanel);
      if (updateSchedule) {
        sanitizeDashboardPanel(incomingSchedule);
      }
      if (controller.signal.aborted || sequence !== dashboardSelectionSequence) {
        return false;
      }

      const replacement = document.importNode(incomingPanel, true);
      const previousPanel = document.querySelector("[data-dashboard-detail]");
      if (!previousPanel) {
        throw new Error("dashboard detail panel is unavailable");
      }
      previousPanel.replaceChildren(...replacement.childNodes);
      previousPanel.dataset.raceId = responseRaceId;
      previousPanel.hidden = incomingPanel.hidden;
      if (updateSchedule) {
        disposeScheduleBodyScroll?.();
        const body = schedule.querySelector("[data-schedule-body-scroll]");
        const incomingBody = document.importNode(incomingSchedule.querySelector("[data-schedule-body-scroll]"), true);
        body.replaceChildren(...incomingBody.childNodes);
        body.scrollTop = 0;
        const venueBar = schedule.querySelector(".schedule-venue-filter");
        const incomingVenueBar = incomingSchedule.querySelector(".schedule-venue-filter");
        if (venueBar && incomingVenueBar) {
          venueBar.replaceChildren(...document.importNode(incomingVenueBar, true).childNodes);
        }
        const form = schedule.querySelector("[data-filter-form]");
        form.querySelector('input[name="meet"]')?.remove();
        const meetInput = incomingSchedule.querySelector('input[name="meet"]');
        if (meetInput) {
          form.append(document.importNode(meetInput, true));
        }
        schedule.querySelectorAll(".schedule-date-arrow[href]").forEach((arrow) => {
          const incomingArrow = incomingSchedule.querySelector(`.schedule-date-arrow[aria-label="${arrow.getAttribute("aria-label")}"]`);
          if (incomingArrow?.hasAttribute("href")) {
            arrow.setAttribute("href", incomingArrow.getAttribute("href"));
          }
        });
        dashboardFilterUrl = new URL(target.href);
        initScheduleBodyScroll();
        initClickableRows(body);
        animateDashboardContent([body]);
      }
      syncScheduleHeadingHeight();
      initSortableTables(previousPanel);
      animateDashboardContent([...previousPanel.children]);
      schedule.querySelectorAll("[data-dashboard-race-id]").forEach((row) => {
        row.classList.toggle("selected", row.dataset.dashboardRaceId === previousPanel.dataset.raceId);
      });
      if (pushHistory) {
        window.history.pushState({ dashboardRaceSelection: true }, "", target.href);
      }
      schedule.removeAttribute("aria-busy");
      previousPanel.removeAttribute("aria-busy");
      return true;
    } catch (error) {
      if (controller.signal.aborted || sequence !== dashboardSelectionSequence) {
        return false;
      }
      schedule.removeAttribute("aria-busy");
      currentPanel.removeAttribute("aria-busy");
      if (updateSchedule) {
        window.location.assign(target.href);
      } else {
        showDashboardSelectionError(currentPanel, target.href, detailHref, pushHistory, allowDefault);
      }
      return false;
    } finally {
      if (sequence === dashboardSelectionSequence) {
        dashboardSelectionController = null;
      }
    }
  }

  document.addEventListener("click", (event) => {
    const venueLink = event.target instanceof Element
      ? event.target.closest(".schedule-venue-button")
      : null;
    if (dashboardSelectionEnabled && venueLink && !event.defaultPrevented && event.button === 0
      && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
      && isDashboardVenueUrl(venueLink.href)) {
      event.preventDefault();
      loadDashboardRace(venueLink.href, null, true, true, true);
      return;
    }
    const link = event.target instanceof Element
      ? event.target.closest("a[data-dashboard-race-select]")
      : null;
    if (!link || event.defaultPrevented || event.button !== 0
      || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
      || (link.target && link.target !== "_self") || link.hasAttribute("download")) {
      return;
    }
    if (!isDashboardSelectionUrl(link.href)) {
      return;
    }
    if (!document.querySelector("[data-dashboard-schedule]")
      || !document.querySelector("[data-dashboard-detail]")) {
      return;
    }
    event.preventDefault();
    loadDashboardRace(link.href, link.dataset.raceDetailHref);
  });

  if (dashboardSelectionEnabled) {
    window.addEventListener("popstate", () => {
      const current = new URL(window.location.href);
      if (!dashboardFiltersMatch(current, dashboardFilterUrl) && isDashboardVenueUrl(current.href)) {
        loadDashboardRace(current.href, null, false, true, true);
        return;
      }
      if (!isDashboardSelectionUrl(current.href, true)) {
        window.location.reload();
        return;
      }
      const panel = document.querySelector("[data-dashboard-detail]");
      const raceId = current.searchParams.get("race_id") || panel?.dataset.raceId;
      const selectedRow = [...document.querySelectorAll("[data-dashboard-race-id]")]
        .find((row) => row.dataset.dashboardRaceId === raceId);
      loadDashboardRace(current.href, selectedRow?.dataset.raceDetailHref, false, true);
    });
  }

  function initClickableRows(root = document) {
    root.querySelectorAll("[data-href]").forEach((row) => {
      if (row.dataset.navigationInitialized === "true") {
        return;
      }
      row.dataset.navigationInitialized = "true";
      const href = row.dataset.href;
      if (!href) {
        return;
      }

      const navigate = (newTab) => {
        if (newTab) {
          window.open(href, "_blank", "noopener");
          return;
        }
        if (row.matches("[data-dashboard-race-id]")) {
          if (isDashboardSelectionUrl(href)
            && document.querySelector("[data-dashboard-schedule]")
            && document.querySelector("[data-dashboard-detail]")) {
            loadDashboardRace(href, row.dataset.raceDetailHref);
          } else {
            window.location.href = href;
          }
          return;
        }
        window.location.href = href;
      };

      row.addEventListener("click", (event) => {
        if (event.target.closest("a, button, input, select, label")) {
          return;
        }
        navigate(event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1);
      });
      row.addEventListener("keydown", (event) => {
        if (event.target.closest("a, button, input, select, label")) {
          return;
        }
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          navigate(event.metaKey || event.ctrlKey);
        }
      });
    });
  }

  initClickableRows();

  /* ------------------------------------------------------------------
     말 이력 탭
     ------------------------------------------------------------------ */
  document.querySelectorAll("[data-history-tabs]").forEach((root) => {
    const tabs = [...root.querySelectorAll("[data-tab]")];
    const panes = [...root.querySelectorAll("[data-pane]")];

    const activate = (key) => {
      tabs.forEach((tab) => {
        const active = tab.getAttribute("data-tab") === key;
        tab.classList.toggle("is-active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
      });
      panes.forEach((pane) => {
        pane.classList.toggle("is-active", pane.getAttribute("data-pane") === key);
      });
    };

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => activate(tab.getAttribute("data-tab") || ""));
    });
  });

  /* ------------------------------------------------------------------
     요약 숫자 카운트업
     ------------------------------------------------------------------ */
  function initCountUp() {
    if (REDUCED_MOTION) {
      return;
    }
    const formatter = new Intl.NumberFormat("ko-KR");
    document.querySelectorAll("[data-countup]").forEach((element) => {
      const raw = element.textContent.trim();
      if (!/^\d[\d,]*$/.test(raw)) {
        return;
      }
      const target = Number(raw.replace(/,/g, ""));
      if (!Number.isFinite(target) || target === 0) {
        return;
      }
      const useComma = raw.includes(",");
      const duration = 650;
      const start = performance.now();
      const tick = (now) => {
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const value = Math.round(target * eased);
        element.textContent = useComma ? formatter.format(value) : String(value);
        if (progress < 1) {
          requestAnimationFrame(tick);
        }
      };
      requestAnimationFrame(tick);
    });
  }

  initCountUp();

  /* ------------------------------------------------------------------
     테이블 컬럼 정렬 (data-sortable)
     ------------------------------------------------------------------ */
  function cellSortValue(text) {
    const trimmed = text.trim();
    if (!trimmed || trimmed === "—" || trimmed === "-") {
      return { missing: true, number: null, text: "" };
    }
    // "1:13.5" 형태의 기록은 초 단위로 변환
    const timeMatch = trimmed.match(/^(\d+):(\d+(?:\.\d+)?)/);
    if (timeMatch) {
      return {
        missing: false,
        number: Number(timeMatch[1]) * 60 + Number(timeMatch[2]),
        text: trimmed,
      };
    }
    const numberMatch = trimmed.replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
    return {
      missing: false,
      number: numberMatch ? Number(numberMatch[0]) : null,
      text: trimmed,
    };
  }

  function initSortableTables(root = document) {
    const tables = root.matches?.("table[data-sortable]")
      ? [root]
      : root.querySelectorAll("table[data-sortable]");
    tables.forEach((table) => {
      if (table.dataset.sortableInitialized === "true") {
        return;
      }
      const tbody = table.querySelector("tbody");
      const headRow = table.querySelector("thead tr");
      if (!tbody || !headRow) {
        return;
      }
      table.dataset.sortableInitialized = "true";
      const headers = [...headRow.children];

      headers.forEach((th, columnIndex) => {
        if (th.hasAttribute("data-server-sort")) {
          const link = th.querySelector("a[href]");
          th.addEventListener("click", (event) => {
            if (link && !event.target.closest("a")) link.click();
          });
          return;
        }
        if (!th.textContent.trim()) {
          return;
        }
        th.classList.add("sortable-col");
        th.tabIndex = 0;
        th.setAttribute("role", "button");

        const sortBy = () => {
          const direction = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
          headers.forEach((other) => other.removeAttribute("aria-sort"));
          th.setAttribute("aria-sort", direction);

          const rows = [...tbody.querySelectorAll("tr")];
          const keyed = rows.map((row, order) => {
            const cell = row.children[columnIndex];
            const sortText = cell?.dataset.sortValue ?? cell?.textContent ?? "";
            return { row, order, value: cellSortValue(sortText) };
          });

          const useNumber = keyed.some((item) => item.value.number != null);
          const sign = direction === "ascending" ? 1 : -1;

          keyed.sort((a, b) => {
            if (a.value.missing !== b.value.missing) {
              return a.value.missing ? 1 : -1; // 결측값은 항상 아래로
            }
            if (a.value.missing) {
              return a.order - b.order;
            }
            if (useNumber && a.value.number != null && b.value.number != null) {
              if (a.value.number !== b.value.number) {
                return (a.value.number - b.value.number) * sign;
              }
            } else {
              const compared = a.value.text.localeCompare(b.value.text, "ko");
              if (compared !== 0) {
                return compared * sign;
              }
            }
            return a.order - b.order;
          });

          keyed.forEach((item) => tbody.appendChild(item.row));
        };

        th.addEventListener("click", sortBy);
        th.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            sortBy();
          }
        });
      });
    });
  }

  initSortableTables();

  /* ------------------------------------------------------------------
     경주 상세 목차 스크롤 스파이
     ------------------------------------------------------------------ */
  function initScrollSpy() {
    const toc = document.querySelector(".page-toc");
    if (!toc || !("IntersectionObserver" in window)) {
      return;
    }
    const links = [...toc.querySelectorAll('a[href^="#"]')];
    const sections = links
      .map((link) => document.querySelector(link.getAttribute("href")))
      .filter(Boolean);
    if (!sections.length) {
      return;
    }

    const setCurrent = (id) => {
      links.forEach((link) => {
        link.classList.toggle("is-current", link.getAttribute("href") === `#${id}`);
      });
    };

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length) {
          setCurrent(visible[0].target.id);
        }
      },
      { rootMargin: "-15% 0px -65% 0px" }
    );

    sections.forEach((section) => observer.observe(section));
  }

  initScrollSpy();

  function initMobileMenu() {
    const drawer = document.querySelector("[data-mobile-menu]");
    if (!drawer) {
      return;
    }
    const openButtons = document.querySelectorAll("[data-mobile-menu-open]");
    const closeButtons = drawer.querySelectorAll("[data-mobile-menu-close]");

    const setOpen = (open) => {
      drawer.hidden = !open;
      document.body.classList.toggle("mobile-menu-open", open);
      openButtons.forEach((button) => button.setAttribute("aria-expanded", open ? "true" : "false"));
    };

    openButtons.forEach((button) => {
      button.addEventListener("click", () => setOpen(drawer.hidden));
    });
    closeButtons.forEach((button) => {
      button.addEventListener("click", () => setOpen(false));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !drawer.hidden) {
        setOpen(false);
      }
    });
  }

  initMobileMenu();

  /* ------------------------------------------------------------------
     더비온 앱 열기 (한국마사회 공식 앱, 스토어 미등록)
     2.0이 있으면 2.0, 없으면 1.0(구 더비온)으로 연결한다.
     2.0: mycard5 / kr.co.kra.m.mycard5
     1.0: mycard4 / kr.co.kra.m.mycard4
     ------------------------------------------------------------------ */
  const DERBYON_V2 = { scheme: "mycard5", pkg: "kr.co.kra.m.mycard5" };
  const DERBYON_V1 = { scheme: "mycard4", pkg: "kr.co.kra.m.mycard4" };
  const DERBYON_FALLBACK = "https://m.kra.co.kr/comp/view/kraAppList.do";
  const DERBYON_WAIT_MS = 900;

  function derbyOnLeftPage() {
    return document.hidden || document.visibilityState === "hidden";
  }

  function derbyOnAfterWait(fn) {
    const started = Date.now();
    const timer = window.setTimeout(() => {
      if (derbyOnLeftPage()) {
        return;
      }
      if (Date.now() - started < DERBYON_WAIT_MS - 80) {
        return;
      }
      fn();
    }, DERBYON_WAIT_MS);
    const cancel = () => window.clearTimeout(timer);
    document.addEventListener(
      "visibilitychange",
      () => {
        if (derbyOnLeftPage()) {
          cancel();
        }
      },
      { once: true }
    );
    window.addEventListener("pagehide", cancel, { once: true });
  }

  function androidLaunchIntent(app, fallback) {
    let url =
      "intent:#Intent;action=android.intent.action.MAIN;category=android.intent.category.LAUNCHER;package=" +
      app.pkg;
    if (fallback) {
      url += ";S.browser_fallback_url=" + encodeURIComponent(fallback);
    }
    return url + ";end";
  }

  function openDerbyOnApp() {
    const ua = navigator.userAgent || "";
    const isAndroid = /Android/i.test(ua);
    const isIOS = /iPhone|iPad|iPod/i.test(ua);

    if (isAndroid) {
      window.location.href = androidLaunchIntent(DERBYON_V2);
      derbyOnAfterWait(() => {
        window.location.href = androidLaunchIntent(DERBYON_V1, DERBYON_FALLBACK);
      });
      return;
    }

    if (isIOS) {
      window.location.href = DERBYON_V2.scheme + "://";
      derbyOnAfterWait(() => {
        window.location.href = DERBYON_V1.scheme + "://";
        derbyOnAfterWait(() => {
          window.location.href = DERBYON_FALLBACK;
        });
      });
      return;
    }

    window.location.href = DERBYON_FALLBACK;
  }

  document.querySelectorAll("[data-open-derbyon]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      openDerbyOnApp();
    });
  });

  /* ------------------------------------------------------------------
     모바일 고정 영역: 아래로 스크롤하면 로고 줄·필터 줄·하단 탭을 접고
     라운드 칩만 남긴다. 위로 스크롤하거나 맨 위 근처면 다시 펼친다.
     ------------------------------------------------------------------ */
  const mobileChrome = (() => {
    const body = document.body;
    const root = document.documentElement;
    const chrome = document.querySelector("[data-mobile-chrome]");
    const topbar = document.querySelector(".mobile-topbar");
    if (!body.classList.contains("mobile-app") || !chrome || !topbar) {
      return null;
    }
    const filters = chrome.querySelector("[data-chrome-filters]");
    const THRESHOLD = 8;
    let condensed = false;
    let anchorY = window.scrollY;
    let lockedUntil = 0;
    let ticking = false;
    let metrics = { topShift: 0, filterShift: 0, full: 0 };

    function bottom(state = condensed) {
      return state ? metrics.full - metrics.topShift - metrics.filterShift : metrics.full;
    }

    function publish() {
      root.style.setProperty("--mobile-chrome-bottom", `${Math.round(bottom())}px`);
      root.style.setProperty("--mobile-sticky-clearance", `${Math.round(bottom() + 12)}px`);
    }

    function measure() {
      const topPadding = parseFloat(getComputedStyle(topbar).paddingTop) || 0;
      const gap = parseFloat(getComputedStyle(chrome).rowGap) || 0;
      metrics = {
        topShift: topbar.offsetHeight - topPadding,
        filterShift: filters ? filters.offsetHeight + gap : 0,
        full: topbar.offsetHeight + chrome.offsetHeight,
      };
      root.style.setProperty("--mobile-topbar-shift", `${metrics.topShift}px`);
      root.style.setProperty("--mobile-chrome-filter-shift", `${metrics.filterShift}px`);
      publish();
    }

    function setCondensed(next) {
      if (next === condensed) {
        return;
      }
      condensed = next;
      body.classList.toggle("chrome-condensed", next);
      publish();
    }

    function sync() {
      ticking = false;
      const y = window.scrollY;
      if (performance.now() < lockedUntil) {
        anchorY = y;
        return;
      }
      if (y <= metrics.full) {
        setCondensed(false);
        anchorY = y;
        return;
      }
      const delta = y - anchorY;
      if (Math.abs(delta) < THRESHOLD) {
        return;
      }
      setCondensed(delta > 0);
      anchorY = y;
    }

    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("pageshow", measure);
    window.addEventListener(
      "scroll",
      () => {
        if (!ticking) {
          ticking = true;
          requestAnimationFrame(sync);
        }
      },
      { passive: true }
    );

    return {
      bottom,
      setCondensed,
      lock(ms) {
        lockedUntil = performance.now() + ms;
      },
      isCondensed: () => condensed,
      full: () => metrics.full,
    };
  })();

  function mobileStickyClearance() {
    if (mobileChrome) {
      return mobileChrome.bottom() + 12;
    }
    const topbar = document.querySelector(".mobile-topbar");
    return (topbar ? topbar.getBoundingClientRect().bottom : 0) + 12;
  }

  function scrollToMobileRound(id) {
    const target = document.getElementById(id);
    if (!target) {
      return;
    }
    const absolute = window.scrollY + target.getBoundingClientRect().top;
    if (mobileChrome) {
      mobileChrome.lock(800);
      const condensedTop = absolute - mobileChrome.bottom(true) - 12;
      mobileChrome.setCondensed(condensedTop > mobileChrome.full());
    }
    const top = absolute - mobileStickyClearance();
    window.scrollTo({ top: Math.max(0, top), behavior: "auto" });
  }

  function revealJumpChip(chip) {
    if (!chip) {
      return;
    }
    const nav = chip.closest(".mobile-round-jump");
    if (!nav) {
      return;
    }
    const navBox = nav.getBoundingClientRect();
    const chipBox = chip.getBoundingClientRect();
    if (chipBox.left >= navBox.left + 8 && chipBox.right <= navBox.right - 8) {
      return;
    }
    const offset = chipBox.left - navBox.left - (navBox.width - chipBox.width) / 2;
    nav.scrollTo({
      left: Math.max(0, nav.scrollLeft + offset),
      behavior: REDUCED_MOTION ? "auto" : "smooth",
    });
  }

  function jumpChipId(link) {
    return link.dataset.roundId || decodeURIComponent((link.hash || "").slice(1));
  }

  function setMobileRoundSelection(id, { reveal = false } = {}) {
    document.querySelectorAll(".mobile-round-jump").forEach((nav) => {
      let selected = null;
      nav.querySelectorAll("a[data-round-id], a[href^='#']").forEach((link) => {
        const on = jumpChipId(link) === id;
        link.classList.toggle("active", on);
        if (on) {
          link.setAttribute("aria-current", "true");
          selected = link;
        } else {
          link.removeAttribute("aria-current");
        }
      });
      if (reveal) {
        revealJumpChip(selected);
      }
    });
  }

  function initMobileRoundJump() {
    const links = [...document.querySelectorAll(".mobile-round-jump a[href^='#']")];
    if (!links.length) {
      return;
    }

    let lockedUntil = 0;
    let ticking = false;

    links.forEach((link) => {
      const id = jumpChipId(link);
      if (!id) {
        return;
      }
      link.dataset.roundId = id;
      // 네이티브 #id 점프가 카드를 고정 메뉴 위로 올린 뒤 JS가 다시 맞추는 깜빡임을 막는다.
      link.setAttribute("href", "#_");
      link.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          lockedUntil = performance.now() + 800;
          setMobileRoundSelection(id, { reveal: true });
          scrollToMobileRound(id);
        },
        true
      );
    });

    const sections = [...document.querySelectorAll(".mobile-round[id]")];
    if (!document.body.classList.contains("mobile-home") || !sections.length) {
      return;
    }

    const syncFromScroll = () => {
      ticking = false;
      if (performance.now() < lockedUntil) {
        return;
      }
      const clearance = mobileStickyClearance();
      let current = sections[0];
      sections.forEach((section) => {
        if (section.getBoundingClientRect().top - clearance <= 12) {
          current = section;
        }
      });
      if (current) {
        setMobileRoundSelection(current.id, { reveal: true });
      }
    };

    window.addEventListener(
      "scroll",
      () => {
        if (ticking) {
          return;
        }
        ticking = true;
        requestAnimationFrame(syncFromScroll);
      },
      { passive: true }
    );
  }

  initMobileRoundJump();

  if (document.body.classList.contains("mobile-home")) {
    if (history.scrollRestoration) {
      history.scrollRestoration = "manual";
    }
    const initial = decodeURIComponent((location.hash || "").slice(1));
    if (initial.startsWith("round")) {
      setMobileRoundSelection(initial, { reveal: true });
      requestAnimationFrame(() => scrollToMobileRound(initial));
    }
  }
})();
