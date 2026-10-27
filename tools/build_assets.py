"""Gera o card único do perfil da organização mandasTeam e a prancha de tokens do BRAND.md.

    python tools/build_assets.py                              # escreve assets/*.svg
    python tools/build_assets.py --profile ../mandasTeam-.github   # e o profile/README.md do .github

Tokens, fontes e motivos seguem o BRAND.md. Mudar texto ou cor = editar CONFIG e rodar de novo;
nunca edite os SVGs à mão.

Figura: Hendrick Goltzius, segundo Polidoro da Caravaggio, "Vulcan" (c. 1592), National Gallery
of Art, CC0. Recortada do nicho em tools/art/vulcan.png (cinza + alfa). Original:
https://commons.wikimedia.org/wiki/File:Hendrik_Goltzius_after_Polidoro_da_Caravaggio,_Vulcan,_probably_1592,_NGA_60689.jpg
"""
from __future__ import annotations

import argparse
import base64
import io
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fontTools.pens.svgPathPen import SVGPathPen  # noqa: E402
from fontTools.pens.transformPen import TransformPen  # noqa: E402
from svgkit import REDUCED_MOTION, Font, MissingGlyph, Theme, num, svg  # noqa: E402

FONTS = ROOT / "tools" / "fonts"
ART = ROOT / "tools" / "art" / "vulcan.png"
HEAD = (0.582, 0.107)     # centro da cabeça, relativo ao recorte
HAMMER = (0.055, 0.415)   # cabeça do martelo, relativo ao recorte

# ----------------------------------------------------------------------------- tokens (BRAND.md §2)
T = Theme(
    card="#FBF8F1",       # mármore: fundo
    line="#E3D6B8",       # veio: bordas e réguas finas
    text="#1A1712",       # tinta: títulos e texto principal
    soft="#4B4438",       # grafite: texto corrido
    muted="#6E6656",      # pó: apoio
    accent="#8A6417",     # ouro velho: rótulos e links (único ouro em texto)
    on_accent="#FBF8F1",
    extra={
        "pergaminho": "#F3ECDD",  # superfície secundária
        "ouro": "#C79A3A",        # raios, gravura, filetes (nunca texto)
        "brasa": "#E9CF8E",       # luz da gravura, fagulhas, texto sobre tinta
        "bronze": "#7A5716",      # sombra da gravura
    },
)
X = T.extra

CONFIG = {
    "name": ("mandas", "Team"),
    "handle": "github.com/mandasTeam",
    "kicker": "oficina de skills",
    "tagline": "Skills para agentes de código.",
    "about": [
        ("Cada skill ensina um trabalho completo ao agente, com scripts e referências. ", "r"),
        ("Hermes Agent", "a"), (", ", "r"), ("Claude Code", "a"),
        (" e qualquer agente que leia ", "r"), ("SKILL.md", "a"),
        (". Abertas, em português, sob licença MIT.", "r"),
    ],
    "skills": [
        ("I", "readme-designer",
         "README de perfil e de projeto no GitHub com design próprio em SVG, fatos conferidos e poucos tokens."),
        ("II", "product-owner",
         "Do escopo ao backlog no GitHub, com requisitos rastreáveis, decisões registradas e nada que nenhum requisito peça."),
        ("III", "skill-author",
         "Cria e revisa skills de agente: fluxo tirado da tarefa, gatilho certo e melhora medida contra o agente sem a skill."),
    ],
    "usage": ["clone o repo da skill",
              "copie skills/<nome>/ para as skills do agente",
              "peça a tarefa: o agente carrega a skill sozinho"],
    "terminal": ("~/.claude/skills", "$ ls", "readme-design/   product-owner/"),
    "plinth": "HEFESTO",
}


