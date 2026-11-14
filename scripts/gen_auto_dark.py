#!/usr/bin/env python3
"""
다크모드 누락 점검 + 자동 보정 (078)
====================================
라이트 기본 페이지(common.css 사용)에서 다크모드(body.sf-dark)로 바꿨을 때
밝은 배경·어두운 글씨가 그대로 남는 CSS 규칙을 찾아서, 페이지마다
<style id="sf-auto-dark"> 블록에 다크용 규칙을 자동으로 만들어 넣는다.

  - 이미 다크 규칙이 있는 요소는 건드리지 않음 (기존 수작업 다크 색 유지)
  - 규칙을 "추가"만 함. 기존 CSS는 수정하지 않음
  - 다시 돌리면 sf-auto-dark 블록만 새로 만들어 교체 (여러 번 돌려도 안전)

사용법 (레포 루트에서)
  python3 scripts/gen_auto_dark.py --check          # 점검만 (파일 안 바꿈)
  python3 scripts/gen_auto_dark.py                   # 전 페이지 적용
  python3 scripts/gen_auto_dark.py landtax portfolio # 지정 페이지만

새 페이지를 만들거나 페이지 CSS를 고친 뒤에는 이 스크립트를 한 번 돌릴 것.

한계 (자동으로 못 잡는 것)
  - canvas 차트 색 (JS에서 직접 그리는 색)
  - 그라데이션·이미지 배경
  - JS가 style 속성에 직접 넣는 색 중 common.css의 인라인 보정 목록에 없는 값
"""
import os, re, sys, glob, colorsys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK_ID = 'sf-auto-dark'
BLOCK_RE = re.compile(r'\n?<style id="%s">.*?</style>\n?' % BLOCK_ID, re.S)

# 다크 팔레트 (common.js 다크 규칙과 같은 계열)
SURFACE   = '#1e242e'   # 흰색 계열 박스
SURFACE_2 = '#1a1f29'   # 아주 옅은 회색 박스
SURFACE_3 = '#232a35'   # 회색 박스
BORDER    = '#2c333f'

NAMED = {'white': '#ffffff', 'black': '#000000', 'whitesmoke': '#f5f5f5', 'gray': '#808080', 'grey': '#808080',
         'silver': '#c0c0c0', 'lightgray': '#d3d3d3', 'lightgrey': '#d3d3d3', 'red': '#ff0000', 'blue': '#0000ff',
         'green': '#008000', 'navy': '#000080', 'ivory': '#fffff0', 'snow': '#fffafa', 'gainsboro': '#dcdcdc'}
COLOR_TOKEN = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:%s)\b' % '|'.join(NAMED), re.I)

# 다크로 바꾸면 안 되는 것 (인쇄물·종이 미리보기 등)
SKIP_SELECTOR = re.compile(r'print|paper|receipt|a4|sheet-preview|qr|statement|\.sup-', re.I)


def parse_color(tok):
    """색 문자열 → (r,g,b,a) 0~1. 실패 시 None."""
    tok = tok.strip().lower()
    if tok in NAMED:
        tok = NAMED[tok]
    if tok.startswith('#'):
        h = tok[1:]
        if len(h) in (3, 4):
            h = ''.join(ch * 2 for ch in h)
        if len(h) not in (6, 8):
            return None
        try:
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        except ValueError:
            return None
        return r, g, b, a
    m = re.match(r'rgba?\(([^)]*)\)', tok)
    if m:
        parts = [p for p in re.split(r'[\s,/]+', m.group(1).strip()) if p]
        try:
            vals = [float(p.rstrip('%')) for p in parts]
        except ValueError:
            return None
        if len(vals) < 3:
            return None
        a = vals[3] if len(vals) > 3 else 1.0
        if a > 1:
            a /= 100
        return vals[0] / 255, vals[1] / 255, vals[2] / 255, a
    return None


def lum(c):
    def f(x):
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def to_hex(r, g, b):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b))


def dark_bg(c):
    """밝은 배경색 → 다크 배경색."""
    h, l, s = colorsys.rgb_to_hls(c[0], c[1], c[2])
    if s < 0.2 or l > 0.985:
        if l >= 0.97:
            return SURFACE
        if l >= 0.93:
            return SURFACE_2
        return SURFACE_3
    return to_hex(*colorsys.hls_to_rgb(h, 0.15, min(s, 0.45)))   # 색감은 살리고 어둡게


