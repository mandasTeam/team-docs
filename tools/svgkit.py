"""svgkit: motor para gerar cards SVG de README com texto convertido em <path>.

O GitHub exibe SVG via <img> em sandbox: fonte web e imagem externa não carregam.
Por isso todo texto vira contorno (HarfBuzz + fontTools) e imagens entram em base64.

O svgkit não tem estilo próprio: só mede e desenha texto e dá peças estruturais neutras
(fundo de card, título de seção, etiqueta). Cor, fonte, forma e motivo vêm do plano de
design de cada projeto, no build_assets.py dele.

Uso mínimo:
    from svgkit import Font, Theme, heading
    display = Font("fonts/<Display>.ttf")                      # fonte estática
    body = Font("fonts/<Familia>[wght].ttf", wght=500)         # fonte variável: escolha o eixo
    open("h.svg", "w", encoding="utf-8").write(heading("Projetos", display, Theme()))

Dependências: fonttools, uharfbuzz.
"""
from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

REDUCED_MOTION = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


def num(v: float) -> str:
    """Uma casa decimal: corta ~40% do tamanho do path sem diferença visível."""
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


@dataclass
class Theme:
    """Tokens de cor do plano de design. Os padrões são cinzas neutros só para o código rodar:
    troque todos pelos do projeto. Cores do motivo vão em `extra` (nome -> hex)."""
    card: str = "#16181D"      # fundo dos cards (precisa ler nos temas claro e escuro do GitHub)
    line: str = "#2C3038"      # borda dos cards
    text: str = "#F2F3F5"      # texto principal
    soft: str = "#C4C8D0"      # texto secundário
    muted: str = "#8A909C"     # apoio, rótulos discretos
    accent: str = "#9AA4B5"    # destaque
    on_accent: str = "#16181D" # texto sobre o acento
    extra: dict[str, str] = field(default_factory=dict)


class MissingGlyph(ValueError):
    pass


class Font:
    def __init__(self, path: str | Path, **axes: float):
        """axes: posição nos eixos de uma fonte variável, ex.: Font(p, wght=700, wdth=85)."""
        path = Path(path)
        self.name = path.stem
        self.tt = TTFont(path)
        self.gs = self.tt.getGlyphSet(location=axes or None)
        self.order = self.tt.getGlyphOrder()
        self.upem = self.tt["head"].unitsPerEm
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        if axes:
            self.hb.set_variations(axes)

    def _shape(self, text: str):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": True})
        return buf.glyph_infos, buf.glyph_positions

    def width(self, text: str, size: float, tracking: float = 0) -> float:
        infos, pos = self._shape(text)
        return sum(p.x_advance for p in pos) * size / self.upem + tracking * max(len(infos) - 1, 0)

    def cap_height(self, size: float) -> float:
        bp = BoundsPen(self.gs)
        self.gs["H"].draw(bp)
        return bp.bounds[3] * size / self.upem

    def path(self, text: str, size: float, x: float, y: float, anchor: str = "start",
             tracking: float = 0) -> str:
        """Contorno do texto com a linha de base em y. anchor: start | middle | end."""
        w = self.width(text, size, tracking)
        x -= {"start": 0, "middle": w / 2, "end": w}[anchor]
        s = size / self.upem
        pen = SVGPathPen(self.gs, ntos=num)
        infos, pos = self._shape(text)
        cx = 0.0
        for info, p in zip(infos, pos):
            if info.codepoint == 0:
                raise MissingGlyph(f"{self.name} não tem glifo para algum caractere de {text!r}")
            tp = TransformPen(pen, (s, 0, 0, -s, x + cx + p.x_offset * s, y - p.y_offset * s))
            self.gs[self.order[info.codepoint]].draw(tp)
            cx += p.x_advance * s + tracking
        return pen.getCommands()

    def wrap(self, text: str, size: float, max_w: float) -> list[str]:
        lines, cur = [], ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if cur and self.width(trial, size) > max_w:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def fit(self, text: str, size: float, max_w: float, tracking: float = 0, floor: float = 12) -> float:
        """Maior tamanho <= size em que o texto cabe em max_w."""
        while size > floor and self.width(text, size, tracking) > max_w:
            size -= 0.5
        return size


# --------------------------------------------------------------------------- texto rico
Segment = tuple  # (texto, Font, tamanho, cor)


