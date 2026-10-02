"""Geometric reading order shared by the viewer and the PDF worker.

PDF painting order need not be reading order. Separate wide gaps within a
painted line, then use whitespace cuts to read columns before their neighbour.
This is an inferred order, not a claim that an untagged PDF has semantics.
"""
from .model import union


def ordered_lines(model):
    visible = [g for g in model.glyphs if g.mode != 3 and g.opacity > 0]
    # A purely OCR page is readable too. Avoid copying a second OCR rendition
    # of visible text; an OCR-only block remains available beside real text.
    ocr = [g for g in model.glyphs if g.mode == 3 or g.opacity <= 0]
    visible_blocks = {g.block for g in visible}
    glyphs = visible + [g for g in ocr if g.block not in visible_blocks]
    groups = {}
    for glyph in glyphs:
        groups.setdefault((glyph.block, glyph.line, glyph.mode), []).append(glyph)
    lines = []
    for group in groups.values():
        # The baseline's direction also handles vertical and right-to-left
        # writing without sorting by arbitrary glyph identifiers.
        direction = group[0].direction
        group.sort(key=lambda g: (g.origin[0] * direction[0] +
                                  g.origin[1] * direction[1], g.id))
        part = []
        for glyph in group:
            if part and direction[0] > .8:
                gap = glyph.bbox[0] - part[-1].bbox[2]
                if gap > max(18., 2.5 * max(glyph.size, part[-1].size)):
                    lines.append(part)
                    part = []
            part.append(glyph)
        if part:
            lines.append(part)

    def whitespace_cut(items, axis):
        intervals = sorted((union(g.bbox for g in line)[axis],
                            union(g.bbox for g in line)[axis + 2])
                           for line in items)
        if not intervals:
            return None
        edge = intervals[0][1]
        gaps = []
        for start, end in intervals[1:]:
            if start > edge:
                gaps.append((start - edge, (start + edge) / 2.))
            edge = max(edge, end)
        threshold = 18. if axis == 0 else max(4., min(g.size for line in items for g in line) * .8)
        candidates = [(width, position) for width, position in gaps if width >= threshold]
        return max(candidates)[1] if candidates else None

    def order(items):
        if len(items) < 2:
            return items
        # A full-width heading naturally prevents the horizontal cut. A
        # vertical cut first isolates it and then discovers the columns below.
        for axis in (0, 1):
            cut = whitespace_cut(items, axis)
            if cut is not None:
                before = [line for line in items if union(g.bbox for g in line)[axis + 2] <= cut]
                after = [line for line in items if union(g.bbox for g in line)[axis] >= cut]
                if before and after and len(before) + len(after) == len(items):
                    return order(before) + order(after)
        return sorted(items, key=lambda line: (min(g.bbox[1] for g in line),
                                               min(g.bbox[0] for g in line)))

    return order(lines)


def ordered_glyphs(model):
    return [glyph for line in ordered_lines(model) for glyph in line]


def selection_text(model, start_id=None, end_id=None):
    """Inclusive character range; missing endpoint IDs fail rather than expand."""
    glyphs = ordered_glyphs(model)
    if not glyphs:
        return ""
    positions = {glyph.id: index for index, glyph in enumerate(glyphs)}
    if start_id is not None and start_id not in positions:
        raise ValueError("El inicio de la selección ya no pertenece a esta página.")
    if end_id is not None and end_id not in positions:
        raise ValueError("El final de la selección ya no pertenece a esta página.")
    start = positions[start_id] if start_id is not None else 0
    end = positions[end_id] if end_id is not None else len(glyphs) - 1
    start, end = sorted((start, end))
    result, previous = [], None
    for glyph in glyphs[start:end + 1]:
        if previous is not None:
            if glyph.block != previous.block:
                result.append("\n\n")
            elif glyph.line != previous.line:
                result.append("\n")
        result.append(glyph.text)
        previous = glyph
    return "".join(result)