class Glyphs:
    """Texto em path com glifo reaproveitado: cada glifo vira um <path id> em <defs> e cada
    ocorrência um <use>. Corta o SVG a menos da metade frente a um path por letra."""

    def __init__(self) -> None:
        self.ids: dict[tuple[int, str], str] = {}
        self.paths: list[str] = []

    def _glyph(self, font: Font, name: str) -> str | None:
        key = (id(font), name)
        if key not in self.ids:
            pen = SVGPathPen(font.gs, ntos=lambda v: str(round(v)))
            font.gs[name].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
            d = pen.getCommands()
            self.ids[key] = f"g{len(self.ids)}" if d else ""
            if d:
                self.paths.append(f'<path id="{self.ids[key]}" d="{d}"/>')
        return self.ids[key] or None

    def text(self, font: Font, s: str, size: float, x: float, y: float, fill: str,
             anchor: str = "start", tracking: float = 0) -> str:
        x -= {"start": 0, "middle": font.width(s, size, tracking) / 2, "end": font.width(s, size, tracking)}[anchor]
        sc = size / font.upem
        infos, pos = font._shape(s)
        uses, cx = [], 0.0
        for info, p in zip(infos, pos):
            if info.codepoint == 0:
                raise MissingGlyph(f"{font.name} sem glifo em {s!r}")
            gid = self._glyph(font, font.order[info.codepoint])
            if gid:
                uses.append(f'<use href="#{gid}" x="{round(cx + p.x_offset)}" y="{round(-p.y_offset)}"/>')
            cx += p.x_advance + tracking / sc
        return f'<g transform="translate({num(x)},{num(y)}) scale({sc:.5f})" fill="{fill}">{"".join(uses)}</g>'

    def rich(self, segs: list[tuple[str, Font, float, str]], x: float, y: float, max_w: float, lh: float) -> list[str]:
        """Parágrafo com trechos de estilos diferentes; quebra só em espaço comum (NBSP segura)."""
        words: list[list[tuple[str, Font, float, str]]] = [[]]
        for t, f, sz, col in segs:
            parts = t.split(" ")
            for i, part in enumerate(parts):
                if i:
                    words.append([])
                if part:
                    words[-1].append((part.replace(" ", " "), f, sz, col))
        words = [w for w in words if w]
        out, cx, cy = [], 0.0, y
        for w in words:
            ww = sum(f.width(t, sz) for t, f, sz, _ in w)
            sp = w[0][1].width(" ", w[0][2])
            if cx and cx + sp + ww > max_w:
                cx, cy = 0.0, cy + lh
            elif cx:
                cx += sp
            for t, f, sz, col in w:
                out.append(self.text(f, t, sz, x + cx, cy, col))
                cx += f.width(t, sz)
        return out

    def defs(self) -> str:
        return "".join(self.paths)

W = 1200
G = None  # Glyphs do SVG em construção
RX = 6
INSET = 14


def fonts() -> dict[str, Font]:
    bs, gm = FONTS / "BigShoulders[opsz,wght].ttf", FONTS / "GeistMono[wght].ttf"
    return {"display": Font(bs, wght=800, opsz=72), "body": Font(gm, wght=400), "bold": Font(gm, wght=600)}


# ----------------------------------------------------------------------------- peças do tema
DEFS_GRAIN = ('<filter id="grain" x="0" y="0" width="100%" height="100%">'
              '<feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="4" stitchTiles="stitch"/>'
              '<feColorMatrix values="0 0 0 0 .48 0 0 0 0 .34 0 0 0 0 .09 0 0 0 .55 -.22"/></filter>')


def plate(w: int, h: int) -> list[str]:
    """Placa: mármore com grão de papel, borda veio e filete em ouro (a marca da chapa)."""
    return [f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="{RX}" fill="{T.card}" stroke="{T.line}" stroke-width="2"/>',
            f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="{RX}" filter="url(#grain)"/>',
            f'<rect x="{INSET}" y="{INSET}" width="{w - 2 * INSET}" height="{h - 2 * INSET}" fill="none" '
            f'stroke="{X["ouro"]}" stroke-width="1"/>']


