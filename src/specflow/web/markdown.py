"""Bezpieczne renderowanie Markdownu z treści od modelu (ADR-0008).

Artefakty Spec Kit, wiadomości wywiadu, log agenta i wyniki testów pisze model (albo kod,
który model napisał), więc to niezaufane dane. Gdyby trafiły do strony jako HTML,
wstrzyknięty `<script>` wykonałby się z uprawnieniami użytkownika w Specflow.

Zasady:
- surowy HTML w Markdownie jest wyłączony (`html: False`) - wychodzi jako tekst;
- linki tylko `http(s)://`, `mailto:` i kotwice `#` (bez `javascript:`, `data:` itp.);
- obrazki wyłączone (śledzące piksele, zasoby z zewnątrz);
- druga warstwa: nagłówek CSP w aplikacji blokuje skrypty spoza `/static`.
"""

from collections.abc import Sequence

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

_ALLOWED_SCHEMES = ("http://", "https://", "mailto:", "#")


def _validate_link(url: str) -> bool:
    return url.strip().lower().startswith(_ALLOWED_SCHEMES)


def _link_open(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
) -> str:
    tokens[idx].attrSet("rel", "noopener noreferrer nofollow")
    return self.renderToken(tokens, idx, options, env)


def _build() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable("table")
    md.disable("image")
    md.validateLink = _validate_link  # type: ignore[method-assign]
    md.add_render_rule("link_open", _link_open)
    return md


_MD = _build()


def render_markdown(text: str) -> str:
    return str(_MD.render(text))
