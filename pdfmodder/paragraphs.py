"""Composición local: líneas explícitas, párrafos y ajuste sin tocar otras celdas."""
import math
from .model import EditError


def layout_lines(text,measure,width,reflow,line_height,paragraph_gap=0.):
    if not math.isfinite(line_height) or line_height<=0:
        raise EditError('El interlineado debe ser un número positivo.')
    if not math.isfinite(paragraph_gap) or paragraph_gap<0:
        raise EditError('La separación entre párrafos no puede ser negativa.')
    result=[]
    offset=0.
    for paragraph_index,paragraph in enumerate(text.split('\n\n')):
        if paragraph_index:
            offset+=line_height+paragraph_gap
        for hard_line in paragraph.split('\n'):
            wrapped=[]
            if reflow:
                line=''
                for word in hard_line.split(' '):
                    candidate=line+' '+word if line else word
                    if line and measure(candidate)>width+.035:
                        wrapped.append(line)
                        line=word
                    else:line=candidate
                wrapped.append(line)
            else:wrapped=[hard_line]
            for line in wrapped:
                if measure(line)>width+.035:
                    raise EditError('El texto supera el espacio disponible. Amplía el área o cambia el formato manualmente.')
                result.append((line,offset))
                offset+=line_height
    return result