def light_text(c):
    """어두운 글씨색 → 다크 배경용 밝은 글씨색."""
    h, l, s = colorsys.rgb_to_hls(c[0], c[1], c[2])
    if s < 0.15:
        nl = max(0.62, min(0.87, 1 - l * 0.6))
        return to_hex(nl, nl, nl)
    return to_hex(*colorsys.hls_to_rgb(h, max(l, 0.70), min(s, 0.85)))


def is_dark_text(c):
    h, l, s = colorsys.rgb_to_hls(c[0], c[1], c[2])
    L = lum(c)
    return L < 0.22 if s < 0.15 else L < 0.14


def dark_border(c):
    h, l, s = colorsys.rgb_to_hls(c[0], c[1], c[2])
    if s < 0.2:
        return BORDER
    return to_hex(*colorsys.hls_to_rgb(h, 0.30, min(s, 0.5)))


# ───────────────────────── CSS 파싱 ─────────────────────────
def strip_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def parse_rules(css, media=None):
    """→ [(selector, [(prop, value)], media)]. @media 1단계 중첩 지원."""
    out = []
    i, n = 0, len(css)
    while i < n:
        j = css.find('{', i)
        if j < 0:
            break
        head = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        if head.startswith('@'):
            if re.match(r'@(media|supports)', head) and 'print' not in head:
                out.extend(parse_rules(body, head))
        elif head:
            decls = []
            for d in body.split(';'):
                if ':' in d:
                    p, v = d.split(':', 1)
                    decls.append((p.strip().lower(), v.strip()))
            out.append((' '.join(head.split()), decls, media))
        i = k
    return out


def split_selectors(sel):
    parts, depth, cur = [], 0, ''
    for ch in sel:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


STRUCT = re.compile(r':(?:nth-child|nth-of-type|nth-last-child|nth-last-of-type)\([^)]*\)|:(?:first|last|only)-(?:child|of-type)')


def compounds(sel, keep_struct=False):
    """'.a .b > .c:hover' → [{'.a'}, {'.b'}, {'.c'}] (가상클래스·속성 제거한 토큰 집합).
    keep_struct=True: :nth-child(even) 같은 구조 가상클래스는 토큰으로 남김 (095, 배경 판정용)"""
    if keep_struct:
        sel = STRUCT.sub(lambda m: ' \x00' + m.group(0).replace(' ', '') + '\x00 ', sel)
        sel = re.sub(r' \x00(.*?)\x00 ', lambda m: '\x01' + m.group(1).replace(':', '\x02').replace('(', '\x03').replace(')', '\x04').replace('+', '\x05'), sel)
    sel = re.sub(r'::?[\w-]+(\([^)]*\))?', '', sel)
    sel = re.sub(r'\[[^\]]*\]', '', sel)
    out = []
    for comp in re.split(r'[\s>+~]+', sel.strip()):
        toks = set(t.replace('\x01', ':').replace('\x02', ':').replace('\x03', '(').replace('\x04', ')').replace('\x05', '+')
                   for t in re.findall(r'\x01?[.#\x02]?[\w\x02\x03\x04\x05-]+', comp))
        if toks:
            out.append(toks)
    return out


def covers(dark_comps, light_comps):
    """다크 규칙(선택자)이 라이트 규칙의 대상 요소에도 걸리는지 근사 판정."""
    if not dark_comps or not light_comps:
        return False
    if not dark_comps[-1] <= light_comps[-1]:
        return False
    pos = len(light_comps) - 2
    for dc in reversed(dark_comps[:-1]):
        while pos >= 0 and not dc <= light_comps[pos]:
            pos -= 1
        if pos < 0:
            return False
        pos -= 1
    return True


def group_of(prop):
    if prop in ('background', 'background-color'):
        return 'bg'
    if prop == 'color':
        return 'color'
    if prop.startswith('border') and not prop.endswith(('radius', 'width', 'style', 'collapse', 'spacing')):
        return 'border'
    return None


