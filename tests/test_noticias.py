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
