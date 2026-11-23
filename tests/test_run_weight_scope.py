import re

from decomprepair import run_weight_scope
from decomprepair.run_weight_scope import FAMILY, units, variants

SOURCE = """void spawn(void **arg0, void *arg1, s32 arg2) {
    void *rec;
    s32 count;
    s32 buf;
    f32 scale;

    count = *(u16 *)((char *)arg1 + 4);
    if ((arg2 & 0xFF) != 0) {
        rec = alloc(*arg0, 1);
        *arg0 = rec;
        *(s32 *)((char *)rec + 0x3C) = count;
        *(u16 *)((char *)rec + 0x40) = count;
        if (count > 3) {
            *(u8 *)((char *)rec + 0x48) |= 4;
        } else {
            *(u8 *)((char *)rec + 0x48) |= 8;
        }
        buf = heap(count * 2, 5);
        *(s32 *)((char *)rec + 0x38) = buf;
        scale = 0.5f;
        *(f32 *)((char *)rec + 0x30) = *(f32 *)((char *)arg1 + 0x18) * scale;
        *(f32 *)((char *)rec + 0x34) = *(f32 *)((char *)arg1 + 0x1C) * scale;
        *(f32 *)((char *)rec + 0x38) = *(f32 *)((char *)arg1 + 0x20) * scale;
        build(rec, buf, count);
    }
    finish(*arg0);
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _unwrap(text):
    stripped = _flat(text)
    while re.search(r'do \{ ((?:(?!do \{).)*?) \} while \(0\);', stripped):
        stripped = re.sub(r'do \{ ((?:(?!do \{).)*?) \} while \(0\);', r'\1', stripped, count=1)
    return stripped


def test_an_if_block_a_run_and_a_statement_are_units_with_the_names_they_hold():
    found = units(SOURCE, 'spawn')
    kinds = {}
    for _, _, text, counts, kind in found:
        kinds.setdefault(kind, []).append((_flat(text), counts))
    block = next(counts for text, counts in kinds[0] if text.startswith('if ((arg2 & 0xFF) != 0) {'))
    assert block['rec'] >= 10 and block['scale'] == 4 and block['count'] >= 5
    assert any(text.startswith('*(f32 *)((char *)rec + 0x30)') and text.count(';') == 3 and counts['scale'] == 3
               for text, counts in kinds[1])
    assert ('build(rec, buf, count);', {'rec': 1, 'buf': 1, 'count': 1}) in kinds[2]
    # the compound statements come first, then the heaviest runs
    assert found[0][4] == 0
    heavy = [sum(counts.values()) for *_, counts, kind in found if kind != 0]
    assert heavy == sorted(heavy, reverse=True)


def test_a_child_wraps_one_unit_in_a_one_shot_scope_and_nothing_else_changes():
    children = variants(SOURCE, 'spawn')
    assert 0 < len(children) <= run_weight_scope.LIMIT
    assert len({text for _, text in children}) == len(children)
    for family, text in children:
        assert family == FAMILY
        assert text != SOURCE and text.count('do {') == 1 and text.count('} while (0);') == 1
        assert _unwrap(text) == _flat(SOURCE)
    flat = [_flat(text) for _, text in children]
    assert any('do { if ((arg2 & 0xFF) != 0) {' in text and '} } while (0); finish(*arg0);' in text for text in flat)
    assert any('do { build(rec, buf, count); } while (0);' in text for text in flat)
    run = ('do { *(f32 *)((char *)rec + 0x30) = *(f32 *)((char *)arg1 + 0x18) * scale; '
           '*(f32 *)((char *)rec + 0x34) = *(f32 *)((char *)arg1 + 0x1C) * scale; '
           '*(f32 *)((char *)rec + 0x38) = *(f32 *)((char *)arg1 + 0x20) * scale; } while (0);')
    assert any(run in text for text in flat)


def test_a_run_may_hold_a_compound_statement():
    flat = [_flat(text) for _, text in variants(SOURCE, 'spawn')]
    inner = ('do { *(u16 *)((char *)rec + 0x40) = count; if (count > 3) { *(u8 *)((char *)rec + 0x48) |= 4; } else '
             '{ *(u8 *)((char *)rec + 0x48) |= 8; } buf = heap(count * 2, 5); } while (0);')
    assert any(inner in text for text in flat)


def test_what_a_scope_would_change_is_left_alone():
    loops = """void f(s32 *arg0, s32 n) {
    s32 i;

    for (i = 0; i < n; i++) {
        if (arg0[i] == 0) {
            break;
        }
        use(arg0[i]);
    }
    if (n > 2) {
        goto out;
    }
    use2(n);
out:
    use3(n);
}
"""
    texts = [_flat(text) for _, text in variants(loops, 'f')]
    assert texts
    assert not any('do { if (arg0[i] == 0) { break; }' in text for text in texts)
    assert not any('goto out; } } while (0);' in text or 'do { if (n > 2) { goto out; }' in text for text in texts)
    assert not any('out: use3(n); } while (0)' in text or 'do { out:' in text for text in texts)
    assert any('do { use(arg0[i]); } while (0);' in text for text in texts)


def test_declarations_asm_volatile_and_existing_scopes_are_not_units():
    assert variants('void f(void) { g(); h(); }', 'f') == []
    assert variants('void f(s32 a) { asm("nop"); g(a); h(a); }', 'f') == []
    assert variants('void f(volatile s32 *a) { s32 b; b = *a; g(b); }', 'f') == []
    wrapped = 'void f(s32 a) { s32 b; b = a; do { g(b); h(a); } while (0); }'
    assert variants(wrapped, 'f')  # a run inside an existing scope is one scope deeper: the ladders go three deep
    found = units(wrapped, 'f')
    assert not any(_flat(text).startswith('do {') for _, _, text, _, _ in found)
    nested = 'void f(s32 a) { s32 b; b = a; if (a) { s32 c; c = b; g(c); } }'
    assert not any('s32 c;' in _flat(text) and _flat(text).startswith('do {') for _, text in variants(nested, 'f'))


def test_the_family_is_registered_and_declines_a_function_it_cannot_read():
    from decomprepair import registry
    assert any(entry.module.endswith('run_weight_scope') for entry in registry.declared())
    assert variants('void other(void) { }', 'f') == []
    assert variants('void f(s32 a) {\n#define X 1\n g(a); h(a); }', 'f') == []
