"""Point d'entrée : boucle pygame de la simulation Maison IA."""

from __future__ import annotations

import argparse
import random
import webbrowser
from pathlib import Path

import pygame
from dotenv import load_dotenv

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.provider import LLMError, create_provider
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.paths import ask_and_store_api_key, load_api_key, prepare_installed_app
from sim.events import EventBus
from sim.journal import JsonlJournal
from ui import theme
from ui.dialogue_box import MIND_KINDS, NEWS_KINDS, DialogueBox
from ui.hud import Hud, draw_game_over
from ui import tooltip
from ui.household import HouseholdScreen
from ui.interview import InterviewScreen
from ui.journal import JournalScreen
from ui.portrait import PortraitScreen
from ui.renderer import Renderer
from ui.sprites import TILE
from world.house import House
from world.terrain import build_house

SPEED_KEYS = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3}
PAN_KEYS = {pygame.K_LEFT: (-1, 0), pygame.K_a: (-1, 0), pygame.K_RIGHT: (1, 0), pygame.K_d: (1, 0),
            pygame.K_UP: (0, -1), pygame.K_w: (0, -1), pygame.K_DOWN: (0, 1), pygame.K_s: (0, 1)}
PAN_SPEED = 700         # px écran par seconde
SCROLL_SCALE = 2.0      # zoom de départ quand la carte ne tient pas à l'écran
MAX_TICKS_PER_FRAME = 60
SCALES = (3.0, 2.0, 1.5, 1.0)
SCREEN_MARGIN = (40, 90)  # bordure de fenêtre et barre des tâches


def fit_view(house: House, hud_width: int, wanted: float | str) -> tuple[float, tuple[int, int] | None]:
    """Zoom et taille de la zone de carte.

    La carte entière tient à l'écran (maison) : plus grand agrandissement qui la fait tenir.
    Sinon (grand terrain) : zoom SCROLL_SCALE et zone de carte = tout l'écran disponible, avec défilement.
    """
    info = pygame.display.Info()
    max_w, max_h = info.current_w - SCREEN_MARGIN[0] - hud_width, info.current_h - SCREEN_MARGIN[1]
    if wanted != "auto":
        scale = float(wanted)
        if house.width * TILE * scale <= max_w and house.height * TILE * scale <= max_h:
            return scale, None
        return scale, (max_w, max_h)
    for scale in SCALES:
        if house.width * round(TILE * scale) <= max_w and house.height * round(TILE * scale) <= max_h:
            return scale, None
    return SCROLL_SCALE, (max_w, max_h)


