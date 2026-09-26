"""Generate the two 경주 tab design drafts (pre-race 출마표 / post-race 결과·기록표)."""
from __future__ import annotations

import itertools
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "drafts"
SYMBOL = "../../../../src/horse_racing/web/static/images/brand/mapilog-symbol-color.svg"
WORDMARK = "../../../../src/horse_racing/web/static/images/brand/mapilog-wordmark-color.svg"

_ids = itertools.count(1)


def aid(prefix: str) -> str:
    return f'id="{prefix}-{next(_ids)}"'


# (num, name, meta, jockey, trainer, owner, carried, body, delta, rating, finish, time, margin, win, place)
ENTRIES = [
    (8, "판타스틱밸류", "4세 · 한국 · 암", "서승운", "손병철", "무지개렌트카", "55", 462, -6, 83, 1, "1:24.1", "—", 6.5, 2.5),
    (4, "라온포레스트", "6세 · 한국 · 암", "최범현", "이강서", "라온랜드(주)", "55", 509, 27, 108, 2, "1:25.5", "8", 16.2, 2.7),
    (16, "여수슈퍼스타", "4세 · 한국 · 암", "최은경", "이상영", "박세완", "55", 465, -12, 71, 3, "1:25.5", "머리", 84.3, 15.9),
    (12, "클리어리위너", "3세 · 한국 · 암", "다실바", "구영준", "신우철", "53.5", 471, -4, 65, 4, "1:26.1", "3", 6.4, 2.2),
    (5, "즐거운여정", "6세 · 한국 · 암", "진겸", "이상영", "(주)나스카", "55", 484, -12, 109, 5, "1:26.2", "¾", 20.5, 3.8),
    (9, "플라잉데이", "4세 · 한국 · 암", "김용근", "이준철", "김형순", "55", 476, 0, 80, 6, "1:26.2", "½", 68.9, 12.3),
    (15, "타이거로어", "3세 · 한국 · 암", "루이스", "정호익", "에릭 코", "53.5", 493, 5, 55, 7, "1:26.4", "1", 127.2, 27.6),
    (10, "보령라이트퀸", "4세 · 한국 · 암", "정도윤", "임금만", "최원길", "55", 504, 10, 95, 8, "1:26.5", "½", 4.9, 2.0),
    (2, "클럽큐", "4세 · 한국 · 암", "김아현", "최영주", "최홍일", "55", 440, -4, 65, 9, "1:26.6", "½", 35.7, 9.1),
    (6, "글라디우스", "5세 · 한국 · 암", "임기원", "강성오", "김기종", "55", 491, 17, 106, 10, "1:26.6", "머리", 2.5, 1.4),
    (1, "선라이즈", "3세 · 한국 · 암", "채상현", "하무선", "김근영", "53.5", 465, -7, 60, 11, "1:26.6", "머리", 52.1, 12.6),
    (11, "캐치레이스", "3세 · 한국 · 암", "이동하", "서인석", "고재완", "53.5", 514, 12, 65, 12, "1:27.0", "1¾", 29.3, 6.3),
    (14, "뱅뱅뱅", "5세 · 한국 · 암", "조인권", "임성실", "혼디", "55", 477, -7, 88, 13, "1:27.1", "¾", 48.2, 8.8),
    (13, "라온사일런스", "4세 · 한국 · 암", "장추열", "이강서", "라온랜드(주)", "55", 488, 12, 78, 14, "1:27.7", "4", 20.2, 6.3),
    (7, "에이스하이", "4세 · 한국 · 암", "이현종", "하무선", "투애니포", "55", 502, 2, 86, 15, "1:28.1", "2½", 31.8, 7.3),
    (3, "오늘도스마일", "4세 · 한국 · 암", "이용호", "문병기", "(주)나스카", "55", 495, 12, 87, 16, "1:34.1", "34", 73.2, 10.5),
]
# passing positions S1F, 3C, G3F, 4C, G1F (finish is the finish column)
POS = {8: [2, 1, 1, 1, 1], 4: [12, 10, 10, 9, 6], 16: [4, 4, 5, 5, 3], 12: [8, 8, 4, 4, 5], 5: [7, 3, 3, 3, 2],
       9: [3, 7, 9, 10, 10], 15: [11, 6, 8, 8, 9], 10: [14, 15, 15, 15, 14], 2: [15, 14, 14, 13, 12],
       6: [9, 9, 7, 7, 7], 1: [6, 5, 6, 6, 8], 11: [5, 11, 12, 12, 13], 14: [13, 12, 11, 11, 11],
       13: [1, 2, 2, 2, 4], 7: [10, 13, 13, 14, 15], 3: [16, 16, 16, 16, 16]}
S1F = {8: 13.6, 4: 14.1, 16: 13.7, 12: 13.9, 5: 13.9, 9: 13.7, 15: 14.0, 10: 15.1, 2: 15.2, 6: 14.0, 1: 13.9,
       11: 13.8, 14: 14.7, 13: 13.5, 7: 14.0, 3: 15.7}
L600 = {8: 37.8, 4: 36.9, 16: 37.6, 12: 38.2, 5: 38.8, 9: 37.8, 15: 38.2, 10: 36.9, 2: 37.2, 6: 38.4, 1: 38.6,
        11: 38.1, 14: 38.2, 13: 41.0, 7: 38.8, 3: 43.4}
L200 = {8: 13.3, 4: 12.5, 16: 13.2, 12: 13.4, 5: 14.0, 9: 12.8, 15: 13.1, 10: 12.6, 2: 12.9, 6: 13.4, 1: 13.3,
        11: 13.2, 14: 13.4, 13: 15.3, 7: 13.6, 3: 17.4}
# Recent form is illustrative except #4 (8-3-1-3-4 from the live mobile card).
FORM = {8: [3, 2, 5, 1, 4], 4: [8, 3, 1, 3, 4], 16: [6, 7, 4, 9, 5], 12: [2, 4, 3], 5: [1, 5, 2, 6, 3],
        9: [7, 3, 8, 2, 6], 15: [4, 6, 5], 10: [2, 1, 3, 4, 2], 2: [9, 8, 6, 5, 7], 6: [1, 2, 1, 3, 2],
        1: [5, 3, 7], 11: [6, 9, 4], 14: [4, 8, 10, 6, 9], 13: [3, 5, 2, 7, 4], 7: [10, 7, 9, 8, 11],
        3: [11, 12, 9, 10, 8]}