def rich_lines(segs: list[Segment], max_w: float):
    """Quebra trechos com estilos diferentes só nos espaços ("**Nome**." fica junto)."""
    words, cur = [], []
    for text, font, size, color in segs:
        for tok in re.findall(r"\S+|\s+", text):
            if tok.isspace():
                if cur:
                    words.append(cur)
                    cur = []
            else:
                cur.append((tok, font, size, color))
    if cur:
        words.append(cur)

    lines, line, lw = [], [], 0.0
    for w in words:
        space = w[0][1].width(" ", w[0][2]) if line else 0.0
        ww = sum(f.width(t, s) for t, f, s, _ in w)
        if line and lw + space + ww > max_w:
            lines.append(line)
            line, lw, space = [], 0.0, 0.0
        line.append((space, w))
        lw += space + ww
    if line:
        lines.append(line)
    return lines


def line_width(line) -> float:
    return sum(sp + sum(f.width(t, s) for t, f, s, _ in w) for sp, w in line)


def rich_paths(lines, x: float, y: float, line_h: float, align: str = "start", box_w: float = 0) -> list[str]:
    out = []
    for i, line in enumerate(lines):
        cx = x + {"start": 0, "middle": (box_w - line_width(line)) / 2}[align]
        for space, w in line:
            cx += space
            for t, f, s, c in w:
                out.append(f'<path d="{f.path(t, s, cx, y + i * line_h)}" fill="{c}"/>')
                cx += f.width(t, s)
    return out


# --------------------------------------------------------------------------- peças neutras
def svg(w: int, h: int, title: str, body: str, style: str = "") -> str:
    """title vira <title> (leitor de tela); repita o texto completo no alt do <img>."""
    css = f"<style>{style}</style>" if style else ""
    title = title.replace("&", "&amp;").replace("<", "&lt;")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-labelledby="t"><title id="t">{title}</title>{css}{body}</svg>\n')


def data_uri(path: str | Path) -> str:
    """Imagem embutida (avatar, folha de ícones). Não acompanha mudanças no original."""
    path = Path(path)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def card_frame(w: int, h: int, theme: Theme, rx: float = 16, stroke: float = 2) -> list[str]:
    """Fundo de card com borda. Só estrutura: o motivo do projeto é desenhado por cima."""
    i = stroke / 2
    box = f'x="{num(i)}" y="{num(i)}" width="{num(w - stroke)}" height="{num(h - stroke)}" rx="{num(rx)}"'
    return [f'<rect {box} fill="{theme.card}" stroke="{theme.line}" stroke-width="{num(stroke)}"/>']


def heading(text: str, font: Font, theme: Theme, w: int = 1200, h: int = 64, size: float = 32,
            color: str | None = None, rule: bool = True, rx: float = 12) -> str:
    """Título de seção numa faixa com fundo próprio (sem fundo, some no tema claro do GitHub),
    texto à esquerda e, opcional, uma régua até a borda. Ponto de partida estrutural:
    a forma final do título sai do plano de design."""
    base = h / 2 + font.cap_height(size) / 2
    d = card_frame(w, h, theme, rx)
    d.append(f'<path d="{font.path(text, size, 28, base)}" fill="{color or theme.text}"/>')
    if rule:
        x = 28 + font.width(text, size) + 24
        d.append(f'<line x1="{num(x)}" y1="{num(h / 2)}" x2="{w - 28}" y2="{num(h / 2)}" '
                 f'stroke="{theme.line}" stroke-width="2"/>')
    return svg(w, h, text, "".join(d))


def pill(x: float, y: float, text: str, font: Font, size: float, fill: str, ink: str,
         pad: float = 18, h: float = 40, rx: float | None = None) -> list[str]:
    """Etiqueta com fundo (cargo, tag de stack). rx=None deixa em pílula; rx=0, retângulo."""
    w = font.width(text, size) + pad * 2
    r = h / 2 if rx is None else rx
    return [f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="{num(r)}" fill="{fill}"/>',
            f'<path d="{font.path(text, size, x + pad, y + h / 2 + font.cap_height(size) / 2)}" fill="{ink}"/>']


def warning_icon(x: float, y: float, fill: str, ink: str) -> str:
    """Desenhado à mão: fontes de texto raramente têm ⚠."""
    return (f'<g transform="translate({num(x)},{num(y)})"><path d="M0,-15 L16,13 L-16,13 Z" fill="{fill}" '
            f'stroke="{ink}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<rect x="-1.6" y="-6" width="3.2" height="10" rx="1.4" fill="{ink}"/>'
            f'<circle cy="8" r="1.9" fill="{ink}"/></g>')