def collect_dark(rules):
    """다크 규칙 목록 → [(compounds, {group})]"""
    out = []
    for sel, decls, _ in rules:
        if 'sf-dark' not in sel:
            continue
        groups = {group_of(p) for p, _ in decls} - {None}
        if not groups:
            continue
        for part in split_selectors(sel):
            if 'sf-dark' not in part:
                continue
            stripped = re.sub(r'^.*?sf-dark\S*\s*', '', part).strip()
            if not stripped:
                continue
            if 'bg' in groups and STRUCT.search(stripped):
                # (095) 「짝수 줄만」 다크 배경은 같은 짝수 줄 규칙만 덮음 → 배경은 구조 가상클래스를 남긴 채 판정
                #       (안 그러면 tr.hit 같은 밝은 줄 배경이 다크를 못 받음 — 095 jaechohwan 누진표)
                out.append((compounds(stripped, True), {'bg'}))
                rest = groups - {'bg'}
                if rest:
                    out.append((compounds(stripped), rest))
                continue
            out.append((compounds(stripped), groups))
    return out


def shared_dark_rules():
    """모든 페이지에 공통으로 걸리는 다크 규칙 (common.js 주입분 + common.css 등)."""
    css = ''
    for name in ('common.css', 'auth-guard.css'):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            css += strip_comments(open(p, encoding='utf-8').read()) + '\n'
    for name in ('common.js', 'sf-slots.js'):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            js = open(p, encoding='utf-8').read()
            css += '\n'.join(re.findall(r'body\.sf-dark[^{}]*\{[^{}]*\}', js)) + '\n'
    rules = parse_rules(css)
    # <body class="sf-no-pblock"> 페이지에는 적용되지 않는 규칙(흡수한 표준 블록)은 따로 구분
    full = collect_dark(rules)
    limited = collect_dark([r for r in rules if 'sf-no-pblock' not in r[0]])
    return full, limited


def common_vars():
    p = os.path.join(ROOT, 'common.css')
    out = {}
    if os.path.exists(p):
        for sel, decls, _ in parse_rules(strip_comments(open(p, encoding='utf-8').read())):
            if sel == ':root':
                for k, v in decls:
                    if k.startswith('--'):
                        out[k] = v
    return out


def resolve_vars(v, table, depth=0):
    """var(--x, 대체값) → 실제 값. 모르는 변수가 있으면 None."""
    if 'var(' not in v:
        return v
    if depth > 4:
        return None
    ok = [True]

    def sub(m):
        name, fb = m.group(1), m.group(2)
        if name in table:
            return table[name]
        if fb:
            return fb.strip()
        ok[0] = False
        return ''
    r = re.sub(r'var\(\s*(--[\w-]+)\s*(?:,([^()]*))?\)', sub, v)
    if not ok[0]:
        return None
    return resolve_vars(r, table, depth + 1)


INPUTISH = re.compile(r'(?:^|[\s>+~])(?:input|select|textarea)\b')


