"""Prototypes from the call sites for callees m2c declared with `()`, so `f32` arguments stay `f32`.

C promotes an `f32` argument to a callee declared without parameters to `double`: `cvt.d.s` and two argument words
(or an 8-byte stack slot) where the game passed a single float in `$f12`/`$f14` or a word. An N64 function's sin/cos
and draw calls took it from 77% to 98% once their prototypes were written from the arguments it passes. Offered when
every call passes the same number of arguments and at least one is a float; the others are `s32`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'call_site_prototype'
FAMILIES = (FAMILY,)

IDENT = r"[A-Za-z_]\w*"
DECL = re.compile(r"(?m)^(?P<ret>[\w ]+?[\s*]+)(?P<name>" + IDENT + r")\s*\(\s*\)\s*;(?P<rest>.*)$")
# (set per function by variants: the f32 locals and parameters, and the callees declared to return f32)
f32_names: set = set()
f32_funcs: set = set()
pointer_names: set = set()


def split_args(text):
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += (ch in "([") - (ch in ")]")
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def kind(arg):
    a = arg.strip()
    if a.startswith("&") or a in pointer_names or a == "NULL":
        return "ptr"
    if re.fullmatch(r"-?\d+\.\d*f?|-?\d*\.\d+f?|-?\d+(\.\d+)?e-?\d+f?", a):
        return "f32"
    if re.fullmatch(r"\(f32\)\s*.+", a):
        return "f32"
    if re.fullmatch(r"-?\s*(" + IDENT + r")(\s*\[[^]]*\])*", a):
        base = re.match(r"-?\s*(" + IDENT + ")", a)[1]
        if base in f32_names:
            return "f32"
    m = re.fullmatch(r"-?\s*(" + IDENT + r")\s*\(.*\)", a)
    if m and m[1] in f32_funcs:
        return "f32"
    if re.search(r"M2C_FIELD\([^;]*,\s*f32\s*\*", a) and a.startswith("M2C_FIELD") and a.count("M2C_FIELD") >= 1:
        if re.fullmatch(r"-?\s*M2C_FIELD\(.*,\s*f32\s*\*\s*,\s*[^,]+\)", a):
            return "f32"
    if re.search(r"\b\d+\.\d*f\b", a) or re.search(r"(?<![\w.])(" + "|".join(map(re.escape, f32_names or {"__none__"})) + r")(?![\w.])", a):
        # arithmetic on floats
        if not re.search(r"[&|^~%]|<<|>>", a):
            return "f32"
    return None




def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = source[opening:end]
    global f32_names, f32_funcs, pointer_names
    pointer_names = set(re.findall(r"(?m)^\s*[\w ]+?\*\s*(" + IDENT + r")\s*;", body))
    pointer_names |= set(re.findall(r"(?m)^\s*[\w ]+?\s+(" + IDENT + r")\s*\[[^]]*\]\s*;", body))
    pointer_names |= set(re.findall(r"\*\s*(" + IDENT + r")\s*[,)]", source[span[0]:opening]))
    f32_names = set(re.findall(r"(?m)^\s*f32\s+(" + IDENT + r")\s*(?:\[[^]]*\])*\s*;", body))
    f32_names |= set(re.findall(r"(?m)^\s*f32\s+(" + IDENT + r")\s*=", body))
    f32_names |= set(re.findall(r"\bf32\s+(" + IDENT + r")\s*[,)]", source[span[0]:opening]))
    outside = source[:span[0]]
    f32_funcs = {m["name"] for m in DECL.finditer(outside) if re.fullmatch(r"\s*f32\s*", m["ret"])}
    text = source
    for m in reversed(list(DECL.finditer(outside))):
        callee = m["name"]
        sigs = []
        for c in re.finditer(r"\b" + re.escape(callee) + r"\s*\(", body):
            start = c.end()
            depth, i = 1, start
            while i < len(body) and depth:
                depth += (body[i] == "(") - (body[i] == ")")
                i += 1
            sigs.append([kind(a) for a in split_args(body[start:i - 1])])
        if not sigs or not any("f32" in s for s in sigs) or len({len(s) for s in sigs}) != 1:
            continue
        params = []
        for k in range(len(sigs[0])):
            ks = {s[k] for s in sigs}
            # (an address, an array or a pointer local passed as `s32` is refused by the compiler: `void *` then)
            params.append("f32" if ks == {"f32"} else "void *" if ks == {"ptr"} else
                          "s32" if not ks & {"f32", "ptr"} else None)
        if None in params:
            continue
        ret = m['ret'].rstrip()
        proto = (ret + callee if ret.endswith('*') else f"{ret} {callee}") + f"({', '.join(params)});"
        text = text[:m.start()] + proto + m["rest"] + text[m.end():]
    return [(FAMILY, text)] if text != source else []