EQUIP = {1: "재갈 · 가면", 2: "눈가면", 3: "눈가면", 4: "눈가면", 5: "재갈 · 가면", 6: "BF · 눈가면 · 재갈",
         7: "가면 · 재갈 · 쿠션편자", 8: "눈가면 · 재갈", 9: "BF · 가면", 10: "눈가면 · 재갈", 11: "재갈 · 눈가면",
         12: "가면 · 재갈", 13: "눈가면", 14: "재갈 · 눈가면 · 쿠션편자", 15: "눈가면", 16: "재갈 · 쿠션편자 · 혀끈"}
# latest 수액처치 date in the week before the race (09.20)
FLUID = {1: "9.17", 4: "9.18", 5: "9.18", 6: "9.18", 7: "9.17", 9: "9.18", 11: "9.18", 12: "9.18", 13: "9.18",
         15: "9.13", 16: "9.18"}
# only findings that change a read of the horse; routine 피로회복 수액 stays in the count
MED_ALERT = {8: "파행 9.06", 5: "호흡기 9.10"}
MED_COUNT = {1: 2, 2: 2, 3: 1, 4: 1, 5: 2, 6: 2, 7: 2, 8: 2, 9: 2, 10: 2, 11: 2, 12: 2, 13: 2, 14: 2, 15: 2, 16: 2}
MARKS = {8: "◎", 4: "○", 12: "▲", 10: "△"}
MEMOS = {8: "3C부터 선행 가능, 1,400m 입상 2회", 6: "+17kg 체중 증가 확인 필요"}

SEOUL = [(1, "10:35", "1,200m", "혼4등급", 11, "더로드", "1:12.8"), (2, "11:00", "1,400m", "국6등급", 11, "이클립스골든", "1:28.3"),
         (3, "11:25", "1,300m", "국6등급", 8, "빅토리시크릿", "1:23.3"), (4, "12:05", "1,700m", "국6등급", 10, "파워풀아크틱", "1:52.8"),
         (5, "13:10", "1,800m", "국5등급", 11, "나로마스타", "1:59.6"), (6, "14:00", "1,200m", "국5등급", 11, "태평에스지", "1:14.4"),
         (7, "14:50", "1,300m", "국5등급", 11, "케렌시아", "1:21.4"), (8, "15:40", "1,400m", "도지사배(G3)", 16, "판타스틱밸류", "1:24.1"),
         (9, "16:55", "1,800m", "국3등급", 11, "제이디강자", "1:54.9"), (10, "17:25", "2,000m", "2등급", 9, "트라움킹", "2:11.1"),
         (11, "17:55", "1,200m", "혼4등급", 11, "팬텀프린스", "1:13.7")]
YEONGCHEON = [(1, "12:45", "1,400m", "국4등급", 11, "윈드미르", "1:25.4"), (2, "13:35", "1,600m", "국4등급", 10, "오아시스환희", "1:39.2"),
              (3, "14:25", "1,200m", "혼4등급", 11, "대로의빛", "1:12.7"), (4, "15:15", "1,400m", "국3등급", 11, "새내헌터", "1:24.2"),
              (5, "16:05", "1,200m", "혼3등급", 11, "희망라니", "1:12.8"), (6, "16:30", "1,200m", "2등급", 11, "용비패왕", "1:11.6")]
NOW = "15:08"


def silk(n: int, size: str = "") -> str:
    return f'<span class="silk silk-{n} {size}">{n}</span>'


