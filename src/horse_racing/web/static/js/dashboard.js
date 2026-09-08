(() => {
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
    window.dispatchEvent(new CustomEvent("hr:themechange", { detail: { theme } }));
  }

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
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
    const monthLabel = document.querySelector("[data-calendar-month-label]");
    const grid = document.querySelector("[data-calendar-grid]");
    const valueInput = document.querySelector("[data-calendar-value]");
    const dataElement = document.querySelector("#race-calendar-data");
    if (!modal || !openButton || !grid || !valueInput || !dataElement || !filterForm) {
      return;
    }

    let records = [];
    try {
      records = JSON.parse(dataElement.textContent || "[]");
    } catch (error) {
      return;
    }

    const dates = new Map(records.map((item) => [item.date, item]));
    const sortedDates = [...dates.keys()].sort();
    if (!sortedDates.length) {
      openButton.disabled = true;
      return;
    }

    const parseIso = (value) => {
      const [year, month, day] = value.split("-").map(Number);
      return { year, month, day };
    };
    const toIso = (year, month, day) =>
      `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const selected = parseIso(valueInput.value || sortedDates[sortedDates.length - 1]);
    const minimum = parseIso(sortedDates[0]);
    const maximum = parseIso(sortedDates[sortedDates.length - 1]);
    let viewYear = selected.year;
    let viewMonth = selected.month;

    const monthIndex = (year, month) => year * 12 + month - 1;
    const minimumMonth = monthIndex(minimum.year, minimum.month);
    const maximumMonth = monthIndex(maximum.year, maximum.month);

    const render = () => {
      monthLabel.textContent = `${viewYear}년 ${viewMonth}월`;
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
        button.setAttribute("aria-label", `${viewYear}년 ${viewMonth}월 ${day}일`);

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
            labels.push(record.status === "scheduled" ? "공식 경주 예정" : "공식 경주 결과 있음");
          }
          if (record.hasTrial) {
            labels.push("주행심사 결과 있음");
          }
          button.title = labels.join(" · ");
          if (iso === valueInput.value) {
            button.classList.add("selected");
            button.setAttribute("aria-current", "date");
          }
          button.addEventListener("click", () => {
            valueInput.value = iso;
            modal.close();
            filterForm.requestSubmit();
          });
        }
        grid.appendChild(button);
      }

      const currentMonth = monthIndex(viewYear, viewMonth);
      prevButton.disabled = currentMonth <= minimumMonth;
      nextButton.disabled = currentMonth >= maximumMonth;
    };

    const moveMonth = (delta) => {
      const nextDate = new Date(viewYear, viewMonth - 1 + delta, 1);
      viewYear = nextDate.getFullYear();
      viewMonth = nextDate.getMonth() + 1;
      render();
    };

    openButton.addEventListener("click", () => {
      const current = parseIso(valueInput.value || sortedDates[sortedDates.length - 1]);
      viewYear = current.year;
      viewMonth = current.month;
      render();
      modal.showModal();
    });
    closeButton.addEventListener("click", () => modal.close());
    prevButton.addEventListener("click", () => moveMonth(-1));
    nextButton.addEventListener("click", () => moveMonth(1));
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        modal.close();
      }
    });
  }

  initRaceCalendar();

  /* ------------------------------------------------------------------
     클릭 가능한 행 내비게이션
     ------------------------------------------------------------------ */
  document.querySelectorAll("[data-href]").forEach((row) => {
    const href = row.dataset.href;
    if (!href) {
      return;
    }

    const navigate = (newTab) => {
      if (newTab) {
        window.open(href, "_blank", "noopener");
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
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        navigate(event.metaKey || event.ctrlKey);
      }
    });
  });

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

  function initSortableTables() {
    document.querySelectorAll("table[data-sortable]").forEach((table) => {
      const tbody = table.querySelector("tbody");
      const headRow = table.querySelector("thead tr");
      if (!tbody || !headRow) {
        return;
      }
      const headers = [...headRow.children];

      headers.forEach((th, columnIndex) => {
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
            return { row, order, value: cellSortValue(cell ? cell.textContent : "") };
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
})();