def rays(cx: float, cy: float, r0: float, r1: tuple[float, float], n: int, seed: int,
         a0: float = 0, a1: float = 360, width: float = 1.1, color: str | None = None) -> str:
    """Motivo: a fagulha. Raios finos em feixes saindo de um ponto."""
    rnd = random.Random(seed)
    d = []
    for i in range(n):
        a = math.radians(a0 + (a1 - a0) * i / n)
        bundle = 0.5 + 0.5 * math.sin(i * 0.9) * math.cos(i * 0.23)
        ln = r1[0] + (r1[1] - r1[0]) * max(0.0, min(1.0, bundle + rnd.uniform(-0.15, 0.15)))
        d.append(f"M{num(cx + r0 * math.cos(a))},{num(cy + r0 * math.sin(a))}"
                 f"L{num(cx + (r0 + ln) * math.cos(a))},{num(cy + (r0 + ln) * math.sin(a))}")
    return (f'<path d="{"".join(d)}" stroke="{color or X["ouro"]}" stroke-width="{width}" '
            f'stroke-linecap="round" fill="none"/>')


def dither(w: int, h: int, px: int = 2, box: tuple[float, float, float, float] | None = None) -> str:
    """Estátua em ouro: dithering de 4 tons (transparente, brasa, ouro, bronze) sobre o recorte.
    `box` (x0, y0, x1, y1, relativo à figura) corta um trecho antes, como o busto do avatar."""
    gw, gh = w // px, h // px
    src = Image.open(ART).convert("LA")
    if box:
        sw, sh = src.size
        src = src.crop((round(box[0] * sw), round(box[1] * sh), round(box[2] * sw), round(box[3] * sh)))
    src = src.resize((gw, gh), Image.Resampling.LANCZOS)
    g, a = src.split()
    g = ImageOps.autocontrast(g, cutoff=1).point(lambda v: int(40 + v * 0.86))
    pal_cols = [T.card, X["brasa"], X["ouro"], X["bronze"]]
    pal = Image.new("P", (1, 1))
    pal.putpalette([int(c[i:i + 2], 16) for c in pal_cols for i in (1, 3, 5)] + [0] * (256 - 4) * 3)
    q = Image.merge("RGB", (g, g, g)).quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG)
    q.paste(0, mask=a.point(lambda v: 255 if v < 128 else 0))   # fora da figura = transparente
    buf = io.BytesIO()
    q.save(buf, "PNG", optimize=True, transparency=0, bits=2)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def sparks(cx: float, cy: float, seed: int) -> list[str]:
    """Fagulhas do martelo: pontos quadrados (o pixel do dithering) que piscam em tempos diferentes."""
    rnd = random.Random(seed)
    out = []
    for i in range(16):
        a = math.radians(rnd.uniform(150, 290))
        r = rnd.uniform(14, 78)
        s = rnd.choice((3, 4, 4, 6))
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        col = X["ouro"] if i % 3 else X["bronze"]
        out.append(f'<rect class="sp" style="animation-delay:{i * 0.37 % 2.6:.2f}s" x="{num(x)}" y="{num(y)}" '
                   f'width="{s}" height="{s}" fill="{col}"/>')
    return out


def terminal(x: float, y: float, w: float, f: dict[str, Font], lines: tuple[str, str, str]) -> list[str]:
    """Janela flutuante (vocabulário do site do Hermes) em tinta e pergaminho."""
    title, cmd, out = lines
    bar, h = 28, 92
    return [f'<rect x="{num(x + 6)}" y="{num(y + 6)}" width="{num(w)}" height="{h}" fill="{X["ouro"]}"/>',
            f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{h}" fill="{X["pergaminho"]}" stroke="{T.text}" stroke-width="1.5"/>',
            f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{bar}" fill="{T.text}"/>',
            G.text(f["body"], title, 15, x + 14, y + 19, fill=X["brasa"]),
            G.text(f["bold"], cmd, 17, x + 14, y + bar + 26, fill=T.accent),
            G.text(f["bold"], out, 17, x + 14, y + bar + 52, fill=T.text)]


def section_title(text: str, x: float, y: float, x_end: float, f: dict[str, Font]) -> list[str]:
    size = 56
    tw = f["display"].width(text, size)
    mid = y - f["display"].cap_height(size) / 2
    return [G.text(f["display"], text, size, x, y, fill=T.text),
            f'<line x1="{num(x + tw + 24)}" y1="{num(mid)}" x2="{num(x_end - 40)}" y2="{num(mid)}" stroke="{X["ouro"]}" stroke-width="1.5"/>',
            rays(x_end - 18, mid, 5, (8, 22), 26, 3, width=1.2)]


