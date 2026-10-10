# Extrae la tabla UVR (Arts. 1-16) del texto del Manual ISS 2001 (Acuerdo 256 de 2001).
# Uso: python3 scripts/extraer_iss2001.py <texto_del_manual.txt> <salida.csv>
# Cada fila del manual tiene el formato: <codigo ISS> [PB] <codigo CUPS> <descripcion> <UVR>
import re, csv, sys, collections
txt = open(sys.argv[1], encoding='utf-8').read()
txt = txt.replace('\\[', '[').replace('\\]', ']').replace('\\*','*')
txt = re.sub(r'POR EL CUAL SE APRUEBA EL "MANUAL DE TARIFAS".*?REF\. CODIGO DESCRIPCION UVR', ' ', txt)
txt = re.sub(r'\s+', ' ', txt)
txt = re.sub(r'ACUERDO No\. 256 DE 2\.001 \d+', ' ', txt)
txt = re.sub(r'\( ?19 de Diciembre ?\)', ' ', txt)
# keep the section "especialidad" from ARTICULO headers
arts = [(m.start(), m.group(1), m.group(2).strip()) for m in re.finditer(r'ARTICULO (\d+)\. Se\S+ para las intervenciones quir[uú]rgicas y procedimientos en (?:la especialidad de|las especialidades de) (.*?),', txt)]
start = re.compile(r'(?<![\w(])([A-Z]?\d{5,6}) (?:PB )?([A-Z]\d{5}|\d{6}) ')
ms = list(start.finditer(txt))
notes = re.compile(r'\b(APLICA:|TARIFA:|INCLUYE:|EXCLUYE:|NOTA|ARTICULO \d|PARAGRAFO|PARÁGRAFO)')
rows, bad = [], []
for i, m in enumerate(ms):
    if m.start() < arts[0][0]: continue
    end = ms[i+1].start() if i+1 < len(ms) else len(txt)
    seg = txt[m.end():end]
    n = notes.search(seg)
    body = seg[:n.start()] if n else seg
    body = re.sub(r'\(\d+\)', ' ', body)
    nums = list(re.finditer(r'(?<![\w\-/.,])(\d{1,3}(?:\.\d{3})+|\d{1,4})(?![\w\-/,]|\.\d)', body))
    art = [a for a in arts if a[0] < m.start()][-1]
    if not nums: bad.append((m.group(1), m.group(2), seg[:150])); continue
    u = nums[-1]
    desc = body[:u.start()].strip()
    tail = body[u.end():].strip()
    rows.append(dict(articulo=art[1], especialidad=art[2], codigo_iss=m.group(1), codigo_cups=m.group(2),
                     descripcion=desc, uvr=int(u.group(1).replace('.','')), resto=tail))
w = csv.DictWriter(open(sys.argv[2],'w',newline='',encoding='utf-8'), fieldnames=['articulo','especialidad','codigo_iss','codigo_cups','descripcion','uvr'])
w.writeheader()
for r in rows: w.writerow({k:r[k] for k in w.fieldnames})
print('filas', len(rows), 'sin UVR', len(bad))
print('por articulo', collections.Counter(r['articulo'] for r in rows))
uv = sorted(r['uvr'] for r in rows); print('uvr min/max', uv[0], uv[-1])
dup = collections.Counter(r['codigo_cups'] for r in rows); print('cups duplicados', sum(1 for v in dup.values() if v>1))
print('--- sin UVR'); [print(b) for b in bad[:15]]
print('--- tails sospechosos (texto con dígitos tras UVR)')
for r in rows:
    if re.search(r'\d', r['resto']): print(r['codigo_cups'], r['uvr'], '|', r['resto'][:100])
