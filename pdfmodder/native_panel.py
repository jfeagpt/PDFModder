"""Panel requests use the same verified CID resources as the on-page editor."""
from dataclasses import replace
from difflib import SequenceMatcher

from .model import EditError, union
from .richmodels import RichTextRequest


def _replace_runs(runs, text):
    old=[]
    for run in runs:
        old.extend(dict(run,text=char) for char in run['text'])
    if not old:
        raise EditError('Selecciona un fragmento con texto.')
    before=''.join(r['text'] for r in old)
    result=[]
    for tag,a,b,c,d in SequenceMatcher(None,before,text,autojunk=False).get_opcodes():
        if tag=='equal':
            result.extend(old[a:b])
        elif d>c:
            if b-a==d-c:
                result.extend(dict(run,text=char) for run,char in zip(old[a:b],text[c:d]))
            else:
                source=old[min(a,len(old)-1)]
                result.extend(dict(source,text=char,char_spacing=0.) for char in text[c:d])
    return result


def edit_native_panel(data, request, model, resolver=None):
    from .richtext import edit_rich_pdf, selection_payload, move_rich_pdf
    if request.dx or request.dy or request.text is None and request.size is None and not request.font_name and not request.font_file and request.color is None:
        if request.text is not None or request.size is not None or request.font_name or request.font_file or request.color is not None:
            raise EditError('Aplica el texto o formato y después mueve el campo en una operación independiente.')
        return move_rich_pdf(data,request,resolver)
    selected=model.selected(request.ids)
    if any(a.line==b.line and b.id!=a.id+1 for a,b in zip(selected,selected[1:])):
        raise EditError('La selección contiene fragmentos separados. Edita cada fragmento o selecciona la línea completa.')
    payload=selection_payload(data,request.page,request.ids,resolver)
    text=request.text if request.text is not None else payload['text']
    text=text.replace('\r\n','\n').replace('\r','\n')
    runs=_replace_runs(payload['runs'],text)
    for run in runs:
        if request.size is not None:run['size']=request.size
        if request.color is not None:run['color']=request.color
        if request.font_name or request.font_file:
            run.update(font_name=request.font_name or run['font_name'],font_file=request.font_file,font_resource=None,font_xref=None)
    if request.anchor not in ('left','center','right','decimal'):
        raise EditError('Elige anclaje izquierdo, centrado, derecho o decimal.')
    bounds=union(g.bbox for g in selected)
    paragraphs=[dict(alignment=request.anchor if request.anchor!='decimal' else 'left',
                     line_spacing=request.line_spacing or 0.,space_after=request.paragraph_spacing)]
    rich=RichTextRequest(request.page,request.ids,runs,rect=bounds,width=request.width,height=request.height,
                         paragraphs=paragraphs,revision=request.revision,allow_overlap=request.allow_overlap,
                         auto_width=request.auto_width and not request.reflow,auto_height=request.auto_height)
    result,report=edit_rich_pdf(data,rich,resolver)
    if not request.reflow and report['line_count']>text.count('\n')+text.count('\u2028')+1:
        raise EditError('El texto supera la anchura disponible. Amplía el área o activa Redistribuir líneas.')
    shift=0.
    if rich.auto_width and request.anchor in ('right','center'):
        shift=(bounds[2]-bounds[0]-(report['rect'][2]-report['rect'][0]))/(2 if request.anchor=='center' else 1)
    if request.anchor=='decimal':
        if '\n' in text or '\u2028' in text:
            raise EditError('El anclaje decimal requiere una sola línea.')
        original=[g.origin[0] for g in selected if g.text==request.decimal_separator]
        updated=[g['origin'][0] for g in report['glyphs'] if g['text']==request.decimal_separator]
        if not original or not updated:
            raise EditError('No se encuentra el separador decimal elegido en ambos textos. Elige anclaje derecho.')
        shift=original[-1]-updated[-1]
    if abs(shift)>.00001:
        shifted=tuple(v+(shift if i%2==0 else 0.) for i,v in enumerate(bounds))
        result,report=edit_rich_pdf(data,replace(rich,rect=shifted),resolver)
    report.update(native_panel=True,line_reflow=False,line_reflow_requested=request.line_reflow,
                  paragraph_layout=request.reflow)
    if request.line_reflow:
        message='Se ha modificado el campo seleccionado conservando sus recursos PDF. Para redistribuir el resto de la línea, selecciona la línea completa en el editor sobre la página.'
        report.setdefault('warnings',[]).append(message)
        report['warning']=message
    return result,report