def skill_plate(x: float, y: float, w: float, h: float, numeral: str, name: str, desc: str,
                f: dict[str, Font], seed: int) -> list[str]:
    """Prancha de catálogo: cada skill é uma lâmina numerada (Pl. I, Pl. II), como num álbum de gravuras."""
    p = 32
    cid = f"cp{seed}"
    d = [f'<clipPath id="{cid}"><rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}"/></clipPath>',
         f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" fill="{X["pergaminho"]}" stroke="{T.line}" stroke-width="1.5"/>',
         f'<g clip-path="url(#{cid})" opacity=".9">{rays(x + w, y, 20, (40, 130), 44, seed, 90, 180)}</g>']
    d.append(G.text(f["display"], "Pl. " + numeral, 24, x + p, y + 50, fill=T.accent))
    d.append(G.text(f["body"], "mandasTeam/" + name, 15, x + p + f["display"].width("Pl. " + numeral, 24) + 16, y + 49, fill=T.muted))
    size = f["display"].fit(name, 66, w - 2 * p - 70)
    d.append(G.text(f["display"], name, size, x + p - 2, y + 120, fill=T.text))
    for i, ln in enumerate(f["body"].wrap(desc, 18, w - 2 * p)):
        d.append(G.text(f["body"], ln, 18, x + p, y + 164 + i * 27, fill=T.soft))
    cmd = f"$ git clone https://github.com/mandasTeam/{name}"
    cs = f["body"].fit(cmd, 15, w - 2 * p - 28, floor=12)
    by = y + h - p - 42
    d.append(f'<rect x="{num(x + p)}" y="{num(by)}" width="{num(w - 2 * p)}" height="42" fill="{T.text}"/>')
    d.append(G.text(f["body"], cmd, cs, x + p + 14, by + 21 + f["body"].cap_height(cs) / 2, fill=X["brasa"]))
    return d


