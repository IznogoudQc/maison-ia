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

## Survie de la famille

- **Argent** : compte commun. Les parents sont payés au retour du travail (`salary_per_day` dans
  `family.yaml`) ; les factures (hypothèque, Hydro, internet, assurances + frais des achats) passent
  chaque vendredi. Un solde négatif mine le moral des parents.
- **Nourriture** : chaque repas et chaque lunch prennent une portion du garde-manger. Un adulte va
  faire l'épicerie quand il baisse, dans la limite de l'argent disponible. Frigo vide : pas de repas.
- **Heures supplémentaires** : proposées aux parents quand l'argent manque.
- **Santé et mort** : faim ou épuisement à zéro font baisser la santé ; à zéro, la personne meurt
  (cadre avec ruban noir au salon, deuil des survivants). Quand toute la famille est morte, la partie
  se termine. `health.mortality: false` remplace la mort par quelques jours d'hôpital.
- **Événements aléatoires** : mise à pied, facture imprévue, hausse du prix de l'épicerie, prime,
  remboursement d'impôt, gardiennage de Léa...
- **Extérieur** : le gazon pousse chaque jour. Sans tondeuse, le jeune d'à côté le tond (40 $) ;
  à 100 %, la ville donne une amende.
- **Achats** : tondeuse, BBQ, piscine, auto. Ils sont proposés aux parents seulement s'il reste deux
  semaines de dépenses en banque ; le LLM (ou le tirage déterministe) décide. L'auto fait rentrer
  du travail 30 minutes plus tôt et rend l'épicerie plus rapide et moins chère ; le BBQ remplace le
  souper la fin de semaine ; la piscine permet de se baigner.

Les prompts du LLM reçoivent l'état du ménage (argent, garde-manger, achats, chômage, santé,
deuils, dernière nouvelle) : les dialogues en parlent naturellement.

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
| `display` | `pixel_scale` (`auto` = le plus grand agrandissement qui tient dans l'écran, ou 1, 1.5, 2, 3), `fps`, `hud_width` |
| `sim` | `tick_minutes` (minutes simulées par tick), `base_ticks_per_second`, `speed_multipliers`, `start_day` (0 = lundi), `start_time`, `seed` |
| `llm` | `provider` (`mock`, `claude`, `ollama`), `claude_model`, `claude_effort`, `max_calls_per_minute` (limite par minute réelle), `decisions_enabled`, `decision_cooldown_minutes`, `decision_max_wait_minutes`, `mock_invalid_rate` |
| `dialogue` | `pair_cooldown_minutes` (cooldown social par paire), `max_participants`, `line_display_s` |
| `memory` | `short_term_size`, `recall_count` (souvenirs envoyés au LLM), `summary_every`, `max_summaries` |
| `economy` | `enabled`, `start_money`, `start_pantry`, `portion_price`, `weekly_bills`, `bills_weekday`, `grocery_days`, `low_pantry_days`, `overtime_below` |
| `health` | `mortality`, `starvation_per_hour`, `exhaustion_per_hour`, `regen_per_hour`, `hospital_days`, `grief_days` |
| `events` | `enabled`, `check_time`, `frequency` (0 = jamais, 2 = deux fois plus souvent) |

Le compteur d'appels et de tokens est affiché en haut du panneau, avec le solde, le garde-manger
et les derniers mouvements d'argent. Chaque dialogue, décision LLM, départ, retour, résumé, paie,
facture, épicerie, événement et décès est écrit dans `logs/sim_<date>.jsonl`.

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
    salary_per_day: 0        # paie nette par journée de travail (0 = pas d'emploi)
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
world/               maison, cours avant et arrière, objets (dont ceux à acheter) ; A*
agents/              persona, besoins, actions, horaire, mémoire, état de l'agent
llm/                 interface + factory, Claude, Ollama, mock, prompts, service (threads, retry, repli)
sim/                 horloge, moteur, économie (economy.py), événements aléatoires, bus, journal JSONL, config
ui/                  rendu pixel art (sprites générés dans sprites.py), bulles et historique, HUD
data/family.yaml     les personas
```

Le LLM ne gère jamais le mouvement : il choisit parmi des options calculées par le moteur, et ses
réponses sont validées (pydantic + vérification métier). Les appels tournent dans un pool de
threads ; pendant l'attente, l'agent affiche « … » et la boucle pygame continue.
