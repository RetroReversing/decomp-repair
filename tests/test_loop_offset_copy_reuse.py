from decomprepair import loop_offset_copy_reuse as lr

SOURCE = """\
typedef struct { f32 a, b; } Out;
typedef struct { f32 x, y; } In;
extern f32 D_ONE;
void *alloc(s32);
void init(Player *p, Src *s)
{
    s32 i;
    s32 n;
    n = s->count;
    p->count = n;
    p->buf = alloc(n * sizeof(Out) + n * sizeof(Out) + n * sizeof(In));
    for (i = 0; i < p->count; i++) {
        p->buf[i].a = D_ONE;
        p->buf[i].b = p->src->items[i].y;
    }
}
"""


def children():
    return lr.variants(SOURCE, 'init')


def test_the_statement_reads_the_count_through_the_loop_counter():
    family, text = children()[0]
    assert family == 'loop_counter_copy_reuse'
    assert 'i = n;\n    p->buf = alloc(i * sizeof(Out) + i * sizeof(Out) + i * sizeof(In));' in text
    assert 'for (i = 0; i < p->count; i++)' in text


def test_a_byte_offset_the_loop_steps_holds_the_copy_and_reads_the_records():
    texts = {f: t for f, t in reversed(children())}
    text = [t for f, t in children() if f == 'loop_offset_copy_reuse' and 'p->src->items)' in t][0]
    assert 's32 off;' in text and 'f32 k0;' in text
    assert 'off = n;\n    p->buf = alloc(off * sizeof(Out)' in text
    # the guard, the float constant first, then the offset: the target's preheader order
    assert text.index('i = 0;\n    if (i < p->count) {') < text.index('k0 = D_ONE;') < text.index('off = 0;')
    assert '((__typeof__(p->src->items))(off + (s32)p->src->items))->y' in text
    assert 'p->buf[i].a = k0;' in text
    assert text.index('i++;') < text.index('off += sizeof(*p->src->items);') < text.index('} while (i < p->count);')
    assert 'loop_offset_copy_reuse_plain' in texts


def test_declines_a_loop_that_can_leave_early_or_a_statement_that_writes_the_count():
    assert lr.variants(SOURCE.replace('p->buf[i].a = D_ONE;', 'if (i > 3) break;\n        p->buf[i].a = D_ONE;'), 'init') == []
    assert lr.variants(SOURCE.replace('alloc(n * sizeof(Out)', 'alloc(n++ * sizeof(Out)'), 'init') == []
