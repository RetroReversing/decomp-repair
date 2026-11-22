from decomprepair import counted_loop_shapes as shapes

# the m2c shapes of four counted loops over a loaded table (a pointer walk, a stride, an address sum, a shifted product)
SOURCE = """void unpack(void *ctx) {
    u32 pad[8];
    u32 limit;
    u32 i;
    u32 k;
    u16 *base;
    u16 *cursor;
    u16 word;
    s32 scaled;
    s32 stride;
    void *entry;
    void *item;
    u32 extent;
    u8 *data;
    u8 *walk;
    u32 area;
    u32 width;
    u32 height;
    base = load(ctx);
    limit = count >> 1;
    i = 0;
    if (limit != 0) {
        cursor = base;
        do {
            word = *cursor;
            i += 1;
            *cursor = scale(word) + 1;
            cursor += 1;
        } while (i < (count >> 1));
    }
    i = 0;
    if ((*((u32 *) (((char *) ctx) + 0x14))) != 0) {
        do {
            *((s32 *) (((char *) ((i * 8) + (*((u8 **) (((char *) ctx) + 0x10))))) + 4)) = 1;
            scaled = i * 8; entry = scaled + (*((u8 **) (((char *) ctx) + 0x10)));
            *((void **) (((char *) entry) + 4)) = (void *) ((*((u32 *) (((char *) entry) + 4))) + 2);
            i += 1;
        } while (i < ((u32) (*((u32 *) (((char *) ctx) + 0x14)))));
    }
    k = 0;
    if ((*((u32 *) (((char *) ctx) + 0x1C))) != 0) {
        stride = 0;
        do {
            item = stride + (*((u8 **) (((char *) ctx) + 0x18)));
            *((s32 *) (((char *) item) + 8)) = 3;
            k += 1;
            stride += 0xC;
        } while (k < ((u32) (*((u32 *) (((char *) ctx) + 0x1C)))));
    }
    k = 0;
    if ((*((u32 *) (((char *) ctx) + 0x1C))) != 0) {
        stride = 0;
        do {
            item = stride + (*((u8 **) (((char *) ctx) + 0x18)));
            data = *((u8 **) (((char *) item) + 8));
            area = ((u32) (width * height)) >> 1;
            if (!((*((u8 *) (((char *) item) + 0))) & 1)) {
                if (((int) (((u32) (width * height)) >> 1)) != 0) {
                    walk = data;
                    do {
                        *walk = (*walk >> 4) | ((*walk & 0xF) * 0x10);
                        ++walk;
                    } while (((u32) walk) < ((u32) ((((u32) (width * height)) >> 1) + data)));
                }
            }
            k += 1;
            stride += 0xC;
        } while (k < ((u32) (*((u32 *) (((char *) ctx) + 0x1C)))));
    }
    done();
}
"""


def found(family, source=SOURCE):
    return [text for label, text in shapes.variants(source, 'unpack') if label == family]


def test_pointer_walk_becomes_an_index_with_the_step_last():
    text = found(shapes.INDEX)[0]
    assert 'word = base[i];' in text and '*cursor' not in text and 'cursor += 1' not in text
    assert 'base[i] = scale(word) + 1;' in text and 'cursor = base;' not in text
    assert text.index('base[i] = ') < text.index('i += 1;')


def test_stride_is_read_from_the_counter():
    first, second = found(shapes.STRIDE)[:2]
    assert 'item = k * 0xC + (*' in first and 'stride += 0xC' not in first.split('k = 0;')[1]
    assert 'stride' in first and 'stride += 0xC;' in first  # the other loop still has its own
    assert 'item = k * 0xC' in second


def test_later_counters_share_the_first_one():
    text = found(shapes.SHARE)[0]
    assert text.count('k = 0;') == 0 and 'u32 k;' not in text and 'k += 1' not in text
    assert text.count('i = 0;') == 4


def test_guarded_loops_become_for_loops_and_the_unused_array_goes_with_them():
    loops = found(shapes.FOR)
    assert all('for (i = 0; i < (count >> 1); i += 1)' not in text for text in loops)  # the walk has its step in the middle
    strided = found(shapes.STRIDE)[0]
    strided = found(shapes.STRIDE, strided)[0]
    text = found(shapes.FOR_FRAME, strided)[0]
    assert 'u32 pad[8];' not in text and text.count('for (') == 3
    assert 'for (i = 0; i < ((u32) (*((u32 *) (((char *) ctx) + 0x14)))); i += 1)' in text
    assert found(shapes.FOR_ALL, strided) and 'u32 pad[8];' in found(shapes.FOR_ALL, strided)[0]


def test_the_sum_lands_in_the_scaled_register():
    text = found(shapes.ACCUMULATE)[0]
    assert 'scaled = i * 8; scaled += (s32) (' in text
    assert '(((char *) scaled) + 4)' in text and 'entry' not in text.split('scaled +=')[1].split('i += 1')[0]


def test_an_integer_address_sum():
    chain = found(shapes.CHAIN)[0]
    assert 'item = (void *) (k * 0xC + (s32) (*' in chain or 'item = (void *) (i * 0xC + (s32) (*' in chain


def test_the_shift_moves_into_the_arm_that_uses_it():
    text = found(shapes.SHIFT)[0]
    assert 'area = ((u32) (width * height));' in text and 'area >>= 1;' in text
    assert '((int) area) != 0' in text and '>> 1)) != 0' not in text


def test_the_limit_sum_is_cast_per_operand():
    text = found(shapes.CASTS)[0] if found(shapes.CASTS) else ''
    chain = found(shapes.CHAIN)[0]
    assert '(u32) area + (u32) data' in chain or '(u32) area + (u32) data' in text


def test_the_chain_applies_every_step():
    chain = found(shapes.CHAIN)[0]
    assert 'do {' not in chain.split('area =')[0] and 'u32 pad[8];' not in chain
    assert chain.count('for (i = 0;') == 4 and 'cursor' not in chain


def test_refused_when_the_rewrite_would_change_a_loop():
    assert not found(shapes.FOR, SOURCE.replace('if ((*((u32 *) (((char *) ctx) + 0x14))) != 0)', 'if (other != 0)'))
    assert not found(shapes.FOR, SOURCE.replace('u32 i;', 's32 i;'))  # a signed counter's guard is not its first test
    assert not found(shapes.INDEX, SOURCE.replace('word = *cursor;', 'word = *cursor; cursor += 2;'))
    assert not found(shapes.STRIDE, SOURCE.replace('stride += 0xC;', 'stride += width;'))