def analyze(html, shared, cvars=None):
    """→ (만들 규칙 문자열 목록, 통계)"""
    html_wo = BLOCK_RE.sub('\n', html)
    css_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html_wo, re.S)
    rules = []
    for b in css_blocks:
        rules.extend(parse_rules(strip_comments(b)))
    dark = shared + collect_dark(rules)

    def is_covered(sel_part, group):
        lc = compounds(sel_part, group == 'bg')
        for dc, groups in dark:
            if group in groups and covers(dc, lc):
                return True
        return False

    # 페이지 자체 CSS 변수 (:root{--x:#fff}) 중 다크 재정의가 없는 것
    var_defs, var_dark = {}, set()
    for sel, decls, _ in rules:
        for p, v in decls:
            if p.startswith('--'):
                if 'sf-dark' in sel:
                    var_dark.add(p)
                elif sel in (':root', 'html', 'body'):
                    var_defs[p] = v
    var_use = collections.defaultdict(set)
    for sel, decls, _ in rules:
        for p, v in decls:
            g = group_of(p)
            if g:
                for name in re.findall(r'var\((--[\w-]+)', v):
                    var_use[name].add(g)

    out = collections.OrderedDict()   # (media, selector) → {prop: value}
    keep = collections.OrderedDict()  # 상태·변형 규칙 원래 색 유지용
    emitted = []                      # [(media, selector part, group)]
    untouched = []                    # [(media, part, group, prop, value)] 변환 안 한 색 선언
    stats = collections.Counter()

    def emit(media, sel, decl, bucket=None):
        prop, val = decl.split(':', 1)
        (out if bucket is None else bucket).setdefault((media, sel), collections.OrderedDict())[prop] = val

    # 변수 값 표: 공통(--sf-*) + 페이지 자체. 다크에서 다시 정의되는 변수는 제외(이미 처리된 것)
    vtable = dict(cvars or {})
    vtable.update(var_defs)
    for name in var_dark:
        vtable.pop(name, None)

    var_decls = []
    for name, val in var_defs.items():
        if name in var_dark or name.startswith('--sf-') or name.startswith('--p-'):
            continue
        m = COLOR_TOKEN.fullmatch(val.strip())
        c = parse_color(val) if m else None
        if not c or c[3] < 0.5:
            continue
        use = var_use.get(name, set())
        L = lum(c)
        if use and use <= {'bg', 'border'} and L > 0.80:
            var_decls.append('%s:%s' % (name, dark_bg(c) if 'bg' in use else dark_border(c)))
            stats['변수'] += 1
        elif use == {'color'} and L < 0.20:
            var_decls.append('%s:%s' % (name, light_text(c)))
            stats['변수'] += 1
    if var_decls:
        for d in var_decls:
            emit(None, '', d)
            vtable.pop(d.split(':', 1)[0], None)   # 다크 값이 생겼으니 아래에서 다시 풀지 않음

    for sel, decls, media in rules:
        if 'sf-dark' in sel or sel.startswith(('from', 'to')) or re.match(r'^\d', sel):
            continue
        if SKIP_SELECTOR.search(sel):
            continue
        props = dict(decls)
        # 이 규칙 자체의 배경 밝기 (글씨색 판단용)
        own_bg = None
        for bp in ('background', 'background-color'):
            if bp in props and 'gradient' not in props[bp] and 'url(' not in props[bp]:
                m = COLOR_TOKEN.search(props[bp])
                if m:
                    own_bg = parse_color(m.group(0))
        mid_bg = own_bg is not None and own_bg[3] >= 0.5 and 0.20 < lum(own_bg) <= 0.80

        for part in split_selectors(sel):
            if part in (':root', 'html', 'body', '*') or part.startswith('body.') or '@' in part:
                continue
            inputish = bool(INPUTISH.search(part))
            for p, v in decls:
                g = group_of(p)
                if not g:
                    continue
                raw = v.replace('!important', '').strip()
                if 'gradient' in v or 'url(' in v:
                    untouched.append((media, part, g, p, raw))
                    continue
                val = resolve_vars(raw, vtable)
                if val is None:
                    untouched.append((media, part, g, p, raw))
                    continue
                if val in ('none', 'transparent', 'inherit', 'initial', 'unset', '0', 'currentcolor'):
                    continue
                m = COLOR_TOKEN.search(val)
                if not m:
                    continue
                c = parse_color(m.group(0))
                if not c or c[3] < 0.5:
                    continue
                L = lum(c)
                if g == 'bg' and L > 0.80:
                    if inputish or is_covered(part, 'bg'):
                        continue
                    emit(media, part, 'background-color:%s!important' % dark_bg(c))
                    emitted.append((media, part, 'bg'))
                    stats['배경'] += 1
                elif g == 'color' and is_dark_text(c):
                    if mid_bg or inputish or is_covered(part, 'color'):
                        continue
                    emit(media, part, 'color:%s!important' % light_text(c))
                    emitted.append((media, part, 'color'))
                    stats['글씨'] += 1
                elif g == 'border' and L > 0.62:
                    if inputish or is_covered(part, 'border'):
                        continue
                    side = re.match(r'border-(top|right|bottom|left)', p)
                    prop = 'border-%s-color' % side.group(1) if side else 'border-color'
                    emit(media, part, '%s:%s!important' % (prop, dark_border(c)))
                    emitted.append((media, part, 'border'))
                    stats['테두리'] += 1
                else:
                    untouched.append((media, part, g, p, raw))

    # 위에서 만든 !important 규칙이 같은 요소의 상태·변형 규칙(.active, .primary, :hover 등)의
    # 원래 색을 덮어쓰지 않도록, 그런 규칙은 원래 값을 다크용으로 한 번 더 적어 줌
    em_comps = [(m, s, g, compounds(s)) for m, s, g in emitted]
    for media, part, g, p, raw in untouched:
        if is_covered(part, g):
            continue
        pc = compounds(part)
        for m2, s2, g2, sc in em_comps:
            if g2 == g and s2 != part and covers(sc, pc):
                if g == 'border':
                    cm = COLOR_TOKEN.search(resolve_vars(raw, vtable) or '')
                    if not cm:
                        break
                    side = re.match(r'border-(top|right|bottom|left)', p)
                    emit(media, part, '%s:%s!important' % ('border-%s-color' % side.group(1) if side else 'border-color', cm.group(0)), keep)
                else:
                    emit(media, part, '%s:%s!important' % (p, raw), keep)
                stats['유지'] += 1
                break

    lines = []
    for bucket in (out, keep):
        for (media, sel), ds in bucket.items():
            body = ';'.join('%s:%s' % kv for kv in ds.items())
            rule = 'body.sf-dark{%s}' % body if sel == '' else 'body.sf-dark %s{%s}' % (sel, body)
            lines.append('%s{%s}' % (media, rule) if media else rule)
    return lines, stats


