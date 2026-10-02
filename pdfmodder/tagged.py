"""Conservación explícita de la estructura lógica de PDF etiquetado.

MCID, ParentTree y /K se verifican con pypdf. Las referencias se comparan por
identidad lógica, no por xref. No se certifica conformidad PDF/UA.
"""
from dataclasses import dataclass
from io import BytesIO
import hashlib
import copy
import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import (ContentStream,DecodedStreamObject,IndirectObject,
    DictionaryObject,NameObject,NumberObject,FloatObject,TextStringObject,NullObject)
from .model import EditError

SHOW={b'Tj',b'TJ',b"'",b'"'}
PAINT={b'Do',b'BI',b'INLINE IMAGE',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'sh'}


def obj(value):
    return value.get_object() if isinstance(value,IndirectObject) else value


def ref(value):
    value=value if isinstance(value,IndirectObject) else getattr(value,'indirect_reference',None)
    return (value.idnum,value.generation) if value is not None else None


def fail(message):
    raise EditError('PDF etiquetado: '+message)


def _integer(value,label):
    if not isinstance(value,int) or isinstance(value,bool) or value<0:
        fail(label+' debe ser un entero no negativo.')
    return int(value)


def _stream(operations):
    s=DecodedStreamObject()
    s.set_data(b'')
    result=ContentStream(s,None)
    result.operations=operations
    return result.get_data()


def _has_string(operands):
    if isinstance(operands,(str,bytes)):
        return bool(operands)
    return isinstance(operands,(list,tuple)) and any(_has_string(v) for v in operands)


def _number_tree(value,seen=None):
    value=obj(value)
    if not isinstance(value,dict):
        fail('ParentTree no es un árbol numérico válido.')
    seen=set() if seen is None else seen
    identity=id(value)
    if identity in seen:
        fail('ParentTree contiene un ciclo.')
    seen=seen|{identity}
    result={}
    numbers=obj(value.get('/Nums',[]))
    if len(numbers)%2:
        fail('ParentTree contiene pares incompletos.')
    for k,v in zip(numbers[::2],numbers[1::2]):
        key=_integer(k,'La clave ParentTree')
        if key in result:
            fail('ParentTree contiene claves repetidas.')
        result[key]=obj(v)
    for child in obj(value.get('/Kids',[])):
        for k,v in _number_tree(child,seen).items():
            if k in result:
                fail('ParentTree contiene claves repetidas.')
            result[k]=v
    return result


@dataclass
class Mark:
    mcid:int
    tag:object
    properties:object
    resolved:dict
    start:int
    end:int=-1
    paints:bool=False
    nested_actual:bool=False