def take_snapshot(screen: pygame.Surface, area: pygame.Rect, chronicle, caption: str) -> None:
    """Photo de la carte pour la chronique de la semaine (960 px de large au plus)."""
    width = min(960, area.width)
    shot = pygame.transform.smoothscale(screen.subsurface(area), (width, round(area.height * width / area.width)))
    name = chronicle.next_shot_name()
    try:
        chronicle.out_dir.mkdir(parents=True, exist_ok=True)
        pygame.image.save(shot, str(chronicle.out_dir / name))
    except (pygame.error, OSError) as exc:
        print(f"[Chronique] capture impossible : {exc}")
        chronicle.wanted = None
        return
    chronicle.add_snapshot(name, caption)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulation Maison IA")
    parser.add_argument("--nouveau", action="store_true", help="ignorer save.json et repartir de zéro")
    parser.add_argument("--config", help="fichier de configuration (défaut : config.yaml)")
    parser.add_argument("--cle", action="store_true",
                        help="saisir la clé Claude une fois (rangée dans le Gestionnaire d'identifiants Windows)")
    args = parser.parse_args()

    if args.cle:
        ask_and_store_api_key()
        return
    prepare_installed_app()  # installée : config, données et sauvegardes dans %APPDATA%\MaisonIA
    load_dotenv()
    load_api_key()
    try:
        # Chemin explicite : il doit exister ; config.yaml absent : valeurs par défaut
        config = load_config(args.config or "config.yaml", required=args.config is not None)
    except FileNotFoundError as exc:
        parser.error(str(exc))
    rng = random.Random(config.sim.seed)

    try:
        provider = create_provider(config.llm)
        llm_label = provider.label()
    except LLMError as exc:
        print(f"[LLM] {exc} -> repli sur le mode mock")
        provider = MockProvider(config.llm.mock_latency_s, config.llm.mock_invalid_rate)
        llm_label = "mock (repli : config LLM invalide)"
    prices = (config.llm.claude_price_in, config.llm.claude_price_out) if config.llm.provider == "claude" else (0.0, 0.0)
    llm = LLMService(provider, config.llm.max_calls_per_minute, config.llm.max_workers, prices)

    terrain = config.world.terrain
    seed = terrain.seed if terrain.seed is not None else config.sim.seed
    house = build_house(config.world.scenario, terrain.width, terrain.height, seed, terrain.tree_density)
    personas = load_family(config.family_file)
    agents = [Agent(persona=p, pos=house.random_tile(rng)) for p in personas]
    clock = SimClock(config.sim.start_day, config.sim.start_time, config.sim.tick_minutes)
    bus = EventBus()
    engine = Engine(config, house, agents, clock, rng, bus, llm)
    engine.initialize()
    save_path = Path(config.save_file)
    engine.chronicle.out_dir = save_path.parent / "chroniques"   # pages HTML et captures de la semaine
    if save_path.exists() and not args.nouveau:
        try:
            engine.load_state(save_path)
            print(f"[Sauvegarde] {save_path} chargée : {clock.label()}")
        except (ValueError, KeyError, OSError) as exc:
            print(f"[Sauvegarde] {save_path} illisible ({exc}) -> nouvelle partie")

    pygame.init()
    title = "Maison IA — le terrain" if config.world.scenario == "terrain" else "Maison IA — famille Gagnon"
    pygame.display.set_caption(title)
    scale, viewport = fit_view(house, config.display.hud_width, config.display.pixel_scale)
    renderer = Renderer(house, scale, viewport)
    camp = next((a for a in agents if not a.is_away), agents[0])
    renderer.center_on(*camp.pos)
    map_w, map_h = renderer.size
    screen = pygame.display.set_mode((map_w + config.display.hud_width, map_h))
    hud = Hud(pygame.Rect(map_w, 0, config.display.hud_width, map_h))
    hud.careers = engine.careers
    dialogue_box = DialogueBox(renderer, engine.everyone, config.dialogue.line_display_s, config.dialogue.history_size)
    bus.subscribe("dialogue", dialogue_box.on_dialogue)
    bus.subscribe("replique", dialogue_box.on_line)
    for kind in NEWS_KINDS:
        bus.subscribe(kind, dialogue_box.on_news)
    for kind in MIND_KINDS:
        bus.subscribe(kind, dialogue_box.on_mind)
    journal = JsonlJournal(config.log_dir, clock)
    journal.attach(bus)
    journal_screen = JournalScreen(engine.history, Path(config.save_file).with_name("chronique.html"))
    household_screen = HouseholdScreen(engine)
    portrait_screen = PortraitScreen(engine)
    interview_screen = InterviewScreen(engine)
    frame_clock = pygame.time.Clock()

    speed_index = 0
    paused = False
    selected_id: str | None = None
    follow = False          # F : la caméra suit l'agent sélectionné
    dragging = False        # clic droit maintenu : on fait glisser la vue
    tick_accumulator = 0.0
    running = True

    while running:
        dt = frame_clock.tick(config.display.fps) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.TEXTINPUT and interview_screen.open:
                interview_screen.handle_text(event.text)
            elif event.type == pygame.KEYDOWN and interview_screen.handle_key(event):
                continue  # entrevue ouverte : on écrit, le jeu ne voit pas les touches
            elif event.type == pygame.KEYDOWN and journal_screen.handle_key(event):
                continue  # journal ouvert : il garde le clavier (Échap le ferme)
            elif event.type == pygame.KEYDOWN and household_screen.handle_key(event):
                continue  # écran Maison ouvert : idem
            elif event.type == pygame.KEYDOWN and portrait_screen.handle_key(event):
                continue  # fiche personnage ouverte : idem
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_h:
                    dialogue_box.toggle_history()
                elif event.key == pygame.K_j:
                    journal_screen.toggle()
                elif event.key == pygame.K_i:
                    household_screen.toggle()
                elif event.key == pygame.K_p:
                    portrait_screen.show(selected_id)
                elif event.key == pygame.K_k:
                    page = engine.chronicle.latest()
                    if page is not None and page.exists():
                        webbrowser.open(page.resolve().as_uri())
                elif event.key == pygame.K_t:
                    interview_screen.show(selected_id, event.unicode.lower() or "t")
                elif event.key in SPEED_KEYS:
                    speed_index = min(SPEED_KEYS[event.key], len(config.sim.speed_multipliers) - 1)
                elif event.key == pygame.K_f:
                    follow = not follow and selected_id is not None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if event.pos[0] < map_w and not renderer.minimap_click(event.pos):
                    clicked = renderer.agent_at(engine.everyone, event.pos)
                    selected_id = clicked.id if clicked else None
                    follow = follow and selected_id is not None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and event.pos[0] < map_w:
                dragging = True
                follow = False
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                dragging = False
            elif event.type == pygame.MOUSEMOTION and dragging:
                renderer.pan(-event.rel[0], -event.rel[1])
            elif event.type == pygame.MOUSEWHEEL:
                if journal_screen.open:
                    journal_screen.wheel(event.y)
                elif household_screen.open:
                    household_screen.wheel(event.y)
                elif dialogue_box.show_history:
                    dialogue_box.scroll_history(event.y * 3)
                else:
                    mouse = pygame.mouse.get_pos()
                    renderer.zoom(1 if event.y > 0 else -1, mouse if mouse[0] < map_w else None)

        keys = pygame.key.get_pressed()
        pan = [sum(d[i] for k, d in PAN_KEYS.items() if keys[k]) for i in (0, 1)]
        if pan != [0, 0] and not (journal_screen.open or household_screen.open or portrait_screen.open
                                  or interview_screen.open):
            follow = False
            renderer.pan(pan[0] * PAN_SPEED * dt, pan[1] * PAN_SPEED * dt)

        speed = config.sim.speed_multipliers[speed_index]
        if not paused:
            tick_accumulator += dt * config.sim.base_ticks_per_second * speed
            ticks = 0
            while tick_accumulator >= 1.0 and ticks < MAX_TICKS_PER_FRAME:
                engine.tick()
                tick_accumulator -= 1.0
                ticks += 1
            tick_accumulator = min(tick_accumulator, 1.0)  # évite la spirale de rattrapage
        engine.poll()  # réponses LLM arrivées (non bloquant)

        renderer.set_yard(engine.economy.household.lawn, engine.car_home(), engine.economy.household.wood)
        renderer.purchases = set(engine.economy.household.purchases)
        renderer.set_season(engine.seasons.foliage, engine.seasons.snow, engine.seasons.driveway)
        renderer.sim_minute = clock.total_minutes
        renderer.vehicles_out = engine.garage.in_use()
        renderer.set_plan(engine.architect.plan, [t.rect[:2] for t in engine.architect.clearing_trees()])
        renderer.update_display(engine.everyone, dt)
        followed = engine.agent_by_id(selected_id) if follow and selected_id else None
        if followed is not None and not followed.is_away:
            renderer.center_on(*renderer.display_pos.get(followed.id, followed.pos))
        dialogue_box.update(0.0 if paused else dt)
        screen.fill(theme.BACKGROUND)
        renderer.draw(screen, engine.everyone, selected_id, clock.minute_of_day)
        dialogue_box.draw(screen)
        caption = engine.chronicle.snapshot_request()
        if caption is not None:
            take_snapshot(screen, pygame.Rect(0, 0, map_w, map_h), engine.chronicle, caption)
        journal_screen.draw(screen, pygame.Rect(0, 0, map_w, map_h))
        household_screen.draw(screen, pygame.Rect(0, 0, map_w, map_h))
        portrait_screen.draw(screen, pygame.Rect(0, 0, map_w, map_h))
        interview_screen.draw(screen, pygame.Rect(0, 0, map_w, map_h))
        mouse = pygame.mouse.get_pos()
        screens_open = journal_screen.open or household_screen.open or portrait_screen.open or interview_screen.open
        if not screens_open and not dialogue_box.show_history and mouse[0] < map_w and not dragging:
            tooltip.draw(screen, tooltip.describe(engine, renderer, mouse), mouse, pygame.Rect(0, 0, map_w, map_h))
        selected = engine.agent_by_id(selected_id) if selected_id else None
        promises = [f"{p.text} ({engine.social.when_label(p.minute)})"
                    for p in engine.social.promises if p.status == "pending"]
        extra = list(engine.family.hud_lines()) + engine.credit.hud_lines() + engine.visitors.hud_lines()
        extra += engine.gossip.hud_lines() + [engine.seasons.hud_line()]
        if house.layout.wild:
            extra.append(f"Bois : {engine.economy.household.wood} bûches   "
                         f"Arbres : {len(house.objects_of_kind('arbre'))}")
        hud.draw(screen, clock, speed, paused, agents, selected, llm, llm_label,
                 engine.economy, engine.alive_count(), promises, extra, engine.architect.hud_lines(),
                 engine.garage.hud_lines() + engine.inventory.hud_lines())
        if engine.game_over:
            draw_game_over(screen, pygame.Rect(0, 0, map_w, map_h), clock)
        pygame.display.flip()

    if engine.game_over:
        print(f"[Sauvegarde] partie terminée : {save_path} n'est pas modifié (relancer avec --nouveau)")
    else:
        engine.save_state(save_path)
        print(f"[Sauvegarde] état écrit dans {save_path} ({clock.label()})")
    llm.shutdown()
    journal.close()
    pygame.quit()


if __name__ == "__main__":
    main()