def target_pages(args):
    if args:
        files = []
        for a in args:
            a = a.strip('/')
            p = os.path.join(ROOT, a, 'index.html') if not a.endswith('.html') else os.path.join(ROOT, a)
            if os.path.exists(p):
                files.append(p)
            else:
                print('  ⚠ 없음:', a)
        return files
    return sorted(glob.glob(os.path.join(ROOT, '**', '*.html'), recursive=True))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    check = '--check' in sys.argv
    shared = shared_dark_rules()
    cvars = common_vars()
    total = collections.Counter()
    changed = 0
    for path in target_pages(args):
        html = open(path, encoding='utf-8').read()
        # 라이트 기본 페이지만 대상 (다크 전용 페이지는 common-dark.css를 씀)
        if 'common.css' not in html or 'common-dark.css' in html:
            continue
        body_tag = re.search(r'<body[^>]*>', html)
        use = shared[1] if (body_tag and 'sf-no-pblock' in body_tag.group(0)) else shared[0]
        lines, stats = analyze(html, use, cvars)
        rel = os.path.relpath(path, ROOT)
        base = BLOCK_RE.sub('\n', html)
        if lines:
            block = ('\n<style id="%s">\n/* 자동 생성 (scripts/gen_auto_dark.py) — 직접 고치지 말 것. 페이지 CSS를 바꾼 뒤 스크립트를 다시 돌리면 갱신됨 */\n%s\n</style>\n'
                     % (BLOCK_ID, '\n'.join(lines)))
            m = re.search(r'<style\b', base)
            head_end = base.find('</head>')
            if m and (head_end < 0 or m.start() < head_end):
                new = base[:m.start()] + block.lstrip('\n') + base[m.start():]
            elif head_end >= 0:
                new = base[:head_end] + block.lstrip('\n') + base[head_end:]
            else:
                print('  ⚠ <style>·</head> 없음:', rel)
                continue
        else:
            new = base
        total.update(stats)
        if sum(stats.values()):
            print('%-46s 배경 %3d · 글씨 %3d · 테두리 %3d · 변수 %2d · 유지 %2d' % (rel, stats['배경'], stats['글씨'], stats['테두리'], stats['변수'], stats['유지']))
        if new != html:
            changed += 1
            if not check:
                open(path, 'w', encoding='utf-8').write(new)
    print('─' * 60)
    print('합계: 배경 %d · 글씨 %d · 테두리 %d · 변수 %d / %s 파일 %d개'
          % (total['배경'], total['글씨'], total['테두리'], total['변수'], '바뀔' if check else '바뀐', changed))


if __name__ == '__main__':
    main()
