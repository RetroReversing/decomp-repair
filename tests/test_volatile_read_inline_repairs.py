from decomprepair import volatile_read_inline_repairs as r

DRAFT = '''void *spawn(s32, s32, s32);
s32 setFrame(void *, u16, s32);
extern s16 D_800C2942;

void *f(s32 arg0)
{
    u16 frame;
    s32 animation;
    void *obj;
    void *state;

    obj = spawn(0x30, arg0, 0);
    if (obj != NULL) {
        state = (*(void **)((char *)(obj) + 0x6C));
        (*(u16 *)((char *)(state) + 0x2C)) = 0U;
        frame = *(volatile u16 *)((char *)state + 0x2C);
        (*(s8 *)((char *)(state) + 0x28)) = 0;
        animation = D_800C2942;
        *(f32 *)((char *)state + 0x8) = 1.0f;
        setFrame(obj, frame, animation);
    }
    return obj;
}
'''


def _out(source=DRAFT):
    return [text for _family, text in r.variants(source, 'f')]


def test_the_volatile_local_becomes_a_plain_read_at_the_call():
    plain = _out()[0]
    assert 'setFrame(obj, *(u16 *)((char *)(state) + 0x2C), animation);' in plain
    assert 'frame = *(volatile' not in plain
    assert '    u16 frame;' in plain


def test_the_control_keeps_the_read_volatile_and_a_third_reads_it_just_before_the_call():
    out = _out()
    assert len(out) == 3
    assert 'setFrame(obj, *(volatile u16 *)((char *)(state) + 0x2C), animation);' in out[1]
    assert '        frame = *(u16 *)((char *)(state) + 0x2C);\n        setFrame(obj, frame, animation);' in out[2]


def test_a_store_over_the_bytes_read_blocks_it():
    assert _out(DRAFT.replace('0x28)) = 0;', '0x2D)) = 0;')) == []


def test_a_store_through_another_pointer_blocks_it():
    assert _out(DRAFT.replace('(*(s8 *)((char *)(state) + 0x28)) = 0;', '(*(s8 *)((char *)(obj) + 0x28)) = 0;')) == []


def test_a_call_between_blocks_it():
    assert _out(DRAFT.replace('animation = D_800C2942;', 'animation = other(obj);')) == []


def test_a_local_used_twice_is_left_alone():
    assert _out(DRAFT.replace('setFrame(obj, frame, animation);', 'setFrame(obj, frame, frame);')) == []


def test_a_plain_read_is_left_alone():
    assert _out(DRAFT.replace('*(volatile u16 *)', '*(u16 *)')) == []
