# Maison IA

Simulation 2D (vue de dessus) d'une famille québécoise de 4 personnes. Les déplacements, les besoins
et les horaires sont du code déterministe ; un LLM choisit certaines activités, écrit les dialogues
quand des membres de la famille se croisent, et résume leur mémoire. Inspiré du papier
« Generative Agents » (Stanford, 2023), en version simplifiée.

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/) (il installe Python 3.12 au besoin).

```bash
uv sync
uv run python main.py
```

Par défaut, la simulation tourne en mode `mock` : réponses factices, sans clé API et sans coût.
Une sauvegarde `save.json` est rechargée au démarrage ; `uv run python main.py --nouveau` repart de zéro.

### Avec Claude

1. Copier `.env.example` vers `.env` et renseigner `ANTHROPIC_API_KEY` (le fichier `.env` n'est jamais commité).
2. Dans `config.yaml` : `llm.provider: claude` (modèle par défaut : `claude-haiku-5-5`).

### Avec Ollama

1. `ollama pull llama3.1:8b`, avec le serveur Ollama lancé.
2. Dans `config.yaml` : `llm.provider: ollama` (ajuster `ollama_model` et `ollama_url` au besoin).

Si le fournisseur est mal configuré (clé absente par exemple), la simulation le signale dans la
console et passe en mode mock.

## Contrôles

| Touche | Effet |
|---|---|
| Espace | pause / reprise |
| 1 à 4 | vitesse (multiplicateurs `sim.speed_multipliers`) |
| Clic sur un agent | besoins, action, humeur et mémoire dans le panneau ; clic dans le vide : vue famille |
| H | historique des dialogues (molette pour défiler) |
| Échap | sauvegarde dans `save.json` et quitte |

## Configuration (`config.yaml`)

| Section | Clés principales |
|---|---|
| `display` | `pixel_scale` (agrandissement du pixel art : 2 = fenêtre de 1544×768, 1.5 pour un petit écran), `fps`, `hud_width` |
| `sim` | `tick_minutes` (minutes simulées par tick), `base_ticks_per_second`, `speed_multipliers`, `start_day` (0 = lundi), `start_time`, `seed` |
| `llm` | `provider` (`mock`, `claude`, `ollama`), `claude_model`, `claude_effort`, `max_calls_per_minute` (limite par minute réelle), `decisions_enabled`, `decision_cooldown_minutes`, `decision_max_wait_minutes`, `mock_invalid_rate` |
| `dialogue` | `pair_cooldown_minutes` (cooldown social par paire), `max_participants`, `line_display_s` |
| `memory` | `short_term_size`, `recall_count` (souvenirs envoyés au LLM), `summary_every`, `max_summaries` |

Le compteur d'appels et de tokens est affiché en haut du panneau. Chaque dialogue, décision LLM,
départ, retour et résumé est écrit dans `logs/sim_<date>.jsonl`.

## Ajouter un persona

Ajouter une entrée sous `family:` dans `data/family.yaml` :

```yaml
  - id: grandmere            # identifiant unique, utilisé dans les relations des autres
    name: Ginette
    age: 72
    role: grand-mère
    color: [60, 160, 120]    # couleur du pion (RGB)
    traits: [taquine, généreuse]
    interests: [le tricot, les téléromans]
    routines: [Fait sa marche tous les matins]
    relations:
      enfant: "Son petit-fils adoré, qu'elle gâte en cachette."
    speech_style: "Expressions d'antan, « mon p'tit pit »."
    bed: lit_parents         # id d'un objet « lit » de world/house.py
    favorite_actions: [lire, tele]
    schedule:
      wake: "06:00"
      sleep: "21:30"
      away: null             # ou {leave: "08:00", back: "16:00", days: [0,1,2,3,4], label: travail}
      tasks:
        - {time: "18:00", action: souper}
```

- Les actions possibles (`favorite_actions`, `tasks`) sont listées dans `agents/actions.py`.
- Chaque lit a un nombre de places fixe (2 pour `lit_parents`, 1 pour les autres) : pour un
  cinquième membre, ajouter un objet `lit` dans `OBJECTS` (`world/house.py`) avec ses `use_positions`.
- La table compte 4 places : au souper, un membre de trop fait autre chose et retente de s'asseoir
  pendant 30 minutes simulées ; ajouter des `use_positions` à `table` pour l'éviter.
- Penser à ajouter la relation inverse dans les fiches des autres membres.

## Tests

```bash
uv run pytest
```

Couverts : pathfinding A*, décroissance des besoins, parsing JSON du LLM (cas valides et invalides),
retry puis repli, limite de débit, journée simulée complète en mode mock, cooldown par paire,
sauvegarde et chargement.

## Architecture

```
main.py              boucle pygame (tick fixe, poll LLM non bloquant, rendu)
world/               grille, pièces, objets ; A*
agents/              persona, besoins, actions, horaire, mémoire, état de l'agent
llm/                 interface + factory, Claude, Ollama, mock, prompts, service (threads, retry, repli)
sim/                 horloge, moteur, bus d'événements, journal JSONL, config
ui/                  rendu pixel art (sprites générés dans sprites.py), bulles et historique, HUD
data/family.yaml     les personas
```

Le LLM ne gère jamais le mouvement : il choisit parmi des options calculées par le moteur, et ses
réponses sont validées (pydantic + vérification métier). Les appels tournent dans un pool de
threads ; pendant l'attente, l'agent affiche « … » et la boucle pygame continue.
