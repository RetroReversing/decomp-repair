from decomprepair.arm_increment_temp import FAMILY, variants

SOURCE = """
void draw(int flag) {
    Gfx *dl;
    u32 sel;

    if (flag) {
        dl = D_cursor;
        sel = D_slot;
        D_cursor = dl + 1;
        dl->w0 = 1;
        sel -= 0x80000000;
    } else {
        dl = D_cursor;
        dl->w0 = 1;
        sel = *(s32 *)((char *)D_state + 0x74C);
        D_cursor = dl + 1;
        sel -= 0x80000000;
    }
    ((u32 *)dl)[1] = sel;
}
"""


def test_every_arm_stores_the_increment_through_one_temporary():
    [(family, revised)] = variants(SOURCE, 'draw')
    assert family == FAMILY
    assert revised.count('cursor_next = dl + 1;') == 2 and revised.count('D_cursor = cursor_next;') == 2
    assert revised.index('Gfx *cursor_next;') < revised.index('if (flag)')
    assert revised.index('u32 sel;') < revised.index('Gfx *cursor_next;')
    assert variants(revised, 'draw') == []


def test_a_single_store_a_local_target_or_a_non_pointer_stays_put():
    one = SOURCE.replace('D_cursor = dl + 1;\n        sel -= 0x80000000;\n    }', 'sel -= 0x80000000;\n    }')
    assert variants(one, 'draw') == []
    assert variants(SOURCE.replace('    u32 sel;', '    u32 sel;\n    Gfx *D_cursor;'), 'draw') == []
    assert variants(SOURCE.replace('Gfx *dl;', 'u32 dl;'), 'draw') == []
