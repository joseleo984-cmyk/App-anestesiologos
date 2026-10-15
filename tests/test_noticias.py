"""Noticias de anestesia: lectura de RSS/Atom/PubMed, resumen con IA (simulado), temas, leídas y favoritas."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, extraccion, main, noticias
from tests.test_api import cliente  # noqa: F401  (fixture)

HOY = datetime.now(timezone.utc)
RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Revista de prueba</title>
<item><title>Sugammadex vs neostigmine: a randomized trial</title><link>https://ejemplo.org/a1</link>
<guid>a1</guid><pubDate>{HOY:%a, %d %b %Y %H:%M:%S +0000}</pubDate>
<description>&lt;p&gt;Residual &lt;b&gt;blockade&lt;/b&gt; was lower.&lt;/p&gt;</description></item>
<item><title>Erratum</title><link>https://ejemplo.org/a2</link><guid>a2</guid></item>
<item><title>Old paper</title><link>https://ejemplo.org/a3</link><guid>a3</guid>
<pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item>
</channel></rss>""".encode()
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Sociedad</title>
<entry><title>Nueva guia de via aerea dificil</title><id>tag:x,2026:1</id>
<link rel="alternate" href="https://sociedad.org/guia"/><link rel="self" href="https://sociedad.org/self"/>
<updated>2026-10-10T12:00:00Z</updated><summary>Recomendaciones actualizadas.</summary></entry></feed>"""
RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item rdf:about="https://revista.co/art/9"><title>Bloqueo del plano erector</title>
<link>https://revista.co/art/9</link><dc:date>2026-10-01</dc:date><description>Estudio local.</description></item>
</rdf:RDF>"""


def test_lee_rss_atom_y_rdf():
    r = noticias.leer_rss(RSS)
    assert [e["guid"] for e in r] == ["a1", "a2", "a3"]
    assert r[0]["contenido"] == "Residual blockade was lower." and r[0]["publicado_en"].year == HOY.year
    a = noticias.leer_rss(ATOM)[0]
    assert a["enlace"] == "https://sociedad.org/guia" and a["guid"] == "tag:x,2026:1" and a["publicado_en"].day == 10
    d = noticias.leer_rss(RDF)[0]
    assert d["titulo"] == "Bloqueo del plano erector" and d["publicado_en"].month == 10
    with pytest.raises(noticias.FuenteError):
        noticias.leer_rss(b"<html><body>no es rss")


@pytest.mark.parametrize("url,ok", [
    ("https://revista.org/rss", True), ("http://revista.org/rss", True), ("ftp://revista.org", False),
    ("http://localhost:8000/x", False), ("http://127.0.0.1/x", False), ("http://10.0.0.5/x", False),
    ("http://169.254.169.254/latest", False), ("revista.org/rss", False),
])
def test_solo_direcciones_publicas(url, ok):
    assert noticias.direccion_permitida(url) is ok


