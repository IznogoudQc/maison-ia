"""Écran Journal (touche J) : tout l'historique de la partie, par onglet, filtré par personne ou par mot.

Tab ou flèches gauche/droite : onglet ; P : personne suivante ; / : rechercher (Entrée pour finir) ;
molette, Page préc./suiv. : défiler ; E : exporter la chronique en HTML ; J ou Échap : fermer.
"""

from __future__ import annotations

from pathlib import Path

import pygame

from sim.history import CATEGORIES, History
from ui import theme
from ui.dialogue_box import wrap_text

COLORS = {"conversation": (120, 170, 235), "action": (140, 210, 120), "pensee": (190, 160, 240),
          "evenement": (235, 160, 110)}
TABS = [None, *CATEGORIES]   # None = tout


class JournalScreen:
    def __init__(self, history: History, export_path: str | Path) -> None:
        self.history = history
        self.export_path = Path(export_path)
        self.open = False
        self.tab = 0
        self.person: str | None = None
        self.search = ""
        self.typing = False
        self.scroll = 0          # lignes remontées depuis la fin
        self.message = ""

    def toggle(self) -> None:
        self.open = not self.open
        self.scroll, self.typing, self.message = 0, False, ""

    def handle_key(self, event: pygame.event.Event) -> bool:
        """Touche pour le journal ouvert ; True si elle est consommée (le jeu ne la voit pas)."""
        if not self.open:
            return False
        key = event.key
        if self.typing:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                self.typing = False
            elif key == pygame.K_BACKSPACE:
                self.search = self.search[:-1]
            elif event.unicode and event.unicode.isprintable():
                self.search += event.unicode
            self.scroll = 0
            return True
        if key in (pygame.K_ESCAPE, pygame.K_j):
            self.toggle()
        elif key in (pygame.K_TAB, pygame.K_RIGHT):
            self.tab, self.scroll = (self.tab + 1) % len(TABS), 0
        elif key == pygame.K_LEFT:
            self.tab, self.scroll = (self.tab - 1) % len(TABS), 0
        elif key == pygame.K_p:
            people = [None, *self.history.people()]
            index = people.index(self.person) if self.person in people else 0
            self.person, self.scroll = people[(index + 1) % len(people)], 0
        elif key == pygame.K_SLASH or event.unicode == "/":
            self.typing, self.search = True, ""
        elif key == pygame.K_PAGEUP:
            self.scroll += 20
        elif key == pygame.K_PAGEDOWN:
            self.scroll = max(0, self.scroll - 20)
        elif key == pygame.K_e:
            path = self.history.export_html(self.export_path)
            self.message = f"Chronique exportée : {path}"
        return True

    def wheel(self, dy: int) -> None:
        self.scroll = max(0, self.scroll + dy * 3)

    def draw(self, surface: pygame.Surface, area: pygame.Rect) -> None:
        if not self.open:
            return
        panel = area.inflate(-32, -32)
        veil = pygame.Surface(panel.size, pygame.SRCALPHA)
        veil.fill((22, 22, 28, 240))
        surface.blit(veil, panel.topleft)
        pygame.draw.rect(surface, theme.PANEL_BORDER, panel, 2, border_radius=6)
        x, y = panel.x + 16, panel.y + 12
        surface.blit(theme.font(18, bold=True).render("Journal de la famille", True, theme.TEXT), (x, y))
        # Onglets
        tx = x + 230
        for index, category in enumerate(TABS):
            label = "Tout" if category is None else CATEGORIES[category]
            active = index == self.tab
            image = theme.font(14, bold=active).render(label, True, theme.ACCENT if active else theme.TEXT_DIM)
            surface.blit(image, (tx, y + 3))
            if active:
                pygame.draw.line(surface, theme.ACCENT, (tx, y + 22), (tx + image.get_width(), y + 22), 2)
            tx += image.get_width() + 18
        y += 32
        search = f"Recherche : {self.search}{'_' if self.typing else ''}" if (self.search or self.typing) else ""
        filters = f"Personne : {self.person or 'tout le monde'}   {search}"
        surface.blit(theme.font(13).render(filters, True, theme.TEXT_DIM), (x, y))
        y += 22
        # Entrées, des plus anciennes aux plus récentes ; on défile depuis la fin
        entries = self.history.filtered(TABS[self.tab], self.person, self.search)
        font, small = theme.font(13), theme.font(12)
        width = panel.width - 40
        rows: list[tuple[str, tuple[int, int, int], pygame.font.Font]] = []
        current_day = None
        for entry in entries:
            if entry.day != current_day:
                current_day = entry.day
                rows.append((f"— Jour {entry.day + 1} —", theme.TEXT, font))
            color = COLORS.get(entry.category, theme.TEXT)
            for i, line in enumerate(wrap_text(f"{entry.stamp()[-5:]}  {entry.title}", font, width)):
                rows.append((line if i == 0 else "        " + line, color, font))
            for extra in entry.lines:
                for line in wrap_text(extra, small, width - 40):
                    rows.append(("          " + line, theme.TEXT_DIM, small))
        if not rows:
            rows = [("Rien à afficher pour l'instant.", theme.TEXT_DIM, font)]
        footer = 40
        visible = (panel.bottom - footer - y) // 17
        self.scroll = min(self.scroll, max(0, len(rows) - visible))
        end = len(rows) - self.scroll
        for text, color, row_font in rows[max(0, end - visible):end]:
            surface.blit(row_font.render(text, True, color), (x, y))
            y += 17
        help_text = self.message or ("Tab : onglet   P : personne   / : rechercher   molette : défiler   "
                                     "E : exporter en HTML   J : fermer")
        surface.blit(small.render(help_text, True, theme.TEXT_DIM), (x, panel.bottom - 26))