class TaggedStructure:
    def __init__(self,data):
        self.data=data
        self.reader=PdfReader(BytesIO(data),strict=True)
        self.root=self.reader.trailer['/Root']
        self.tree=obj(self.root['/StructTreeRoot'])
        self.pages={ref(p):n for n,p in enumerate(self.reader.pages)}
        self.annotations={ref(a):(n,i) for n,p in enumerate(self.reader.pages)
                          for i,a in enumerate(obj(p.get('/Annots',[])))}
        self.nodes={}
        self.node_refs={ref(self.tree):('tree',)}
        self.owners={}
        self.object_owners=[]
        self.operations=[]
        self.marks=[]
        self.contexts=[]
        self.parents=_number_tree(self.tree.get('/ParentTree',{}))
        self.page_parent_keys={}
        self._walk(self.tree.get('/K',[]),(),ref(self.tree),None,0)
        for number,page in enumerate(self.reader.pages):
            self._page(number,page)
        self._validate_links()

    def _walk(self,value,path,parent,inherited_page,depth):
        if depth>100 or len(self.nodes)>100000:
            fail('la estructura supera los límites de profundidad o tamaño.')
        value_raw=value
        value=obj(value)
        if isinstance(value,NullObject):
            return
        if isinstance(value,(list,tuple)):
            for i,child in enumerate(value):
                self._walk(child,path+(i,),parent,inherited_page,depth+1)
            return
        if isinstance(value,int):
            self._owner(inherited_page,_integer(value,'MCID'),parent)
            return
        if not isinstance(value,dict):
            fail('un elemento /K no es interpretable.')
        page=ref(value.get('/Pg')) or inherited_page
        kind=value.get('/Type')
        if kind=='/MCR' or '/MCID' in value:
            if value.get('/Stm') or value.get('/StmOwn'):
                fail('MCID dentro de un flujo externo; no se conserva todavía su asociación.')
            self._owner(page,_integer(value.get('/MCID'),'MCID'),parent)
        elif kind=='/OBJR':
            target=ref(value.get('/Obj'))
            if target not in self.annotations:
                fail('una referencia OBJR no apunta a una anotación de página verificable.')
            self.object_owners.append((target,parent))
        else:
            identity=ref(value_raw)
            if identity is None or identity in self.node_refs:
                fail('el árbol tiene elementos directos, repetidos o cíclicos.')
            if ref(value.get('/P'))!=parent or not isinstance(value.get('/S'),str):
                fail('el padre o tipo de un elemento estructural es incoherente.')
            self.node_refs[identity]=path
            self.nodes[path]=value
            self._walk(value.get('/K',[]),path+('K',),identity,page,depth+1)

    def _owner(self,page,mcid,parent):
        if page not in self.pages or parent not in self.node_refs:
            fail('un contenido no identifica una página y un padre válidos.')
        key=(self.pages[page],mcid)
        if key in self.owners:
            fail('MCID repetido en el árbol de una página.')
        self.owners[key]=self.node_refs[parent]

    def _page(self,number,page):
        ops=ContentStream(page.get_contents(),self.reader).operations
        marks={}
        stack=[]
        semantic_scopes=[]
        contexts=[]
        resources=obj(page.get('/Resources',{}))
        properties=obj(resources.get('/Properties',{}))
        for index,(args,operator) in enumerate(ops):
            if operator in (b'BMC',b'BDC'):
                if not args or args[0]=='/OC':
                    fail('contenido de capa u operador marcado no compatible.')
                prop=args[1] if operator==b'BDC' and len(args)==2 else None
                resolved=obj(properties.get(prop)) if isinstance(prop,NameObject) else obj(prop)
                if prop is not None and not isinstance(resolved,dict):
                    fail('no se puede resolver una propiedad de contenido marcado.')
                resolved=resolved or {}
                mcid=resolved.get('/MCID')
                mark=None
                if mcid is not None:
                    mcid=_integer(mcid,'MCID')
                    if mcid in marks:
                        fail(f'MCID {mcid} repetido en la página {number+1}.')
                    mark=Mark(mcid,args[0],prop,resolved,index)
                    mark.nested_actual=any(semantic_scopes)
                    for _,ancestor in stack:
                        if ancestor:
                            ancestor.nested_actual=True
                            mark.nested_actual=True
                    marks[mcid]=mark
                else:
                    for _,ancestor in stack:
                        if ancestor:
                            ancestor.nested_actual=True
                stack.append((args[0],mark))
                # Even property-free BMC wrappers can change semantics, e.g.
                # /ReversedChars. Reconstruction must not detach their scope.
                semantic_scopes.append(mark is None or args[0]=='/Artifact')
            context=next((mark.mcid for _,mark in reversed(stack) if mark),None)
            artifact=any(tag=='/Artifact' for tag,_ in stack)
            contexts.append(context)
            if operator in SHOW and _has_string(args) and context is None and not artifact:
                fail(f'hay texto sin etiqueta ni marca de artefacto en la página {number+1}.')
            if operator in PAINT and context is not None:
                marks[context].paints=True
            if operator==b'EMC':
                if not stack:
                    fail('hay un cierre EMC sin apertura.')
                _,mark=stack.pop()
                semantic_scopes.pop()
                if mark:
                    mark.end=index
        if stack:
            fail('hay contenido marcado sin cerrar.')
        if marks:
            key=_integer(page.get('/StructParents'),'StructParents de página')
            if key in self.page_parent_keys:
                fail('dos páginas comparten una clave StructParents.')
            self.page_parent_keys[key]=number
        self.operations.append(ops)
        self.marks.append(marks)
        self.contexts.append(contexts)

    def _validate_links(self):
        for page,marks in enumerate(self.marks):
            key=obj(self.reader.pages[page].get('/StructParents'))
            array=self.parents.get(key,[])
            if marks and not isinstance(array,(list,tuple)):
                fail('ParentTree de página no es una matriz de elementos.')
            for mcid in marks:
                owner=self.owners.get((page,mcid))
                if owner is None or mcid>=len(array) or self.node_refs.get(ref(array[mcid]))!=owner:
                    fail(f'MCID {mcid} de página {page+1} no coincide con ParentTree y /K.')
            if isinstance(array,(list,tuple)):
                for mcid,item in enumerate(array):
                    if not isinstance(obj(item),NullObject) and mcid not in marks:
                        fail('ParentTree conserva un MCID sin contenido.')
        if any(mcid not in self.marks[page] for page,mcid in self.owners):
            fail('el árbol referencia contenido marcado que no existe.')
        used=set(self.page_parent_keys)
        for target,parent in self.object_owners:
            page,index=self.annotations[target]
            annotation=obj(obj(self.reader.pages[page].get('/Annots',[]))[index])
            key=_integer(annotation.get('/StructParent'),'StructParent de anotación')
            if key in used or ref(self.parents.get(key))!=parent:
                fail('la asociación OBJR / StructParent de una anotación es incoherente.')
            used.add(key)
        if set(self.parents)-used:
            fail('ParentTree contiene asociaciones no verificables.')

    def semantic(self):
        def canonical(value,seen=None):
            seen=set() if seen is None else seen
            identity=ref(value)
            if isinstance(value,IndirectObject):
                if identity in self.pages:return ('page',self.pages[identity])
                if identity in self.annotations:return ('annotation',self.annotations[identity])
                if identity in self.node_refs:return ('structure',self.node_refs[identity])
                if identity in seen:fail('una propiedad accesible contiene ciclos no verificables.')
                seen=seen|{identity}
                value=obj(value)
            if isinstance(value,dict):
                return {str(k):canonical(v,seen) for k,v in value.items()}
            if isinstance(value,(list,tuple)):return tuple(canonical(v,seen) for v in value)
            if isinstance(value,bytes):return ('bytes',value.hex())
            if isinstance(value,(str,int,float)) or value is None:return value
            if isinstance(value,NullObject):return None
            if type(value).__name__=='BooleanObject':return value.value
            return str(value)
        return {'tree':canonical(dict(self.tree)),
                'nodes':{path:canonical(dict(node)) for path,node in self.nodes.items()},
                'catalog':{k:canonical(self.root.get(k)) for k in ('/MarkInfo','/Lang','/ViewerPreferences')},
                'pages':[(p.get('/StructParents'),p.get('/Tabs')) for p in self.reader.pages],
                'marks':[{mcid:(str(m.tag),canonical(dict(m.resolved))) for mcid,m in marks.items()} for marks in self.marks]}

    def glyph_contexts(self,page,model):
        """Probe only: color each show op to identify its MCID without decoding fonts.

        Text cursor advances, matrices and encodings are untouched. Probe bytes
        are never exported. Character count/text/origins must match the source.
        """
        markers={None:1}
        for mcid in self.marks[page]:markers[mcid]=len(markers)+1
        if len(markers)>65535:fail('demasiados grupos de contenido en una página.')
        ops=[]
        for (args,operator),mcid in zip(self.operations[page],self.contexts[page]):
            if operator in SHOW:
                value=markers[mcid]
                rgb=((value>>16)&255,(value>>8)&255,value&255)
                ops.append(([FloatObject(v/255) for v in rgb],b'rg'))
                ops.append(([FloatObject(v/255) for v in rgb],b'RG'))
            ops.append((args,operator))
        with fitz.open(stream=self.data,filetype='pdf') as doc:
            xref=doc.get_new_xref()
            doc.update_object(xref,'<<>>')
            doc.update_stream(xref,_stream(ops))
            doc[page].set_contents(xref)
            probed=[(chr(c[0]),c[2],s['color']) for s in doc[page].get_texttrace() for c in s['chars']]
        if len(probed)!=len(model.glyphs):fail('no se puede relacionar cada carácter con su etiqueta.')
        inverse={value:key for key,value in markers.items()}
        result={}
        for g,(text,point,color) in zip(model.glyphs,probed):
            if text!=g.text or any(abs(a-b)>.035 for a,b in zip(point,g.origin)) or len(color)!=3:
                fail('el sondeo de etiquetas no conserva la geometría del texto.')
            value=(round(color[0]*255)<<16)|(round(color[1]*255)<<8)|round(color[2]*255)
            if value not in inverse:fail('no se pudo identificar la etiqueta de un carácter.')
            result[g.id]=inverse[value]
        return result