def head(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://code.iconify.design/iconify-icon/1.0.7/iconify-icon.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600;700&display=swap">
<script>
tailwind.config = {{ theme: {{ extend: {{
  colors: {{
    bg: '#f2f5f2', s1: '#ffffff', s2: '#fbfdfb', s3: '#f0f5f1',
    line: 'rgb(21 45 33 / 11%)', linestrong: 'rgb(21 45 33 / 22%)',
    ink: '#17241d', inkstrong: '#060c09', muted: '#5d7066', faint: '#93a49a',
    accent: '#059669', accentstrong: '#047857', accentdeep: '#065f46', accentsoft: 'rgb(5 150 105 / 9%)',
    lime: '#65a30d', gold: '#b45309', silver: '#64748b', bronze: '#9a5b2d', warn: '#dc2626', info: '#1570c7',
  }},
  fontFamily: {{ sans: ['"Pretendard Variable"', 'Pretendard', '"Noto Sans KR"', 'sans-serif'], mono: ['"JetBrains Mono"', 'monospace'] }},
  boxShadow: {{ soft: '0 6px 18px rgb(20 40 30 / 7%)', raised: '0 16px 40px rgb(20 40 30 / 10%)' }},
}} }} }};
</script>
<style>
  body {{ margin: 0; font-family: "Pretendard Variable", Pretendard, "Noto Sans KR", sans-serif; background: #f2f5f2; color: #17241d; font-size: 14px; }}
  .app-bg {{ background: radial-gradient(800px 420px at 12% -8%, rgb(5 150 105 / 6%), transparent 66%), radial-gradient(720px 400px at 88% -4%, rgb(132 204 22 / 5%), transparent 62%), #f2f5f2; }}
  .mono {{ font-family: "JetBrains Mono", monospace; font-variant-numeric: tabular-nums; }}
  .glass {{ background: rgb(255 255 255 / 82%); backdrop-filter: blur(14px) saturate(150%); }}
  .pill-active {{ background: linear-gradient(135deg, #059669, #65a30d); color: #fff; box-shadow: 0 6px 16px rgb(5 150 105 / 22%); }}
  .btn-primary {{ background: linear-gradient(135deg, #059669, #65a30d); color: #fff; box-shadow: 0 8px 20px rgb(5 150 105 / 24%); }}
  .eyebrow {{ font-family: "JetBrains Mono", monospace; font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: #059669; font-weight: 600; }}
  .silk {{ display: inline-grid; place-items: center; width: 28px; height: 28px; flex: 0 0 auto; border-radius: 9px; font: 700 12px/1 "JetBrains Mono", monospace; box-shadow: 0 2px 6px rgb(0 0 0 / 14%); }}
  .silk.sm {{ width: 22px; height: 22px; border-radius: 7px; font-size: 11px; }}
  .silk-1 {{ background: #f4f4f4; color: #222; border: 1px solid #c5c5c5; }}
  .silk-2 {{ background: #f4c430; color: #1a1a1a; border: 1px solid #d5a600; }}
  .silk-3 {{ background: #c0392b; color: #fff; }}
  .silk-4 {{ background: #1a1a1a; color: #fff; border: 1px solid #4b5563; }}
  .silk-5 {{ background: #1f5fbf; color: #fff; }}
  .silk-6 {{ background: #1f7a3a; color: #fff; }}
  .silk-7 {{ background: #7c2d26; color: #fff; }}
  .silk-8 {{ background: #ef7eb2; color: #30101f; }}
  .silk-9 {{ background: #6d28d9; color: #fff; }}
  .silk-10 {{ background: #38bdf8; color: #0b3b4d; }}
  .silk-11 {{ color: #17212b; background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #f4f4f4 6px 10px); border: 1px solid #8fcde8; }}
  .silk-12 {{ color: #1a1a1a; background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #f4c430 6px 10px); border: 1px solid #caac36; }}
  .silk-13 {{ color: #fff; background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #c0392b 6px 10px); text-shadow: 0 1px 2px rgb(0 0 0 / 65%); }}
  .silk-14 {{ color: #fff; background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #1a1a1a 6px 10px); text-shadow: 0 1px 2px rgb(0 0 0 / 65%); }}
  .silk-15 {{ background: #be123c; color: #fff; }}
  .silk-16 {{ background: #0f766e; color: #fff; }}
  .grid-table {{ border-collapse: separate; border-spacing: 0; width: 100%; font-size: 13px; }}
  .grid-table thead th {{ position: sticky; top: 0; background: #f0f5f1; color: #5d7066; font-size: 11.5px; font-weight: 700; text-align: left; padding: 10px 10px; border-bottom: 1px solid rgb(21 45 33 / 16%); white-space: nowrap; }}
  .grid-table thead th.num {{ text-align: right; }}
  .grid-table tbody td {{ padding: 0 10px; height: 46px; border-bottom: 1px solid rgb(21 45 33 / 8%); white-space: nowrap; }}
  .grid-table tbody tr:hover td {{ background: rgb(5 150 105 / 5%); }}
  .grid-table tbody tr.is-selected td {{ background: rgb(5 150 105 / 8%); }}
  .grid-table td.num {{ text-align: right; font-family: "JetBrains Mono", monospace; font-variant-numeric: tabular-nums; }}
  .grid-table tr.p1 td:first-child {{ box-shadow: inset 3px 0 0 #b45309; }}
  .grid-table tr.p2 td:first-child {{ box-shadow: inset 3px 0 0 #64748b; }}
  .grid-table tr.p3 td:first-child {{ box-shadow: inset 3px 0 0 #9a5b2d; }}
  .grid-table tr.p1 td {{ background: rgb(217 164 34 / 7%); }}
  .grid-table tr.p2 td {{ background: rgb(100 116 139 / 6%); }}
  .grid-table tr.p3 td {{ background: rgb(154 91 45 / 6%); }}
  .form-chip {{ display: inline-grid; place-items: center; min-width: 22px; height: 22px; padding: 0 5px; border-radius: 7px; font: 600 11.5px/1 "JetBrains Mono", monospace; background: #f0f5f1; color: #5d7066; }}
  .form-chip.f1 {{ background: rgb(217 164 34 / 20%); color: #8a4a06; }}
  .form-chip.f2 {{ background: rgb(100 116 139 / 16%); color: #3f4c5e; }}
  .form-chip.f3 {{ background: rgb(154 91 45 / 15%); color: #7a4420; }}
  .heat-0 {{ background: rgb(5 150 105 / 26%); color: #065f46; font-weight: 700; }}
  .heat-1 {{ background: rgb(5 150 105 / 14%); color: #047857; font-weight: 600; }}
  .heat-2 {{ background: rgb(5 150 105 / 6%); }}
  .heat-slow {{ color: #93a49a; }}
  .heat-cell {{ display: inline-block; min-width: 50px; padding: 4px 7px; border-radius: 7px; text-align: right; }}
  .mark {{ display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 999px; font-size: 14px; font-weight: 800; border: 1px dashed rgb(21 45 33 / 18%); color: #c2cdc6; }}
  .mark.on {{ border: 0; color: #fff; }}
  .mark.m1 {{ background: #168a42; }} .mark.m2 {{ background: #756900; }} .mark.m3 {{ background: #9a6500; }} .mark.m4 {{ background: #58635f; }}
  .tag {{ display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 8px; border-radius: 999px; font-size: 11.5px; font-weight: 600; }}
  .rail-item {{ transition: background .18s ease, transform .18s ease; }}
  .rail-item:hover {{ background: rgb(5 150 105 / 5%); }}
  .fade-up {{ animation: fadeUp .32s ease both; }}
  @keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
</style>
</head>
"""


def header() -> str:
    nav = [("경주", True), ("경주 분석", False), ("내 분석", False), ("예측 원장", False), ("데이터", False)]
    new_badge = '<span class="ml-1 align-top text-[10px] text-accent">NEW</span>'
    items = "".join(
        f'<a href="#nav-{i}" {aid("nav")} class="px-4 py-2 rounded-full text-[13.5px] font-bold tracking-[-0.02em] '
        + ("pill-active" if active else "text-muted hover:text-inkstrong hover:bg-s3")
        + f'">{label}{new_badge if label == "내 분석" else ""}</a>'
        for i, (label, active) in enumerate(nav)
    )
    return f"""
<header class="glass sticky top-0 z-30 border-b border-line">
  <div class="mx-auto flex h-[64px] w-[calc(100%-48px)] max-w-[1520px] items-center gap-6">
    <a href="#home" {aid("brand")} class="flex items-center gap-2.5 shrink-0" aria-label="마필로그 홈">
      <img src="{SYMBOL}" alt="" class="h-[26px] w-auto">
      <img src="{WORDMARK}" alt="Mapilog" class="h-[20px] w-auto">
    </a>
    <nav class="flex items-center gap-1">{items}</nav>
    <div class="ml-auto flex items-center gap-2.5">
      <label class="flex h-[38px] w-[300px] items-center gap-2 rounded-full border border-line bg-s2 px-4 text-muted">
        <iconify-icon icon="lucide:search" width="16"></iconify-icon>
        <input class="w-full bg-transparent text-[13px] outline-none placeholder:text-faint" placeholder="말 · 기수 · 조교사 · 마주 검색">
        <span class="mono rounded-md border border-line px-1.5 text-[10.5px] text-faint">/</span>
      </label>
      <button class="grid h-[38px] w-[38px] place-items-center rounded-full border border-line bg-s2 text-muted" aria-label="다크 모드로 전환">
        <iconify-icon icon="lucide:moon" width="17"></iconify-icon>
      </button>
    </div>
  </div>
</header>"""


def day_bar(state: str) -> str:
    meets = [("전체", "17", True), ("서울", "11", False), ("제주", "0", False), ("부산경남", "0", False), ("영천", "6", False)]
    seg = "".join(
        f'<button class="flex items-center gap-1.5 rounded-[10px] px-3.5 py-1.5 text-[13px] font-bold '
        + ("bg-s1 text-inkstrong shadow-[0_1px_4px_rgb(20_40_30_/_10%)]" if on else "text-muted hover:text-ink")
        + ("" if count != "0" else " opacity-45")
        + f'">{name}<span class="mono text-[11px] {"text-accent" if on else "text-faint"}">{count}</span></button>'
        for name, count, on in meets
    )
    live = (
        f'<span class="tag bg-[rgb(21_112_199_/_10%)] text-info"><span class="h-1.5 w-1.5 rounded-full bg-info"></span>진행 중 · {NOW} 기준</span>'
        if state == "pre" else
        '<span class="tag bg-accentsoft text-accentstrong"><iconify-icon icon="lucide:check" width="13"></iconify-icon>전 경주 결과 확정</span>'
    )
    return f"""
<section class="flex items-end justify-between gap-6 pt-7 pb-5">
  <div>
    <p class="eyebrow">RACE CALENDAR</p>
    <h1 class="mt-1.5 text-[30px] font-extrabold tracking-[-0.03em] text-inkstrong">경주 일정과 결과</h1>
    <p class="mt-1.5 flex items-center gap-2 text-[13px] text-muted">
      <span>공식 경주 <b class="mono text-ink">17</b></span><span class="h-1 w-1 rounded-full bg-linestrong"></span>
      <span>출전 <b class="mono text-ink">185</b>두</span><span class="h-1 w-1 rounded-full bg-linestrong"></span>
      <span>주행심사 없음</span>{live}
    </p>
  </div>
  <div class="flex items-center gap-3">
    <div class="flex items-center gap-1 rounded-[14px] border border-line bg-s1 p-1 shadow-soft">
      <button class="grid h-9 w-9 place-items-center rounded-[10px] text-muted hover:bg-s3" aria-label="이전 경주일"><iconify-icon icon="lucide:chevron-left" width="18"></iconify-icon></button>
      <button class="flex items-center gap-2 rounded-[10px] px-3 py-1.5 hover:bg-s3">
        <iconify-icon icon="lucide:calendar-days" width="17" class="text-accent"></iconify-icon>
        <span class="mono text-[14px] font-bold text-inkstrong">2026.09.20</span><span class="text-[12px] font-semibold text-muted">일</span>
      </button>
      <button class="grid h-9 w-9 place-items-center rounded-[10px] text-faint" aria-label="다음 경주일" disabled><iconify-icon icon="lucide:chevron-right" width="18"></iconify-icon></button>
    </div>
    <div class="flex items-center gap-0.5 rounded-[14px] border border-line bg-s3 p-1">{seg}</div>
  </div>
</section>"""


def rail(state: str) -> str:
    def rows(course: str, races):
        out = []
        for num, t, dist, grade, cnt, winner, wtime in races:
            selected = course == "서울" and num == 8
            done = state == "post" or t < NOW
            if done:
                status = f'<span class="text-[11px] font-semibold text-faint">종료</span>'
                sub = f'<span class="truncate text-[12px] text-muted">🏆 {winner}</span><span class="mono text-[11px] text-faint">{wtime}</span>'
            else:
                mins = (int(t[:2]) * 60 + int(t[3:])) - (int(NOW[:2]) * 60 + int(NOW[3:]))
                status = f'<span class="mono rounded-full bg-[rgb(21_112_199_/_10%)] px-2 py-0.5 text-[10.5px] font-bold text-info">{mins}분 후</span>' if mins <= 60 else '<span class="text-[11px] font-semibold text-info">예정</span>'
                sub = f'<span class="text-[12px] text-muted">{grade}</span><span class="mono text-[11px] text-faint">{cnt}두</span>'
            cls = "bg-accentsoft shadow-[inset_3px_0_0_#059669]" if selected else ""
            out.append(f"""
      <a href="#race-{course}-{num}" {aid("race")} class="rail-item flex items-center gap-3 rounded-[12px] px-3 py-2.5 {cls}">
        <span class="mono w-[34px] text-[15px] font-bold {'text-accentstrong' if selected else 'text-inkstrong'}">{num}R</span>
        <span class="min-w-0 flex-1">
          <span class="flex items-center gap-2"><span class="mono text-[12.5px] font-semibold text-ink">{t}</span><span class="mono text-[11.5px] text-muted">{dist}</span><span class="ml-auto">{status}</span></span>
          <span class="mt-0.5 flex items-center justify-between gap-2">{sub}</span>
        </span>
      </a>""")
        return "".join(out)

    return f"""
<aside class="w-[300px] shrink-0">
  <div class="sticky top-[84px] overflow-hidden rounded-[18px] border border-line bg-s1 shadow-soft">
    <div class="flex items-center justify-between border-b border-line px-4 py-3.5">
      <div><p class="eyebrow">DAILY CARD</p><h2 class="mt-0.5 text-[16px] font-extrabold tracking-[-0.02em]">오늘의 경주</h2></div>
      <button class="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[12px] font-semibold text-muted"><iconify-icon icon="lucide:list-filter" width="13"></iconify-icon>예정만</button>
    </div>
    <div class="max-h-[1080px] overflow-y-auto p-2">
      <p class="px-3 pb-1 pt-2 text-[11.5px] font-bold text-accentstrong">서울 · 11경주</p>{rows("서울", SEOUL)}
      <p class="mt-2 border-t border-line px-3 pb-1 pt-3 text-[11.5px] font-bold text-accentstrong">영천 · 6경주</p>{rows("영천", YEONGCHEON)}
    </div>
  </div>
</aside>"""


def race_head(state: str) -> str:
    status = (
        '<span class="tag bg-[rgb(21_112_199_/_10%)] text-info"><span class="h-1.5 w-1.5 animate-pulse rounded-full bg-info"></span>발주까지 32분</span>'
        if state == "pre" else
        '<span class="tag bg-accentsoft text-accentstrong"><iconify-icon icon="lucide:flag" width="12"></iconify-icon>결과 확정</span>'
    )
    tabs = [("출마표", "pre"), ("결과", "post"), ("구간기록", "post"), ("장구 · 진료", "any"), ("배당 · 심판", "post")]
    tab_html = ""
    for label, when in tabs:
        active = (state == "pre" and label == "출마표") or (state == "post" and label == "결과")
        disabled = state == "pre" and when == "post"
        cls = ("bg-s1 text-inkstrong shadow-[0_1px_4px_rgb(20_40_30_/_10%)]" if active
               else "text-faint cursor-not-allowed" if disabled else "text-muted hover:text-ink")
        suffix = '<span class="ml-1 text-[10.5px] font-medium">경주 후</span>' if disabled else ""
        tab_html += f'<button class="rounded-[10px] px-4 py-2 text-[13px] font-bold {cls}">{label}{suffix}</button>'
    return f"""
<div class="fade-up rounded-[18px] border border-line bg-s1 p-5 shadow-soft">
  <div class="flex items-start gap-5">
    <div class="grid h-[76px] w-[76px] shrink-0 place-items-center rounded-[16px] bg-[linear-gradient(135deg,#06392a_0%,#0b5a3c_60%,#0e6a47_100%)] text-white shadow-[0_10px_24px_rgb(6_57_42_/_25%)]">
      <span class="text-center leading-none"><span class="block text-[11px] font-semibold text-[#a7f3d0]">서울</span><span class="mono mt-1 block text-[28px] font-bold">8R</span></span>
    </div>
    <div class="min-w-0 flex-1">
      <p class="mono flex items-center gap-2 text-[12px] font-semibold text-muted">2026.09.20 · 15:40 출발 {status}</p>
      <h2 class="mt-1.5 text-[24px] font-extrabold tracking-[-0.03em] text-inkstrong">제주특별자치도지사배 <span class="ml-1 rounded-[8px] bg-[rgb(217_164_34_/_14%)] px-2 py-0.5 align-middle text-[13px] font-bold text-gold">G3</span></h2>
      <div class="mt-2.5 flex flex-wrap items-center gap-1.5 text-[12px] font-semibold text-muted">
        <span class="tag bg-s3"><iconify-icon icon="lucide:ruler" width="12"></iconify-icon><span class="mono">1,400m</span></span>
        <span class="tag bg-s3">국OPEN · 암말</span>
        <span class="tag bg-s3">16두 출전</span>
        <span class="tag bg-s3"><iconify-icon icon="lucide:sun" width="12"></iconify-icon>맑음 · 건조 · 함수율 <span class="mono">2%</span></span>
      </div>
    </div>
    <div class="flex shrink-0 flex-col items-end gap-2">
      <div class="flex items-center gap-1.5">
        <a href="#prev-race" {aid("act")} class="grid h-9 w-9 place-items-center rounded-full border border-line text-muted hover:bg-s3" aria-label="이전 경주"><iconify-icon icon="lucide:chevron-left" width="17"></iconify-icon></a>
        <a href="#next-race" {aid("act")} class="grid h-9 w-9 place-items-center rounded-full border border-line text-muted hover:bg-s3" aria-label="다음 경주"><iconify-icon icon="lucide:chevron-right" width="17"></iconify-icon></a>
      </div>
      <div class="flex items-center gap-2">
        <a href="#video" {aid("act")} class="flex items-center gap-1.5 rounded-full border border-line bg-s2 px-3.5 py-2 text-[13px] font-bold text-ink hover:border-linestrong"><iconify-icon icon="lucide:play-circle" width="16"></iconify-icon>{'지난 경주 영상' if state == 'pre' else '경주 영상'}</a>
        <a href="#analysis" {aid("act")} class="btn-primary flex items-center gap-1.5 rounded-full px-4 py-2 text-[13px] font-bold"><iconify-icon icon="lucide:table-2" width="16"></iconify-icon>분석 시트로 열기</a>
      </div>
    </div>
  </div>
  <div class="mt-5 flex items-center justify-between">
    <div class="flex items-center gap-0.5 rounded-[12px] border border-line bg-s3 p-1">{tab_html}</div>
    <div class="flex items-center gap-2 text-[12.5px] font-semibold text-muted">
      <button class="flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 hover:bg-s3"><iconify-icon icon="lucide:columns-3" width="14"></iconify-icon>열 편집</button>
      <button class="flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 hover:bg-s3"><iconify-icon icon="lucide:file-spreadsheet" width="14"></iconify-icon>엑셀로 내보내기</button>
      <button class="flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 hover:bg-s3"><iconify-icon icon="lucide:printer" width="14"></iconify-icon>인쇄용</button>
    </div>
  </div>
</div>"""


def card(title: str, eyebrow: str, body: str, extra: str = "") -> str:
    return f"""
  <div class="fade-up rounded-[18px] border border-line bg-s1 p-4 shadow-soft {extra}">
    <div class="flex items-center justify-between"><p class="eyebrow">{eyebrow}</p></div>
    <h3 class="mt-1 text-[14.5px] font-extrabold tracking-[-0.02em] text-inkstrong">{title}</h3>
    <div class="mt-3">{body}</div>
  </div>"""


def mini_row(n: int, name: str, value: str, tone: str = "text-ink") -> str:
    return f'<div class="flex items-center gap-2 py-1">{silk(n, "sm")}<span class="flex-1 truncate text-[13px] font-semibold">{name}</span><span class="mono text-[12.5px] font-bold {tone}">{value}</span></div>'


def pre_insights() -> str:
    name = {e[0]: e[1] for e in ENTRIES}
    pop = "".join(mini_row(n, name[n], f"{o}배", "text-accentstrong" if i == 0 else "text-ink")
                  for i, (n, o) in enumerate([(6, 2.5), (10, 4.9), (12, 6.4), (8, 6.5)]))
    rating = "".join(mini_row(n, name[n], str(r)) for n, r in [(5, 109), (4, 108), (6, 106), (10, 95)])
    cond = f"""
      <div class="space-y-2 text-[12.5px]">
        <div class="flex items-center gap-2"><span class="w-[62px] shrink-0 font-semibold text-muted">체중 ±10kg</span><span class="flex flex-wrap gap-1">{''.join(silk(n, 'sm') for n in [4, 6, 3, 11, 13, 10, 5, 16])}</span></div>
        <div class="flex items-center gap-2"><span class="w-[62px] shrink-0 font-semibold text-muted">눈가리개</span><span class="flex gap-1">{silk(6, 'sm')}{silk(9, 'sm')}</span><span class="text-faint">BF 착용</span></div>
        <div class="flex items-center gap-2"><span class="w-[62px] shrink-0 font-semibold text-muted">진료 주의</span><span class="flex gap-1">{silk(8, 'sm')}{silk(5, 'sm')}</span><span class="text-faint">파행 · 호흡기</span></div>
        <p class="rounded-[10px] bg-[rgb(217_164_34_/_10%)] px-2.5 py-1.5 text-[12px] text-[#8a4a06]"><b>4 라온포레스트</b> +27kg 급증, 직전 대비 확인 필요</p>
      </div>"""
    marks = "".join(
        f'<div class="flex items-center gap-2 py-1"><span class="mark on m{i + 1} !h-[22px] !w-[22px] !text-[12px]">{m}</span>{silk(n, "sm")}<span class="flex-1 truncate text-[13px] font-semibold">{name[n]}</span></div>'
        for i, (n, m) in enumerate(MARKS.items())
    )
    marks += f'<a href="#my-analysis" {aid("my")} class="mt-2 flex items-center justify-center gap-1 rounded-[10px] bg-accentsoft py-1.5 text-[12.5px] font-bold text-accentstrong">내 분석에 저장됨 · 비교하기 <iconify-icon icon="lucide:arrow-right" width="14"></iconify-icon></a>'
    return f"""
<div class="mt-4 grid grid-cols-4 gap-3">
{card("인기 순위", "MARKET · 단승", pop + '<p class="mt-2 text-[11.5px] text-faint">15:08 기준 · 1분마다 갱신</p>')}
{card("레이팅 상위", "RATING", rating)}
{card("컨디션 체크", "CONDITION", cond)}
{card("내 표시", "MY PICKS", marks)}
</div>"""


def form_chips(n: int) -> str:
    chips = []
    for p in FORM[n]:
        cls = f"f{p}" if p <= 3 else ""
        chips.append(f'<span class="form-chip {cls}">{p}</span>')
    pad = "".join('<span class="form-chip opacity-40">·</span>' for _ in range(5 - len(FORM[n])))
    return f'<span class="flex items-center gap-1">{"".join(chips)}{pad}</span>'


def delta(d: int) -> str:
    if d == 0:
        return '<span class="text-faint">0</span>'
    big = abs(d) >= 10
    color = "text-warn" if d > 0 else "text-info"
    weight = "font-bold" if big else ""
    bg = ("bg-[rgb(220_38_38_/_9%)]" if d > 0 else "bg-[rgb(21_112_199_/_9%)]") if big else ""
    return f'<span class="rounded-[6px] px-1.5 py-0.5 {color} {weight} {bg}">{d:+d}</span>'


def equip(n: int) -> str:
    parts = EQUIP[n].split(" · ")
    out = []
    for p in parts:
        if p == "BF":
            out.append('<span class="tag !h-[20px] bg-[rgb(217_164_34_/_16%)] !px-1.5 text-[11px] text-gold">BF</span>')
        else:
            out.append(f'<span class="text-[12px] text-muted">{p}</span>')
    return '<span class="flex items-center gap-1.5">' + '<span class="text-faint">·</span>'.join(out) + "</span>"


def pre_table() -> str:
    rows = []
    for e in sorted(ENTRIES, key=lambda x: x[0]):
        n, name, meta, jockey, trainer, owner, carried, body, d, rating, *_rest = e
        win = e[13]
        mark = MARKS.get(n)
        mark_idx = list(MARKS).index(n) + 1 if mark else 0
        mark_html = f'<span class="mark on m{mark_idx}">{mark}</span>' if mark else '<span class="mark">+</span>'
        alert = MED_ALERT.get(n)
        med = (f'<span class="tag !h-[20px] bg-[rgb(220_38_38_/_9%)] !px-2 text-[11px] text-warn">{alert}</span>'
               if alert else f'<span class="text-[12px] text-faint">30일 {MED_COUNT[n]}건</span>')
        memo = MEMOS.get(n)
        memo_html = (f'<span class="flex max-w-[150px] items-center gap-1 truncate text-[12px] text-accentstrong"><iconify-icon icon="lucide:sticky-note" width="13"></iconify-icon>{memo}</span>'
                     if memo else '<span class="text-faint"><iconify-icon icon="lucide:pencil-line" width="14"></iconify-icon></span>')
        selected = "is-selected" if n == 8 else ""
        rows.append(f"""
        <tr class="{selected}">
          <td class="!pl-4">{mark_html}</td>
          <td><div class="flex items-center gap-2.5">{silk(n)}<span><a href="#horse-{n}" {aid("h")} class="block text-[13.5px] font-bold text-inkstrong hover:text-accentstrong">{name}</a><span class="text-[11.5px] text-faint">{meta}</span></span></div></td>
          <td>{form_chips(n)}</td>
          <td class="num font-semibold">{rating}</td>
          <td class="num">{carried}</td>
          <td class="num"><span class="text-ink">{body}</span> <span class="text-[11.5px]">{delta(d)}</span></td>
          <td><a href="#jockey-{n}" {aid("j")} class="font-semibold text-ink hover:text-accentstrong">{jockey}</a></td>
          <td class="text-muted">{trainer}</td>
          <td>{equip(n)}</td>
          <td>{med}</td>
          <td class="num font-bold {'text-accentstrong' if win < 5 else 'text-ink'}">{win}</td>
          <td class="!pr-4">{memo_html}</td>
        </tr>""")
    return f"""
<div class="fade-up mt-4 overflow-hidden rounded-[18px] border border-line bg-s1 shadow-soft">
  <div class="flex items-center justify-between border-b border-line px-4 py-3">
    <div class="flex items-center gap-3">
      <h3 class="text-[15px] font-extrabold tracking-[-0.02em]">출마표</h3>
      <span class="mono text-[12px] text-faint">16두 · 마번순</span>
      <div class="flex items-center gap-0.5 rounded-[10px] bg-s3 p-0.5 text-[12px] font-bold">
        <button class="rounded-[8px] bg-s1 px-2.5 py-1 text-inkstrong shadow-[0_1px_3px_rgb(20_40_30_/_10%)]">기본</button>
        <button class="rounded-[8px] px-2.5 py-1 text-muted">컨디션</button>
        <button class="rounded-[8px] px-2.5 py-1 text-muted">관계자</button>
        <button class="rounded-[8px] px-2.5 py-1 text-muted">+ 내 보기</button>
      </div>
    </div>
    <p class="flex items-center gap-3 text-[11.5px] text-muted">
      <span class="flex items-center gap-1"><span class="form-chip f1 !h-4 !min-w-4 !text-[9px]">1</span>최근 성적 입상</span>
      <span class="flex items-center gap-1"><span class="text-warn">+</span>/<span class="text-info">−</span> 직전 대비 마체중</span>
      <span class="flex items-center gap-1"><span class="mark !h-4 !w-4 !text-[10px]">+</span>눌러서 ◎○▲△ 표시</span>
    </p>
  </div>
  <table class="grid-table">
    <thead><tr>
      <th class="!pl-4">표시</th><th>마번 · 마명</th><th>최근 5전</th><th class="num">레이팅</th><th class="num">부담</th>
      <th class="num">마체중 · 증감</th><th>기수</th><th>조교사</th><th>장구</th><th>진료</th><th class="num">단승</th><th class="!pr-4">메모</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>"""


def heat(values: dict[int, float], n: int) -> str:
    """Lower is faster for every section time, so rank ascending."""
    ranked = sorted(values.values())
    v = values[n]
    rank = ranked.index(v)
    cls = "heat-0" if rank < 2 else "heat-1" if rank < 4 else "heat-2" if rank < 8 else "heat-slow" if rank >= 13 else ""
    return f'<span class="heat-cell mono {cls}">{v:.1f}</span>'


def trail(n: int, finish: int) -> str:
    pts = POS[n] + [finish]
    w, h = 76, 22
    xs = [2 + i * (w - 4) / 5 for i in range(6)]
    ys = [2 + (p - 1) * (h - 4) / 15 for p in pts]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    gained = pts[0] - finish
    color = "#059669" if gained > 2 else "#dc2626" if gained < -2 else "#93a49a"
    return (f'<span class="flex items-center gap-2"><svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2.4" fill="{color}"/></svg>'
            f'<span class="mono text-[11.5px] text-muted">{"-".join(str(p) for p in POS[n])}</span></span>')


def post_table() -> str:
    rows = []
    for e in ENTRIES:
        n, name, meta, jockey, trainer, owner, carried, body, d, rating, fin, t, margin, win, place = e
        pcls = f"p{fin}" if fin <= 3 else ""
        medal = {1: ("bg-[linear-gradient(135deg,#fde68a,#d9a422)] text-[#5b3304]", "1"), 2: ("bg-[linear-gradient(135deg,#e2e8f0,#94a3b8)] text-[#1e293b]", "2"), 3: ("bg-[linear-gradient(135deg,#f3c9a4,#b87333)] text-[#3b1d08]", "3")}
        if fin in medal:
            fin_html = f'<span class="mono grid h-[28px] w-[34px] place-items-center rounded-[9px] text-[13px] font-bold shadow-[0_2px_6px_rgb(0_0_0_/_12%)] {medal[fin][0]}">{fin}위</span>'
        else:
            fin_html = f'<span class="mono pl-2 text-[13px] font-semibold text-muted">{fin}위</span>'
        mark = MARKS.get(n)
        if mark:
            idx = list(MARKS).index(n) + 1
            hit = fin <= 3
            mark_html = f'<span class="flex items-center gap-1"><span class="mark on m{idx} !h-[22px] !w-[22px] !text-[12px]">{mark}</span>' + ('<iconify-icon icon="lucide:check" width="14" class="text-accent"></iconify-icon>' if hit else "") + "</span>"
        else:
            mark_html = '<span class="text-faint">—</span>'
        rows.append(f"""
        <tr class="{pcls}">
          <td class="!pl-4">{fin_html}</td>
          <td><div class="flex items-center gap-2.5">{silk(n)}<span><a href="#horse-{n}" {aid("h")} class="block text-[13.5px] font-bold text-inkstrong hover:text-accentstrong">{name}</a><span class="text-[11.5px] text-faint">{jockey} · {carried}kg</span></span></div></td>
          <td class="num font-bold text-inkstrong">{t}</td>
          <td class="num text-muted">{margin}</td>
          <td>{trail(n, fin)}</td>
          <td class="num">{heat(S1F, n)}</td>
          <td class="num">{heat(L600, n)}</td>
          <td class="num">{heat(L200, n)}</td>
          <td class="num"><span class="text-ink">{body}</span> <span class="text-[11.5px]">{delta(d)}</span></td>
          <td class="num font-semibold">{win}</td>
          <td class="num text-muted">{place}</td>
          <td class="!pr-4">{mark_html}</td>
        </tr>""")
    return f"""
<div class="fade-up mt-4 overflow-hidden rounded-[18px] border border-line bg-s1 shadow-soft">
  <div class="flex items-center justify-between border-b border-line px-4 py-3">
    <div class="flex items-center gap-3">
      <h3 class="text-[15px] font-extrabold tracking-[-0.02em]">결과 · 기록표</h3>
      <span class="mono text-[12px] text-faint">16두 · 착순</span>
      <div class="flex items-center gap-0.5 rounded-[10px] bg-s3 p-0.5 text-[12px] font-bold">
        <button class="rounded-[8px] bg-s1 px-2.5 py-1 text-inkstrong shadow-[0_1px_3px_rgb(20_40_30_/_10%)]">착순순</button>
        <button class="rounded-[8px] px-2.5 py-1 text-muted">마번순</button>
        <button class="rounded-[8px] px-2.5 py-1 text-muted">막판 600m순</button>
      </div>
    </div>
    <p class="flex items-center gap-3 text-[11.5px] text-muted">
      <span class="flex items-center gap-1.5"><span class="heat-cell heat-0 !min-w-[26px] !px-1 !py-0 text-[10px]">빠름</span><span class="heat-cell heat-2 !min-w-[26px] !px-1 !py-0 text-[10px]">보통</span>구간 기록 색</span>
      <span class="flex items-center gap-1"><svg width="22" height="10"><polyline points="1,8 11,5 21,2" fill="none" stroke="#059669" stroke-width="1.8"/></svg>통과순위 흐름</span>
    </p>
  </div>
  <table class="grid-table">
    <thead><tr>
      <th class="!pl-4">착순</th><th>마번 · 마명</th><th class="num">기록</th><th class="num">착차</th><th>통과 S1F-3C-G3F-4C-G1F</th>
      <th class="num">초반 200m</th><th class="num">막판 600m</th><th class="num">막판 200m</th><th class="num">마체중 · 증감</th><th class="num">단승</th><th class="num">연승</th><th class="!pr-4">내 표시</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="flex items-center justify-between border-t border-line bg-s2 px-4 py-3 text-[12px] text-muted">
    <span>구간 기록은 빠를수록 진한 초록입니다. 착차 단위는 마신입니다.</span>
    <a href="#race-detail" {aid("act")} class="flex items-center gap-1 font-bold text-accentstrong">구간 누적 · 연속 기록 전체 보기 <iconify-icon icon="lucide:arrow-right" width="14"></iconify-icon></a>
  </div>
</div>"""


def bump_chart() -> str:
    w, h = 300, 132
    stages = ["S1F", "3C", "G3F", "4C", "G1F", "결승"]
    xs = [26 + i * (w - 40) / 5 for i in range(6)]

    def y(p):
        return 10 + (p - 1) * (h - 34) / 15

    series = [(8, "#b45309", 1, ""), (4, "#64748b", 2, ""), (16, "#9a5b2d", 3, ""), (13, "#93a49a", 14, "4 3")]
    out = [f'<svg width="100%" viewBox="0 0 {w} {h}" class="overflow-visible">']
    for x, s in zip(xs, stages):
        out.append(f'<line x1="{x:.1f}" y1="6" x2="{x:.1f}" y2="{h - 22}" stroke="rgb(21 45 33 / 8%)"/>')
        out.append(f'<text x="{x:.1f}" y="{h - 6}" text-anchor="middle" font-size="9.5" font-family="JetBrains Mono" fill="#93a49a">{s}</text>')
    for p in (1, 8, 16):
        out.append(f'<text x="8" y="{y(p) + 3:.1f}" font-size="9" font-family="JetBrains Mono" fill="#93a49a">{p}</text>')
    for n, color, fin, dash in series:
        pts = POS[n] + [fin]
        poly = " ".join(f"{x:.1f},{y(p):.1f}" for x, p in zip(xs, pts))
        out.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="{dash}"/>')
        out.append(f'<circle cx="{xs[-1]:.1f}" cy="{y(fin):.1f}" r="3.6" fill="{color}"/>')
    out.append("</svg>")
    legend = "".join(
        f'<span class="flex items-center gap-1.5">{silk(n, "sm")}<span>{label}</span></span>'
        for n, label in [(8, "선행 유지"), (4, "12위→2착"), (16, "중위 유지"), (13, "선두→14착")]
    )
    return "".join(out) + f'<div class="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11.5px] text-muted">{legend}</div>'


def post_insights() -> str:
    podium = "".join(
        f'<div class="flex items-center gap-2 py-1"><span class="mono w-6 text-[12px] font-bold text-{c}">{p}착</span>{silk(n, "sm")}<span class="flex-1 truncate text-[13px] font-semibold">{nm}</span><span class="mono text-[12px] text-muted">{t}</span></div>'
        for p, n, nm, t, c in [(1, 8, "판타스틱밸류", "1:24.1", "gold"), (2, 4, "라온포레스트", "1:25.5", "silver"), (3, 16, "여수슈퍼스타", "1:25.5", "bronze")]
    )
    podium += """
      <div class="mt-2 grid grid-cols-[72px_1fr] gap-2">
        <div class="rounded-[10px] bg-s3 px-2.5 py-1.5"><p class="text-[11px] font-semibold text-muted">단승 8</p><p class="mono text-[15px] font-bold text-inkstrong">6.5<span class="text-[11px] text-muted">배</span></p></div>
        <div class="rounded-[10px] bg-s3 px-2.5 py-1.5"><p class="text-[11px] font-semibold text-muted">연승 8 · 4 · 16</p><p class="mono whitespace-nowrap text-[13px] font-bold text-inkstrong">2.5 · 2.7 · 15.9</p></div>
      </div>"""
    closers = "".join(
        f'<div class="flex items-center gap-2 py-1">{silk(n, "sm")}<span class="flex-1 truncate text-[13px] font-semibold">{nm}</span><span class="mono rounded-[6px] px-1.5 text-[12px] font-bold heat-0">{v}</span><span class="mono w-9 text-right text-[11.5px] text-muted">{f}착</span></div>'
        for n, nm, v, f in [(4, "라온포레스트", "36.9", 2), (10, "보령라이트퀸", "36.9", 8), (2, "클럽큐", "37.2", 9), (16, "여수슈퍼스타", "37.6", 3)]
    )
    closers += '<p class="mt-2 rounded-[10px] bg-accentsoft px-2.5 py-1.5 text-[12px] text-accentdeep"><b>10 보령라이트퀸</b> 14위 출발 · 막판 최상위권, 다음 경주 주목</p>'
    name = {e[0]: (e[1], e[10]) for e in ENTRIES}
    picks = "".join(
        f'<div class="flex items-center gap-2 py-1"><span class="mark on m{i + 1} !h-[22px] !w-[22px] !text-[12px]">{m}</span>{silk(n, "sm")}<span class="flex-1 truncate text-[13px] font-semibold">{name[n][0]}</span>'
        f'<span class="mono text-[12px] font-bold {"text-accentstrong" if name[n][1] <= 3 else "text-muted"}">{name[n][1]}착</span></div>'
        for i, (n, m) in enumerate(MARKS.items())
    )
    picks += '<p class="mt-2 flex items-center gap-1.5 rounded-[10px] bg-accentsoft px-2.5 py-1.5 text-[12px] font-bold text-accentstrong"><iconify-icon icon="lucide:target" width="14"></iconify-icon>◎ · ○ 1-2착 적중 · 기록 저장됨</p>'
    return f"""
<div class="mt-4 grid grid-cols-[1fr_1.35fr_1fr_1fr] gap-3">
{card("결과 · 배당", "RESULT", podium)}
{card("전개 흐름", "PACE MAP · 통과순위", bump_chart())}
{card("막판 600m 빠른 말", "CLOSERS", closers)}
{card("내 표시 결과", "MY PICKS", picks)}
</div>"""


def page(state: str) -> str:
    title = "경주 · 출마표 (경주 전)" if state == "pre" else "경주 · 결과·기록표 (경주 후)"
    main = race_head(state) + (pre_insights() + pre_table() if state == "pre" else post_insights() + post_table())
    return head(title) + f"""
<body>
<div class="app-bg min-h-screen">
{header()}
<main class="mx-auto w-[calc(100%-48px)] max-w-[1520px] pb-12">
{day_bar(state)}
<div class="flex items-start gap-5">
{rail(state)}
<section class="min-w-0 flex-1">{main}</section>
</div>
</main>
<footer class="mx-auto flex w-[calc(100%-48px)] max-w-[1520px] justify-between border-t border-line py-6 text-[12px] text-faint">
  <span class="mono tracking-[.12em]">MAPILOG · HORSE RACING DATA</span><span>한국마사회 공공데이터 기반</span>
</footer>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    (OUT / "03-race-tab-entry-card-pre.html").write_text(page("pre"), encoding="utf-8")
    (OUT / "04-race-tab-result-post.html").write_text(page("post"), encoding="utf-8")
    print("written")
