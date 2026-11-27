"""statement_slide reads `*(T *)((char *)(base) + off)`, the expanded spelling of `M2C_FIELD`, as a cell."""
from decomprepair import statement_slide as module

CTOR = """void f(void *arg0) {
    (*(s32 *)((char *)(arg0) + 0x14)) = -0x199;
    (*(s8 *)((char *)(arg0) + 0x7A)) = 2;
    (*(s8 *)((char *)(arg0) + 0x74)) = 2;
    (*(s8 *)((char *)(arg0) + 0x78)) = 1;
    (*(s8 *)((char *)(arg0) + 0x75)) = 3;
}
"""


def _offsets(text):
    return [line.split('+ ')[1].split(')')[0] for line in text.splitlines() if '+ 0x' in line]


def _children(source):
    return [text for _, text in module.variants(source, 'f')]


def test_a_store_slides_down_past_three_stores_of_other_bytes():
    assert ['0x7A', '0x74', '0x78', '0x14', '0x75'] in [_offsets(text) for text in _children(CTOR)]


def test_the_unwrapped_and_bare_base_spellings_move_too():
    bare = """void f(void *p) {
    *(s16 *)((char *)p + 4) = 1;
    *(s16 *)((char *)p + 6) = 2;
    *(s16 *)((char *)p + 8) = 3;
}
"""
    assert len(_children(bare)) >= 2


def test_overlapping_cells_stay_in_order():
    overlap = """void f(void *p) {
    (*(s32 *)((char *)(p) + 4)) = 1;
    (*(s16 *)((char *)(p) + 6)) = 2;
    (*(s16 *)((char *)(p) + 6)) = 3;
}
"""
    assert not _children(overlap)


def test_a_call_keeps_its_parentheses_and_stays_a_barrier():
    call = """void f(void *p) {
    s32 a;
    a = g (M2C_FIELD(p, s32 *, 4));
    M2C_FIELD(p, s32 *, 8) = 1;
    M2C_FIELD(p, s32 *, 0xC) = 2;
}
"""
    assert all(text.index('a = g') < text.index('s32 *, 8') for text in _children(call))