# ----------------------------------------------------------------------------- o card único
def folio(c: dict, f: dict[str, Font]) -> str:
    global G
    G = Glyphs()
    x0 = 72
    sy = 968                                           # título do catálogo
    rows = (len(c["skills"]) + 1) // 2
    h = round(sy + 40 + rows * 330 + (rows - 1) * 24 + 62)
    # figura
    fh = 700
    fw = fh * Image.open(ART).width / Image.open(ART).height
    fx, fy = 708, 74
    hx, hy = fx + fw * HEAD[0], fy + fh * HEAD[1]
    mx, my = fx + fw * HAMMER[0], fy + fh * HAMMER[1]
    py = fy + fh - 6                                   # topo do plinto

    defs = [DEFS_GRAIN,
            f'<radialGradient id="fade" cx="{num(hx)}" cy="{num(hy)}" r="640" gradientUnits="userSpaceOnUse">'
            '<stop offset=".15" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
            f'<mask id="m"><rect width="{W}" height="{py}" fill="url(#fade)"/></mask>',
            f'<clipPath id="in"><rect x="{INSET}" y="76" width="{W - 2 * INSET}" height="{h - 76 - INSET}"/></clipPath>']
    d = [f'<defs>{"".join(defs)}</defs>'] + plate(W, h)

    # cabeçalho
    d.append(f'<line x1="{x0}" y1="76" x2="{W - x0}" y2="76" stroke="{X["ouro"]}" stroke-width="1"/>')
    d.append(G.text(f["bold"], "mandasTeam", 15, x0, 52, fill=T.text))
    d.append(G.text(f["body"], "/ " + c["kicker"], 15, x0 + f["bold"].width("mandasTeam", 15) + 10, 52, fill=T.muted))
    d.append(G.text(f["body"], c["handle"], 15, W - x0, 52, anchor="end", fill=T.accent))

    # sol da forja: auréola + raios saindo da cabeça, sumindo nas bordas
    d.append(f'<g clip-path="url(#in)" mask="url(#m)">'
             f'{rays(hx, hy, 104, (120, 620), 180, 7, width=1)}'
             f'<circle cx="{num(hx)}" cy="{num(hy)}" r="96" fill="none" stroke="{X["ouro"]}" stroke-width="1.5"/>'
             f'<circle cx="{num(hx)}" cy="{num(hy)}" r="104" fill="none" stroke="{X["ouro"]}" stroke-width=".8" stroke-dasharray="2 5"/>'
             f'</g>')

    # plinto
    pw = 380
    px = hx - pw / 2
    d.append(f'<rect x="{num(px)}" y="{num(py)}" width="{pw}" height="58" fill="{X["pergaminho"]}" stroke="{X["ouro"]}" stroke-width="1.5"/>')
    d.append(f'<rect x="{num(px - 16)}" y="{num(py + 58)}" width="{pw + 32}" height="12" fill="{X["ouro"]}"/>')
    d.append(G.text(f["display"], c["plinth"], 30, hx, py + 29 + f["display"].cap_height(30) / 2, anchor="middle", tracking=16, fill=T.accent))

    # estátua em ouro
    d.append(f'<image x="{num(fx)}" y="{fy}" width="{num(fw)}" height="{fh}" href="{dither(int(fw), fh, px=1)}" '
             f'style="image-rendering:pixelated"/>')
    d += sparks(mx - 6, my - 4, 5)

    # título
    big = 196
    d.append(G.text(f["display"], c["name"][0], big, x0 - 6, 286, fill=T.text))
    d.append(G.text(f["display"], c["name"][1], big, x0 - 6, 456, fill=T.text))
    d.append(G.text(f["bold"], c["tagline"], 26, x0, 528, fill=T.text))
    st = {"r": (f["body"], T.soft), "a": (f["bold"], T.accent)}
    d += G.rich([(t, st[s][0], 19, st[s][1]) for t, s in c["about"]], x0, 576, 560, 31)
    # como usar
    d.append(G.text(f["body"], "como usar", 15, x0, 734, fill=T.accent))
    for i, ln in enumerate(c["usage"]):
        d.append(G.text(f["bold"], str(i + 1), 17, x0, 770 + i * 31, fill=X["ouro"]))
        d.append(G.text(f["body"], ln, 17, x0 + 28, 770 + i * 31, fill=T.text))

    # janela flutuante sobre a estátua
    d += terminal(776, 604, 366, f, c["terminal"])

    # catálogo: duas pranchas por linha
    d += section_title("Skills", x0, sy, W - x0, f)
    pw2 = (W - 2 * x0 - 24) / 2
    for i, (numeral, name, desc) in enumerate(c["skills"]):
        d += skill_plate(x0 + (i % 2) * (pw2 + 24), sy + 40 + (i // 2) * (330 + 24), pw2, 330,
                         numeral, name, desc, f, 11 + i)

    style = ("@keyframes tw{0%,100%{opacity:0}45%{opacity:1}}"
             ".sp{opacity:0;animation:tw 2.6s ease-in-out infinite}" + REDUCED_MOTION + "@media (prefers-reduced-motion:reduce){.sp{opacity:.8}}")
    skills_txt = " ".join(f"Pl. {n}, {nm}: {ds}" for n, nm, ds in c["skills"])
    about_txt = "".join(t for t, _ in c["about"])
    usage_txt = " ".join(f"{i + 1}. {u}." for i, u in enumerate(c["usage"]))
    title = (f'{"".join(c["name"])}, {c["kicker"]}. {c["tagline"]} {about_txt} Como usar: {usage_txt} Skills: {skills_txt}').replace(" ", " ")
    d.append(f"<defs>{G.defs()}</defs>")
    return svg(W, h, title, "".join(d), style)


def tokens_card(f: dict[str, Font]) -> str:
    """Prancha de tokens para o BRAND.md: paleta e tipografia."""
    global G
    G = Glyphs()
    w, h = 1200, 560
    sw = [("mármore", T.card, "fundo"), ("pergaminho", X["pergaminho"], "superfície"),
          ("veio", T.line, "bordas"), ("brasa", X["brasa"], "luz, fagulha"), ("ouro", X["ouro"], "raios e gravura"),
          ("bronze", X["bronze"], "sombra da gravura"), ("ouro velho", T.accent, "rótulos e links"),
          ("tinta", T.text, "títulos e texto")]
    d = [f"<defs>{DEFS_GRAIN}</defs>"] + plate(w, h)
    d.append(G.text(f["body"], "paleta", 16, 48, 60, fill=T.accent))
    n = len(sw)
    bw = (w - 96 - (n - 1) * 12) / n
    for i, (nm, hexv, role) in enumerate(sw):
        x = 48 + i * (bw + 12)
        d.append(f'<rect x="{num(x)}" y="78" width="{num(bw)}" height="110" fill="{hexv}" stroke="{T.line}"/>')
        d.append(G.text(f["bold"], nm, 16, x, 216, fill=T.text))
        d.append(G.text(f["body"], hexv.upper(), 15, x, 240, fill=T.soft))
        for j, ln in enumerate(f["body"].wrap(role, 15, bw)):
            d.append(G.text(f["body"], ln, 15, x, 262 + j * 20, fill=T.muted))
    d.append(f'<line x1="48" y1="306" x2="1152" y2="306" stroke="{T.line}"/>')
    d.append(G.text(f["body"], "tipografia", 16, 48, 344, fill=T.accent))
    d.append(G.text(f["display"], "Forja de skills", 96, 44, 450, fill=T.text))
    d.append(G.text(f["body"], "Big Shoulders 800: títulos, nomes e números", 16, 48, 486, fill=T.muted))
    d.append(G.text(f["bold"], "Geist Mono 600: destaque", 20, 640, 402, fill=T.text))
    d.append(G.text(f["body"], "Geist Mono 400: texto corrido,", 20, 640, 438, fill=T.soft))
    d.append(G.text(f["body"], "rótulos, comandos e janelas", 20, 640, 466, fill=T.soft))
    d.append(G.text(f["body"], "$ git clone https://github.com/mandasTeam/…", 16, 640, 510, fill=T.accent))
    return svg(w, h, "Tokens da direção de arte do mandasTeam: paleta mármore, pergaminho, veio, brasa, ouro, "
                     "bronze, ouro velho e tinta; tipografia Big Shoulders 800 e Geist Mono.",
               "".join(d) + f"<defs>{G.defs()}</defs>")


# ----------------------------------------------------------------------------- avatar da organização
# Busto de Hefesto com o sol da forja, 500 x 500, sem texto: no GitHub ele aparece com 20 a 40 px
# e o nome já vem escrito ao lado. Estático (PNG não anima), então sem fagulhas. O PNG se sobe à mão em
# github.com/organizations/mandasTeam/settings/profile: a API não troca avatar de organização.
AV = 500                         # lado do avatar
AV_INSET = 18                    # filete de ouro (a marca da chapa), na escala do avatar
AV_BOX = (0.08, 0.0, 1.0, 0.36)  # busto: cabeça e peito, sem corte reto dentro da chapa
AV_K = 0.83                      # escala da gravura: o rosto precisa ler com 40 px
AV_HEAD = (250, 206)             # onde a cabeça fica no avatar
AV_HALO = 118                    # raio da auréola


def silhouette(w: int, h: int) -> str:
    """Recorte do busto chapado em mármore. No dithering o tom mais claro é transparente, então
    sem esta base os raios apareceriam através das luzes do corpo."""
    a = Image.open(ART).convert("LA")
    sw, sh = a.size
    a = a.crop((round(AV_BOX[0] * sw), round(AV_BOX[1] * sh), round(AV_BOX[2] * sw), round(AV_BOX[3] * sh)))
    a = a.split()[1].resize((w, h), Image.Resampling.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
    img = Image.new("RGBA", (w, h), T.card)
    img.putalpha(a)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def avatar() -> str:
    aw, ah = Image.open(ART).size
    k = AV_K                                          # px do avatar por px da gravura
    fw, fh = round((AV_BOX[2] - AV_BOX[0]) * aw * k), round((AV_BOX[3] - AV_BOX[1]) * ah * k)
    hx, hy = AV_HEAD
    fx = hx - (HEAD[0] - AV_BOX[0]) * aw * k
    fy = hy - (HEAD[1] - AV_BOX[1]) * ah * k

    inner = AV - 2 * AV_INSET
    defs = (DEFS_GRAIN
            + f'<radialGradient id="fade" cx="{num(hx)}" cy="{num(hy)}" r="330" gradientUnits="userSpaceOnUse">'
              '<stop offset=".3" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
            + f'<mask id="m"><rect width="{AV}" height="{AV}" fill="url(#fade)"/></mask>'
            + f'<clipPath id="in"><rect x="{AV_INSET}" y="{AV_INSET}" width="{inner}" height="{inner}"/></clipPath>')
    d = [f"<defs>{defs}</defs>",
         f'<rect width="{AV}" height="{AV}" fill="{T.card}"/>',
         f'<rect width="{AV}" height="{AV}" filter="url(#grain)"/>',
         f'<g clip-path="url(#in)">',
         # sol da forja
         f'<g mask="url(#m)">{rays(hx, hy, AV_HALO + 10, (80, 300), 150, 7, width=1.5)}</g>',
         f'<circle cx="{num(hx)}" cy="{num(hy)}" r="{AV_HALO}" fill="none" stroke="{X["ouro"]}" stroke-width="2"/>',
         f'<circle cx="{num(hx)}" cy="{num(hy)}" r="{AV_HALO + 10}" fill="none" stroke="{X["ouro"]}" stroke-width="1.2" stroke-dasharray="2 6"/>',
         # busto em ouro, cortado pela chapa; a silhueta em mármore embaixo tapa os raios nas luzes
         f'<image x="{num(fx)}" y="{num(fy)}" width="{fw}" height="{fh}" href="{silhouette(fw, fh)}"/>',
         f'<image x="{num(fx)}" y="{num(fy)}" width="{fw}" height="{fh}" href="{dither(fw, fh, px=2, box=AV_BOX)}" '
         f'image-rendering="optimizeSpeed" style="image-rendering:pixelated"/>',
         "</g>",
         f'<rect x="{AV_INSET}" y="{AV_INSET}" width="{inner}" height="{inner}" fill="none" stroke="{X["ouro"]}" stroke-width="1.5"/>']
    return svg(AV, AV, "mandasTeam: busto de Hefesto em dithering dourado sobre mármore, com auréola e raios.",
               "".join(d))


PROFILE_IMG = "https://github.com/mandasTeam/team-docs/raw/main/assets/mandasteam.svg"


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera os SVGs da direção de arte do mandasTeam.")
    ap.add_argument("--profile", type=Path, metavar="CLONE_DO_.GITHUB",
                    help="também escreve <clone>/profile/README.md (perfil da organização)")
    args = ap.parse_args()
    c, f = CONFIG, fonts()
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.svg"):
        old.unlink()
    files = {"mandasteam.svg": folio(c, f), "brand-tokens.svg": tokens_card(f), "avatar.svg": avatar()}
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
        print(f"{name}: {len(content) / 1024:.0f} KB")
    import resvg_py  # só para o PNG do avatar
    png = bytes(resvg_py.svg_to_bytes(svg_string=files["avatar.svg"], width=AV, height=AV))
    (out / "avatar.png").write_bytes(png)
    print(f"avatar.png: {len(png) / 1024:.0f} KB")
    if args.profile:
        # o perfil é um card só, servido daqui; o alt repete o <title> do SVG, palavra por palavra
        alt = files["mandasteam.svg"].split('<title id="t">', 1)[1].split("</title>", 1)[0].replace('"', "&quot;")
        dest = args.profile / "profile" / "README.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f'<p align="center">\n  <img src="{PROFILE_IMG}" width="100%" alt="{alt}">\n</p>\n',
                        encoding="utf-8")
        print(dest)


if __name__ == "__main__":
    main()