def analyze(data):
    reader=PdfReader(BytesIO(data),strict=True)
    if not reader.trailer['/Root'].get('/StructTreeRoot'):
        return None
    return TaggedStructure(data)


def require_untagged(data,operation):
    try:
        with fitz.open(stream=data,filetype='pdf') as doc:
            if doc.is_encrypted or doc.needs_pass or (doc.metadata or {}).get('encryption'):
                return  # Existing preflight handles permissions and passwords.
        reader=PdfReader(BytesIO(data))
        tagged=bool(reader.trailer['/Root'].get('/StructTreeRoot'))
    except Exception as exc:
        raise EditError('No se puede verificar la estructura del archivo PDF.') from exc
    if tagged:
        fail(operation+' necesita asignar o remapear etiquetas nuevas; esta operación todavía no está habilitada. Sí puedes editar texto existente compatible.')


def assert_structure(before,after,expected=None):
    a=analyze(before)
    b=analyze(after)
    if (a is None)!=(b is None):fail('se perdió o añadió una estructura de accesibilidad.')
    if a is not None and (expected if expected is not None else a.semantic())!=b.semantic():
        fail('la validación detectó cambios ajenos en etiquetas, relaciones, orden o propiedades accesibles.')
    return b


class TaggedEdit:
    def __init__(self,structure,page,model,selected,planned,original_selection,rewriting):
        self.structure=structure
        self.page=page
        self.model=model
        self.contexts=structure.glyph_contexts(page,model)
        owners={self.contexts[g.id] for g in original_selection}
        if None in owners:
            fail('la selección contiene un artefacto; elige contenido con una etiqueta propia.')
        if rewriting and len(owners)!=1:
            fail('la sustitución abarca varias etiquetas. Selecciona un fragmento de una sola etiqueta para conservar su significado.')
        new_owner=next(iter(owners))
        affected={self.contexts[g.id] for g in selected}
        if None in affected:fail('el ajuste de línea incluye un artefacto y no puede asociarse a una etiqueta.')
        self.affected=affected
        self.selected=[g for g in model.glyphs if self.contexts[g.id] in affected]
        removed={g.id for g in selected}
        # Neighbours in a justified line retain their original ids and owners.
        replacement={}
        for g in planned:
            owner=self.contexts.get(g.id,new_owner)
            replacement.setdefault(owner,[]).append(g)
        self.planned={}
        self.original={}
        for mcid in affected:
            mark=structure.marks[page][mcid]
            if mark.paints or mark.nested_actual:
                fail('la etiqueta combina texto con gráficos o propiedades semánticas anidadas; no puede reconstruirse de forma inequívoca.')
            original=[g for g in model.glyphs if self.contexts[g.id]==mcid]
            chosen=[i for i,g in enumerate(original) if g.id in removed]
            if not chosen or chosen!=list(range(min(chosen),max(chosen)+1)):
                fail('la edición afecta fragmentos separados dentro de una etiqueta.')
            actual=original[:min(chosen)]+replacement.get(mcid,[])+original[max(chosen)+1:]
            self.original[mcid]=original
            self.planned[mcid]=actual
        self.expected=copy.deepcopy(structure.semantic())
        self.actual_updates={}
        self.marker_updates={}
        for mcid in affected:
            old=''.join(g.text for g in self.original[mcid])
            new=''.join(g.text for g in self.planned[mcid])
            properties=structure.marks[page][mcid].resolved
            if '/ActualText' in properties and old!=new:
                if str(properties['/ActualText'])!=old:
                    fail('ActualText difiere del texto visible; necesita revisión semántica manual antes de sustituirlo.')
                self.marker_updates[mcid]=new
                self.expected['marks'][page][mcid][1]['/ActualText']=new
            if '/E' in properties and old!=new:
                fail('la etiqueta contiene una expansión /E que requiere actualización semántica manual.')
            if properties.get('/Alt') and old!=new:
                fail('la etiqueta contiene texto alternativo /Alt que requiere revisión semántica manual.')
        for path,node in structure.nodes.items():
            contents=[key for key,owner in structure.owners.items() if owner[:len(path)]==path]
            relevant=[mcid for p,mcid in contents if p==page and mcid in affected]
            if not relevant:continue
            if node.get('/A') or node.get('/C'):
                fail('el elemento tiene atributos de disposición o clases que todavía no se actualizan al editar.')
            if node.get('/E'):
                fail('el elemento contiene una expansión semántica que requiere revisión manual.')
            if node.get('/Alt') and any(
                ''.join(g.text for g in self.original[mcid]) != ''.join(g.text for g in self.planned[mcid])
                for mcid in relevant
            ):
                fail('el elemento contiene texto alternativo /Alt que requiere revisión semántica manual.')
            if '/ActualText' in node:
                if any(p!=page or mcid not in affected for p,mcid in contents):
                    fail('ActualText abarca contenido fuera del fragmento editado; necesita revisión semántica manual.')
                old=''.join(''.join(g.text for g in self.original[mcid]) for p,mcid in contents)
                new=''.join(''.join(g.text for g in self.planned[mcid]) for p,mcid in contents)
                if old!=new:
                    if str(node['/ActualText'])!=old:
                        fail('ActualText del elemento difiere del texto visible; no se sustituye automáticamente.')
                    self.actual_updates[path]=new
                    self.expected['nodes'][path]['/ActualText']=new

    def insert(self,erased,resolved,reproduction=False):
        from .engine import _insert,full_write
        current=analyze(erased)
        marks=current.marks[self.page]
        skipped={index for mcid in self.affected for index in (marks[mcid].start,marks[mcid].end)}
        operations=[operation for i,operation in enumerate(current.operations[self.page]) if i not in skipped]
        with fitz.open(stream=erased,filetype='pdf') as doc:
            page=doc[self.page]
            # A named property may contain the old ActualText. Drop its unused
            # name from a private Resources copy, never from shared resources.
            # The replacement carries an inline copy with the updated value.
            remaining_names={args[1] for args,op in operations if op==b'BDC' and len(args)==2 and isinstance(args[1],NameObject)}
            obsolete={marks[mcid].properties for mcid in self.affected
                      if isinstance(marks[mcid].properties,NameObject)}-remaining_names
            if obsolete:
                resources=DictionaryObject(dict(obj(current.reader.pages[self.page].get('/Resources',{}))))
                properties=DictionaryObject(dict(obj(resources.get('/Properties',{}))))
                for name in obsolete:
                    properties.pop(name,None)
                resources[NameObject('/Properties')]=properties
                buffer=BytesIO()
                resources.write_to_stream(buffer)
                resource_xref=doc.get_new_xref()
                doc.update_object(resource_xref,buffer.getvalue().decode('latin1'))
                doc.xref_set_key(page.xref,'Resources',f'{resource_xref} 0 R')
                page=doc.reload_page(page)
            # MuPDF redaction can add an empty /Alt to the affected structure
            # element. Restore the original value exactly, rather than ignoring
            # that difference in the final semantic validator.
            for path,node in current.nodes.items():
                original=self.structure.nodes[path]
                if node.get('/Alt')!=original.get('/Alt'):
                    restored=DictionaryObject(dict(node))
                    if '/Alt' in original:
                        restored[NameObject('/Alt')]=TextStringObject(str(original['/Alt']))
                    else:
                        restored.pop('/Alt',None)
                    buffer=BytesIO()
                    restored.write_to_stream(buffer)
                    doc.update_object(ref(node)[0],buffer.getvalue().decode('latin1'))
            xref=doc.get_new_xref()
            doc.update_object(xref,'<<>>')
            doc.update_stream(xref,_stream(operations))
            page.set_contents(xref)
            for mcid in sorted(self.affected):
                before=set(page.get_contents())
                _insert(page,self.original[mcid] if reproduction else self.planned[mcid],resolved)
                added=[i for i in page.get_contents() if i not in before]
                # Empty text still has a valid, empty marked-content item.
                props=DictionaryObject(dict(marks[mcid].resolved))
                if not reproduction and mcid in self.marker_updates:
                    props[NameObject('/ActualText')]=TextStringObject(self.marker_updates[mcid])
                prefix=_stream([([marks[mcid].tag,props],b'BDC')])
                content=prefix+b'\n'+b'\n'.join(doc.xref_stream(i) for i in added)+b'\nEMC\n'
                group=doc.get_new_xref()
                doc.update_object(group,'<<>>')
                doc.update_stream(group,content)
                kept=[i for i in page.get_contents() if i not in set(added)]+[group]
                doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{i} 0 R' for i in kept)+']')
            if not reproduction:
                for path,text in self.actual_updates.items():
                    doc.xref_set_key(ref(current.nodes[path])[0],'ActualText',fitz.get_pdf_str(text))
            return full_write(doc)

    def validate(self,after):
        from .engine import extract_page
        result=assert_structure(self.structure.data,after,self.expected)
        with fitz.open(stream=after,filetype='pdf') as doc,fitz.open(stream=self.structure.data,filetype='pdf') as source:
            for page in range(doc.page_count):
                model=extract_page(doc,page)
                before=self.model if page==self.page else extract_page(source,page)
                contexts=result.glyph_contexts(page,model)
                old_contexts=self.contexts if page==self.page else self.structure.glyph_contexts(page,before)
                for mcid in self.structure.marks[page]:
                    actual=''.join(g.text for g in model.glyphs if contexts[g.id]==mcid)
                    glyphs=self.planned[mcid] if page==self.page and mcid in self.affected else [g for g in before.glyphs if old_contexts[g.id]==mcid]
                    if actual!=''.join(g.text for g in glyphs):
                        fail('el texto lógico de una etiqueta no coincide con la edición solicitada.')
        return {'verified':True,'mcids':sorted(self.affected),'structure_preserved':True,
                'logical_text_verified':True,'actual_text_updates':len(self.actual_updates)+len(self.marker_updates),
                'scope':'Preservación de estructura y relaciones verificadas; no certificación PDF/UA.'}