ESEARCH = b'{"esearchresult": {"idlist": ["111", "222"]}}'
EFETCH = b"""<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>111</PMID><Article><Journal><Title>Anesthesiology</Title></Journal>
<ArticleTitle>Remimazolam for <i>sedation</i>: a meta-analysis.</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Context.</AbstractText><AbstractText Label="RESULTS">Less hypotension.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Meta-Analysis</PublicationType></PublicationTypeList>
<ArticleDate><Year>2026</Year><Month>10</Month><Day>08</Day></ArticleDate></Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>222</PMID><Article><Journal><Title>BJA</Title></Journal>
<ArticleTitle>Spinal anaesthesia for caesarean delivery</ArticleTitle>
<Journal><JournalIssue><PubDate><Year>2026</Year><Month>Sep</Month></PubDate></JournalIssue></Journal>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""


def transporte(rutas: dict):
    def responder(req: httpx.Request):
        for parte, cuerpo in rutas.items():
            if parte in str(req.url):
                return httpx.Response(200, content=cuerpo)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(responder))


def test_lee_pubmed(monkeypatch):
    monkeypatch.setattr(noticias, "PAUSA_PUBMED", 0)
    with transporte({"esearch": ESEARCH, "efetch": EFETCH}) as c:
        arts = noticias.leer_pubmed(c, "anesthesia[MeSH] AND guideline[pt]")
    assert [a["guid"] for a in arts] == ["pmid:111", "pmid:222"]
    assert arts[0]["titulo"] == "Remimazolam for sedation: a meta-analysis."
    assert "RESULTS: Less hypotension." in arts[0]["contenido"] and "Meta-Analysis" in arts[0]["contenido"]
    assert arts[0]["enlace"] == "https://pubmed.ncbi.nlm.nih.gov/111/" and arts[0]["publicado_en"].day == 8
    assert arts[1]["publicado_en"].month == 9


def resumen_falso(lote):
    out = {}
    for n in lote:
        if n["titulo"] == "Erratum":
            out[n["noticia_id"]] = {"id": n["noticia_id"], "relevante": False, "tipo": "OTRO", "temas": [],
                                    "titulo_es": "Fe de erratas", "resumen_es": "-"}
        else:
            temas = ["VIA_AEREA", "GUIAS"] if "guia" in n["titulo"] else ["FARMACOLOGIA"]
            out[n["noticia_id"]] = {"id": n["noticia_id"], "relevante": True, "tipo": "ESTUDIO", "temas": temas,
                                    "titulo_es": "ES: " + n["titulo"], "resumen_es": "Resumen en español."}
    return out


@pytest.fixture
def admin(cliente, monkeypatch):
    from app.repositorio import conectar
    with conectar() as c:
        c.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE anestesiologo_id = 1")
        c.commit()
    monkeypatch.setattr(noticias, "_cliente", lambda: transporte({"rss.revista.org": RSS, "sociedad.org": ATOM}))
    monkeypatch.setattr(noticias, "resumir", resumen_falso)
    monkeypatch.setattr(noticias, "datos_infografia", lambda lote: {})
    return cliente


def test_flujo_completo(admin, conn):
    c = admin
    vacio = c.get("/api/noticias").json()
    assert vacio["noticias"] == [] and vacio["hay_fuentes"] is False

    r = c.post("/api/noticias/fuentes/probar", json={"nombre": "Revista", "tipo": "RSS", "url": "https://rss.revista.org/feed"})
    assert r.json()["encontradas"] == 3 and r.json()["ejemplos"][0]["titulo"].startswith("Sugammadex")
    assert c.post("/api/noticias/fuentes", json={"nombre": "Revista", "tipo": "RSS", "url": "http://localhost/x"}).status_code == 422
    for nombre, url in [("Revista", "https://rss.revista.org/feed"), ("Sociedad", "https://sociedad.org/atom")]:
        assert c.post("/api/noticias/fuentes", json={"nombre": nombre, "tipo": "RSS", "url": url}).status_code == 201

    # al abrir Noticias se revisan las fuentes en segundo plano; la siguiente consulta ya las trae resumidas
    assert c.get("/api/noticias").json()["revisando"] is True
    d = c.get("/api/noticias").json()
    assert d["revisando"] is False and d["sin_leer"] == 2
    titulos = [n["titulo_es"] for n in d["noticias"]]
    assert titulos == ["ES: Sugammadex vs neostigmine: a randomized trial", "ES: Nueva guia de via aerea dificil"]
    # la fe de erratas se descartó, la vieja no se trajo y el contenido original no se guarda
    estados = {r["titulo"]: r["estado"] for r in conn.execute("SELECT titulo, estado FROM noticia")}
    assert estados == {"Sugammadex vs neostigmine: a randomized trial": "LISTA", "Erratum": "DESCARTADA",
                       "Nueva guia de via aerea dificil": "LISTA"}
    assert conn.execute("SELECT count(*) AS n FROM noticia WHERE contenido IS NOT NULL").fetchone()["n"] == 0

    # temas propios: solo vía aérea
    assert c.put("/api/noticias/temas", json={"temas": ["VIA_AEREA"]}).status_code == 200
    assert c.put("/api/noticias/temas", json={"temas": ["INVENTADO"]}).status_code == 422
    d = c.get("/api/noticias").json()
    assert [n["titulo_es"] for n in d["noticias"]] == ["ES: Nueva guia de via aerea dificil"] and d["mis_temas"] == ["VIA_AEREA"]
    guia = d["noticias"][0]["noticia_id"]

    # favorita y leída
    assert c.put(f"/api/noticias/{guia}/favorita", json={"favorita": True}).json()["favorita"] is True
    assert c.post(f"/api/noticias/{guia}/leida").status_code == 204
    assert c.get("/api/noticias/sin-leer").json()["sin_leer"] == 0
    assert c.get("/api/noticias").json()["noticias"] == []
    assert [n["noticia_id"] for n in c.get("/api/noticias", params={"ver": "anteriores"}).json()["noticias"]] == [guia]
    assert [n["noticia_id"] for n in c.get("/api/noticias", params={"ver": "favoritas"}).json()["noticias"]] == [guia]
    assert c.post(f"/api/noticias/{guia}/leida", params={"leida": "false"}).status_code == 204
    assert c.get("/api/noticias/sin-leer").json()["sin_leer"] == 1

    # todos los temas otra vez, y marcar todo como leído
    c.put("/api/noticias/temas", json={"temas": []})
    assert c.get("/api/noticias/sin-leer").json()["sin_leer"] == 2
    assert c.post("/api/noticias/leer-todo").status_code == 204
    assert c.get("/api/noticias/sin-leer").json()["sin_leer"] == 0
    # lo que llegue después sí aparece como nuevo
    conn.execute("UPDATE noticia SET listo_en = now() + interval '1 minute' WHERE titulo LIKE 'Sugammadex%'")
    conn.commit()
    assert c.get("/api/noticias/sin-leer").json()["sin_leer"] == 1

    # otro anestesiólogo tiene sus propias leídas y no administra fuentes
    conn.execute("INSERT INTO anestesiologo (nombre, email) VALUES ('Otro', 'otro@x.co')")
    conn.commit()
    otro = TestClient(main.app)
    otro.cookies.set(auth.COOKIE, auth.crear_sesion(2))
    assert otro.get("/api/noticias/sin-leer").json()["sin_leer"] == 2
    assert otro.get("/api/noticias/fuentes").status_code == 403
    assert otro.post("/api/noticias/fuentes", json={"nombre": "X", "tipo": "PUBMED", "url": "anesthesia"}).status_code == 403

    fuentes = c.get("/api/noticias/fuentes").json()["fuentes"]
    assert {f["nombre"]: (f["noticias"], f["por_resumir"]) for f in fuentes} == {"Revista": (1, 0), "Sociedad": (1, 0)}


def test_fuente_caida_y_ia_que_falla(admin, conn, monkeypatch):
    conn.execute("INSERT INTO noticia_fuente (nombre, tipo, url) VALUES ('Caída', 'RSS', 'https://caida.org/rss'), "
                 "('Revista', 'RSS', 'https://rss.revista.org/feed')")
    conn.commit()

    def falla(lote):
        raise extraccion.ExtraccionError("sin servicio")
    monkeypatch.setattr(noticias, "resumir", falla)
    with noticias._cliente() as cli:
        r = noticias.revisar_fuentes(conn, cli)
    assert r["fuentes_con_error"] == 1 and r["nuevas"] == 2 and r["resumidas"] == 0
    assert conn.execute("SELECT ultimo_error FROM noticia_fuente WHERE nombre = 'Caída'").fetchone()["ultimo_error"]
    # quedan pendientes y se reintentan; después de 3 intentos se descartan
    for _ in range(3):
        conn.execute("UPDATE noticia SET intentos = intentos + 1")
    conn.commit()
    noticias.resumir_pendientes(conn)
    assert {r["estado"] for r in conn.execute("SELECT estado FROM noticia")} == {"DESCARTADA"}


def test_no_repite_la_misma_publicacion_de_dos_fuentes(admin, conn):
    conn.execute("INSERT INTO noticia_fuente (nombre, tipo, url) VALUES ('Revista', 'RSS', 'https://rss.revista.org/feed'), "
                 "('Copia', 'RSS', 'https://rss.revista.org/otra')")
    conn.commit()
    with noticias._cliente() as cli:
        r = noticias.revisar_fuentes(conn, cli)
    assert r["nuevas"] == 2  # Sugammadex y Erratum una sola vez (la vieja no entra)
    assert conn.execute("SELECT count(*) AS n FROM noticia").fetchone()["n"] == 2


def test_fuentes_iniciales_se_cargan_una_vez(db_url, conn):
    from app import inicio
    inicio.preparar_base_de_datos()
    fuentes = conn.execute("SELECT nombre, tipo FROM noticia_fuente ORDER BY fuente_id").fetchall()
    assert len(fuentes) == 10 and fuentes[1]["nombre"] == "Anesthesiology (ASA)"
    assert {f["tipo"] for f in fuentes} == {"PUBMED", "RSS"}
    # si el administrador quita una, no vuelve a aparecer al reiniciar
    conn.execute("DELETE FROM noticia_fuente WHERE nombre = 'Anaesthesia'")
    conn.commit()
    inicio.preparar_base_de_datos()
    assert conn.execute("SELECT count(*) AS n FROM noticia_fuente").fetchone()["n"] == 9


@pytest.mark.parametrize("texto,ingles", [
    ("Sugammadex versus neostigmine and postoperative pulmonary complications in patients", True),
    ("In 2,400 patients, sugammadex reduced complications from 12% to 9%.", True),
    ("Sugammadex frente a neostigmina y complicaciones pulmonares en pacientes", False),
    ("Ensayo en 2.400 pacientes: el sugammadex redujo las complicaciones del 12 % al 9 %.", False),
    ("Remimazolam", False),
])
def test_detecta_resumen_en_ingles(texto, ingles):
    assert noticias.parece_ingles(texto) is ingles


def test_resumenes_en_ingles_se_traducen(admin, conn, monkeypatch):
    conn.execute("INSERT INTO noticia_fuente (nombre, tipo, url) VALUES ('Revista', 'RSS', 'https://rss.revista.org/feed')")
    conn.execute("""INSERT INTO noticia (fuente_id, guid, titulo, estado, titulo_es, resumen_es, temas, listo_en) VALUES
        (1, 'x1', 'Trial A', 'LISTA', 'Sugammadex and pulmonary complications', 'In 2,400 patients the rate was lower with sugammadex.', '{GENERAL}', now()),
        (1, 'x2', 'Trial B', 'LISTA', 'Guía de vía aérea', 'La sociedad actualiza el algoritmo de la vía aérea difícil.', '{GENERAL}', now())""")
    conn.commit()
    pedidas = []

    def traducir_falso(lote):
        pedidas.extend(n["noticia_id"] for n in lote)
        return {n["noticia_id"]: {"id": n["noticia_id"], "titulo_es": "Sugammadex y complicaciones pulmonares",
                                  "resumen_es": "En 2.400 pacientes la tasa fue menor con sugammadex."} for n in lote}
    monkeypatch.setattr(noticias, "traducir", traducir_falso)
    assert noticias.resumir_pendientes(conn) == 0
    filas = {r["guid"]: r["titulo_es"] for r in conn.execute("SELECT guid, titulo_es FROM noticia")}
    assert filas == {"x1": "Sugammadex y complicaciones pulmonares", "x2": "Guía de vía aérea"}
    assert len(pedidas) == 1  # solo la que estaba en inglés


def test_la_conexion_se_cierra_antes_de_la_tarea_en_segundo_plano(cliente, monkeypatch):
    """Si la consulta dejara su transacción abierta mientras se resumen noticias (minutos), bloquearía tablas
    y la versión nueva de la app no podría arrancar."""
    import psycopg
    from tests.conftest import TEST_DATABASE_URL
    vistas = []

    def tarea():
        with psycopg.connect(TEST_DATABASE_URL) as c:
            vistas.append(c.execute(
                """SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()
                   AND state = 'idle in transaction' AND pid <> pg_backend_pid()""").fetchone()[0])
    monkeypatch.setattr(noticias, "revisar_en_segundo_plano", tarea)
    assert cliente.get("/api/noticias").status_code == 200
    assert vistas == [0]


def test_historias_y_boletin(admin, conn, monkeypatch):
    def con_infografia(lote):
        out = resumen_falso(lote)
        for n in lote:
            if "Sugammadex" in n["titulo"]:
                out[n["noticia_id"]].update(relevancia=5, cifra="−33 %", cifra_etiqueta="complicaciones pulmonares",
                                            pacientes=1200, conclusion="Menos complicaciones con sugammadex.",
                                            diseno="ECA", poblacion="Adultos", intervencion="Sugammadex",
                                            comparador="Neostigmina", evento="complicaciones", grupo_a="Sugammadex",
                                            valor_a=8, grupo_b="Neostigmina", valor_b=12)
            elif "guia" in n["titulo"]:
                out[n["noticia_id"]].update(tipo="GUIA", relevancia=2, cifra=None, cifra_etiqueta="sobra",
                                            pacientes=0, conclusion="Nueva guía.", diseno="INVENTADO",
                                            grupo_a="A", valor_a=150, grupo_b="B", valor_b=3)
        return out
    monkeypatch.setattr(noticias, "resumir", con_infografia)
    c = admin
    for nombre, url in [("Revista", "https://rss.revista.org/feed"), ("Sociedad", "https://sociedad.org/atom")]:
        c.post("/api/noticias/fuentes", json={"nombre": nombre, "tipo": "RSS", "url": url})
    c.get("/api/noticias")  # revisa en segundo plano

    h = c.get("/api/noticias/historias").json()["historias"]
    assert [n["cifra"] for n in h] == ["−33 %"]                 # la guía tiene relevancia 2: no es historia
    assert h[0]["pacientes"] == 1200 and h[0]["conclusion"].startswith("Menos")
    assert (h[0]["diseno"], h[0]["valor_a"], h[0]["grupo_b"]) == ("ECA", 8, "Neostigmina")
    guia = conn.execute("SELECT cifra_etiqueta, pacientes, diseno, valor_a, grupo_a FROM noticia WHERE titulo LIKE 'Nueva guia%'").fetchone()
    # sin cifra no hay etiqueta; 0 pacientes = null; diseño inválido y un porcentaje imposible no se guardan
    assert guia == {"cifra_etiqueta": None, "pacientes": None, "diseno": None, "valor_a": None, "grupo_a": None}

    # por defecto, la semana completa anterior (el boletín sale los lunes)
    from datetime import date, timedelta
    assert c.get("/api/noticias/boletin").json()["hasta"] < str(date.today() - timedelta(days=date.today().weekday()))
    b = c.get("/api/noticias/boletin", params={"semana": str(date.today())}).json()
    assert b["total"] == 2 and b["sin_leer"] == 2 and b["en_curso"] is True and b["alertas"] == []
    assert [n["cifra"] for n in b["destacadas"]] == ["−33 %", None]
    assert {t["clave"]: t["n"] for t in b["por_tema"]} == {"FARMACOLOGIA": 1, "VIA_AEREA": 1, "GUIAS": 1}
    # leída: sale de las historias
    c.post(f"/api/noticias/{h[0]['noticia_id']}/leida")
    assert c.get("/api/noticias/historias").json()["historias"] == []
    # semana sin noticias
    vacia = c.get("/api/noticias/boletin", params={"semana": "2020-01-08"}).json()
    assert vacia["total"] == 0 and vacia["desde"] == "2020-01-06" and vacia["siguiente"] is not None


def test_completa_infografia_de_noticias_viejas(admin, conn, monkeypatch):
    c = admin
    c.post("/api/noticias/fuentes", json={"nombre": "Revista", "tipo": "RSS", "url": "https://rss.revista.org/feed"})
    c.get("/api/noticias")
    assert conn.execute("SELECT count(*) AS n FROM noticia WHERE estado = 'LISTA' AND conclusion IS NULL").fetchone()["n"] == 1
    monkeypatch.setattr(noticias, "datos_infografia", lambda lote: {n["noticia_id"]: {
        "id": n["noticia_id"], "relevancia": 9, "cifra": "8 %", "cifra_etiqueta": "x", "pacientes": None,
        "conclusion": "Conclusión.", "diseno": "COHORTE"} for n in lote})
    assert noticias.completar_infografia(conn) == 1
    assert conn.execute("SELECT relevancia, cifra FROM noticia WHERE estado = 'LISTA'").fetchone() == {"relevancia": 5, "cifra": "8 %"}
