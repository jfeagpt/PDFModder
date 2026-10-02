"""Conservative colour checks of effective PDF graphics states.

ISO 32000-1, table 58: OP also sets op unless both occur in the same
dictionary; TR2 takes precedence over TR there. Identity is a neutral transfer
function and Default restores the device's page-start transfer function.
The dictionaries/operators are retained unchanged by this read-only analysis.
"""
from dataclasses import dataclass, replace

from pypdf.generic import (ArrayObject, BooleanObject, ContentStream,
                          DictionaryObject, NameObject, NullObject)


COLOR_ISSUE = "Página con sobreimpresión o transferencia de color no admitida."
BLEND_ISSUE = "Página con mezcla de color o máscara de transparencia no reproducible."
_PAINT = {b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*', b'sh',
          b'Tj', b'TJ', b"'", b'"', b'INLINE IMAGE'}


def _resolve(value):
    return value.get_object() if hasattr(value, 'get_object') else value


def _entry(dictionary, key):
    value = _resolve(dictionary.get(key))
    # A null dictionary value is equivalent to the absence of the key.
    return None if isinstance(value, NullObject) else value


def _boolean(value):
    # bool(BooleanObject(False)) is True: pypdf wraps the PDF scalar.
    if isinstance(value, BooleanObject):
        return value.value is True
    if isinstance(value, bool):
        return value
    raise ValueError('El parámetro de sobreimpresión no es booleano.')


def _neutral_transfer(value, *, default=False):
    value = _resolve(value)
    if isinstance(value, NameObject):
        return value == '/Identity' or (default and value == '/Default')
    if isinstance(value, ArrayObject):
        return len(value) == 4 and all(_resolve(v) == '/Identity' for v in value)
    return False


def _normal_blend(value):
    value = _resolve(value)
    if isinstance(value, NameObject):
        return value in ('/Normal', '/Compatible')
    if isinstance(value, ArrayObject):
        # Do not guess the consumer's supported mode when alternatives differ.
        return bool(value) and all(_resolve(v) in ('/Normal', '/Compatible') for v in value)
    return False


@dataclass
class _State:
    stroke_overprint: bool = False
    fill_overprint: bool = False
    transfer: bool = False
    blend: bool = False
    mask: bool = False

    def update(self, values):
        op, nonstroke = _entry(values, '/OP'), _entry(values, '/op')
        if op is not None:
            self.stroke_overprint = _boolean(op)
            if nonstroke is None:
                self.fill_overprint = self.stroke_overprint
        if nonstroke is not None:
            self.fill_overprint = _boolean(nonstroke)
        tr2, tr = _entry(values, '/TR2'), _entry(values, '/TR')
        if tr2 is not None:
            self.transfer = not _neutral_transfer(tr2, default=True)
        elif tr is not None:
            self.transfer = not _neutral_transfer(tr)
        blend, mask = _entry(values, '/BM'), _entry(values, '/SMask')
        if blend is not None:
            self.blend = not _normal_blend(blend)
        if mask is not None:
            self.mask = mask != '/None'

    def issues(self):
        result = []
        if self.stroke_overprint or self.fill_overprint or self.transfer:
            result.append(COLOR_ISSUE)
        if self.blend or self.mask:
            result.append(BLEND_ISSUE)
        return result


def page_color_issues(reader, page, operations=None):
    """Only applied states matter; unused resource entries cannot paint.

    Check every paint operation, including inherited state in Form XObjects.
    A state reset before painting is harmless. Still check the page's final
    state because some edit paths append content. Malformed stacks, unresolved
    resources and cycles fail closed in the caller's existing analysis error.
    This is a page-level gate: genuine special-colour painting anywhere on the
    page remains unsupported, even if the selection is elsewhere.
    """
    result = []

    def visit(ops, resources, initial, ancestry=()):
        resources = _resolve(resources)
        if not isinstance(resources, (dict, DictionaryObject)):
            raise ValueError('Recursos gráficos no resolubles.')
        state, stack = replace(initial), []
        for args, operator in ops:
            if operator == b'q':
                stack.append(replace(state))
            elif operator == b'Q':
                if not stack:
                    raise ValueError('Pila de estado gráfico desequilibrada.')
                state = stack.pop()
            elif operator == b'gs':
                states = _resolve(resources.get('/ExtGState', {}))
                if len(args) != 1 or args[0] not in states:
                    raise ValueError('Estado gráfico no resoluble.')
                values = _resolve(states[args[0]])
                if not isinstance(values, (dict, DictionaryObject)):
                    raise ValueError('Estado gráfico sin diccionario.')
                state.update(values)
            elif operator == b'Do':
                result.extend(state.issues())
                objects = _resolve(resources.get('/XObject', {}))
                if len(args) != 1 or args[0] not in objects:
                    raise ValueError('Objeto gráfico no resoluble.')
                obj = _resolve(objects[args[0]])
                if obj.get('/Subtype') == '/Form':
                    identity = id(obj)
                    if identity in ancestry or len(ancestry) >= 32:
                        raise ValueError('Formularios gráficos cíclicos o demasiado anidados.')
                    visit(ContentStream(obj, reader).operations,
                          obj.get('/Resources', resources), state, (*ancestry, identity))
            elif operator in _PAINT:
                result.extend(state.issues())
        if stack:
            raise ValueError('Pila de estado gráfico desequilibrada.')
        return state

    ops = operations if operations is not None else ContentStream(page.get_contents(), reader).operations
    final = visit(ops, page.get('/Resources', {}), _State())
    result.extend(final.issues())
    return list(dict.fromkeys(result))
