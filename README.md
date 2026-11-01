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

## Scénarios

- **maison** (par défaut) : la famille Gagnon dans sa maison de banlieue, avec ses deux cours.
- **terrain** : un jeune couple (Maxime et Camille, `data/couple.yaml`) vient d'acheter un grand lot
  boisé (120 × 80 tuiles : forêt en massifs d'érables, de sapins et de bouleaux, un étang). Au départ :
  une tente, un feu de camp, une glacière, une table de pique-nique, un baril d'eau de pluie et une
  bécosse. Pas d'hypothèque : seulement les taxes du terrain, les cellulaires et les assurances. La
  tente repose moins bien qu'un lit et le baril lave moins bien qu'une douche (qualité des objets).
  La même graine redonne la même forêt.

**Vivre sur le terrain**
- **Couper du bois** (adultes et ados de 16 ans et plus, de 8 h à 19 h) : l'arbre le plus proche qu'on
  peut atteindre ; la forêt se coupe par la lisière. Un érable donne 6 bûches, un sapin 5, un
  bouleau 4. L'option devient pressante quand la réserve passe sous 25 bûches et disparaît à 60
  (corde pleine, visible près de la tente). La scie à chaîne (400 $) coupe deux fois plus vite.
- **Feu de camp** : un souper sur le feu brûle une bûche (sans bois : souper froid) ; le soir, on
  peut veiller autour du feu (une bûche, du plaisir et du social), et le feu éclaire la nuit.
- **Sans toit** : la tente repose moins bien, le baril lave moins bien, et vivre sans maison use le
  moral petit à petit. Les prompts savent qu'on vit encore sous la tente et combien de bois il reste.

**L'IA architecte**
- Un soir où le couple est au campement (entre 19 h et 21 h 30), un appel LLM dessine la maison :
  l'IA décide des pièces (cuisine, salle de bain, chambre, salon, bureau, atelier), de leur taille
  (dans des bornes réalistes), de leur nombre (jusqu'à 8) et de l'ordre de construction, avec une
  courte discussion du couple affichée en bulles. Elle connaît le coût estimé de chaque pièce
  (argent et bûches), leurs moyens et leurs personnalités.
- L'IA ne donne pas de coordonnées : seulement « collée à la cuisine, côté est ». Le moteur place
  chaque pièce sur la grille sans chevauchement, loin du campement et de l'étang ; une pièce
  impossible est refusée avec la raison (gardée en mémoire). Les murs, les portes entre pièces
  voisines, la porte d'entrée (côté campement), les fenêtres sur les murs extérieurs et les meubles
  selon le type de pièce sont ajoutés automatiquement ; chaque meuble reste accessible.
- Le plan apparaît au sol (piquets et corde, nom des pièces) ; les arbres sur l'emplacement portent
  un ruban rouge et deviennent prioritaires à couper (« défriche l'emplacement de la cuisine »).

**Le chantier**
- Une pièce se bâtit dans l'ordre du plan, une fois son emplacement dégagé. Au premier coup de
  marteau, on achète les matériaux (de 1 000 à 5 000 $ selon la pièce ; la cuisine et la salle de
  bain coûtent plus cher à cause de la plomberie), seulement s'il reste une semaine de dépenses en
  banque.
- Chaque séance de travail (une heure, de 8 h à 20 h) pose des bûches et avance la pièce ; il faut
  8 h + 1,2 h par case de plancher. Un charpentier ou un bricoleur (Maxime) avance 50 % plus vite.
  Sans assez de bois, on avance moins, et la coupe devient pressante (la réserve visée monte jusqu'à
  ce qu'il manque pour finir).
- Ou on engage un entrepreneur (proposé quand on en a les moyens ; l'IA décide) : 40 $ de l'heure
  de travail restante, plus les matériaux et le bois qui manque (6 $ la bûche). Son équipe vient en
  semaine, de 8 h à 16 h, et avance plus vite.
- Sur la carte : dalle de béton, charpente qui monte le long des murs, toiture vers la fin, pile de
  planches, pourcentage au-dessus ; la pancarte jaune de l'entrepreneur quand il y en a un.
- Pièce finie : murs, portes, fenêtres et meubles ; avec la chambre, le couple quitte la tente.
  On peut se promettre de bâtir (« samedi on monte les murs »).
- Pour essayer sans attendre : `world.terrain.instant_build: true` bâtit chaque pièce dès que son
  emplacement est dégagé (ni matériaux, ni travail).

**La famille grandit** (scénario terrain, section `life`)
- Le temps passe vite : un an tous les 7 jours simulés (`days_per_year`). Bébé de 0 à 2 ans, enfant
  de 3 à 12, ado de 13 à 17, adulte à 18 ; le corps grandit à 13 ans, les anniversaires des enfants
  sont fêtés (bannière, souvenirs).
- Quand le couple est heureux (moyenne des besoins et de la santé), proche (affection mutuelle),
  qu'il a un toit et un peu d'argent de côté, un soir il parle d'avoir un enfant : un appel LLM écrit
  la discussion et la décision (« pas maintenant » est une vraie réponse ; au plus une fois par
  semaine). S'il dit oui, l'architecte ajoute une chambre au plan.
- Qui porte le bébé est écrit dans la fiche (`can_be_pregnant: true`, Camille dans
  `data/couple.yaml`) ; sans fiche qui porte, le couple adopte. Grossesse de 5 jours (fatigue, plus
  de gros travaux à la fin), accouchement à l'hôpital, puis l'IA imagine le bébé : prénom, traits,
  intérêts, façon de parler qu'il aura, couleurs.
- Le bébé dort dans un berceau près du lit des parents et ne marche pas : les parents (et les ados)
  s'en occupent (biberon, couche, câlins), d'autant plus vite qu'il a faim ; un parent affamé mange
  d'abord. Le parent qui a porté le bébé (ou un des deux pour une adoption) prend un congé parental
  la première année (prestations RQAP : 70 % du salaire en semaine).
- Garderie de 1 à 4 ans (9 $ par jour), école dès 5 ans, cégep à 18 ; à 3 ans, un vrai lit libre ou
  un matelas en attendant sa chambre (l'architecte agrandit). Jusqu'à 4 enfants (`max_children`).

Pour essayer le terrain : `world.scenario: terrain` dans `config.yaml`, puis
`uv run python main.py --nouveau`. Une sauvegarde d'un scénario n'est pas rechargée dans l'autre.

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
- **Événements aléatoires** (tirés chaque matin, au plus deux par jour) : chacun dit dans quel
  scénario il peut arriver et à quelle condition, et seuls ceux qui collent à la situation sont tirés.
  Partout : mise à pied, facture imprévue (des factures propres à chaque scénario), hausse de
  l'épicerie, prime, impôt, grand-maman (qui vient voir le bébé s'il y en a un), belle journée d'été,
  gardiennage (s'il y a un ado). Sur le terrain : orage (la tente prend l'eau, ou la bâche du
  chantier s'envole), arbre tombé (bûches gratuites), vol de matériaux et corvée entre voisins
  (pendant un chantier), ratons laveurs dans la glacière (tant qu'il n'y a pas de cuisine),
  inspecteur municipal (permis de construire, une seule fois), vente de bois de chauffage (grosse
  réserve), bébé malade (un parent rate une journée), cadeau de naissance.
- **Récit par l'IA** (`events.narrate`) : l'effet chiffré est appliqué par le moteur, puis le LLM
  raconte l'événement en une ou deux phrases avec les noms et le contexte ; le récit doit garder
  tous les chiffres, sinon (ou après 10 secondes sans réponse) le texte fixe est publié.
- **Extérieur** : le gazon pousse chaque jour. Sans tondeuse, le jeune d'à côté le tond (40 $) ;
  à 100 %, la ville donne une amende.
- **Achats** : tondeuse, BBQ, piscine, auto. Ils sont proposés aux parents seulement s'il reste deux
  semaines de dépenses en banque ; le LLM (ou le tirage déterministe) décide. L'auto fait rentrer
  du travail 30 minutes plus tôt et rend l'épicerie plus rapide et moins chère ; le BBQ remplace le
  souper la fin de semaine ; la piscine permet de se baigner.

- **Bibliothèque d'objets** (`data/catalogue.yaml`, à enrichir) : lits en gammes (matelas, lit
  simple, double, king), divans, bibliothèque, coffre à jouets, ordinateur, console, piano,
  congélateur (épicerie 8 % moins chère), potager (2 portions par jour), poulailler (1,5 portion par
  jour), trampoline, hamac, balançoire, spa, panneaux solaires (Hydro −30 $ par semaine). Chaque objet
  a un prix, des frais hebdomadaires éventuels, une taille, une activité (avec une qualité qui la rend
  plus ou moins efficace) et les pièces où il peut aller. Le moteur propose chaque jour quelques
  achats pertinents (un lit en priorité pour qui dort sur un matelas, une gamme supérieure, un objet
  utile) ; l'IA choisit, avec la pièce, et le moteur trouve la place exacte en gardant tout
  accessible. Un objet de gamme supérieure remplace l'ancien (revendu 40 %) ; dans le rouge, on peut
  revendre. Un achat d'objet par jour au plus (sauf un lit qui manque).

Les prompts du LLM reçoivent l'état du ménage (argent, garde-manger, achats, chômage, santé,
deuils, dernière nouvelle) : les dialogues en parlent naturellement.

## Vie intérieure des personnages

- **Plan du matin** : au réveil, chaque personnage demande au LLM son plan de la journée
  (3 à 6 activités placées dans ses plages libres, avec une intention). Le moteur le suit sans autre
  appel : à l'heure prévue, l'activité est choisie directement, sauf urgence (faim, fatigue,
  épicerie). Une activité impossible pendant 90 minutes est « manquée » et laisse un souvenir.
- **Nouveau plan** : une nouvelle importante (mise à pied, prime, décès, hôpital) fait refaire le
  plan du reste de la journée, au plus deux fois par jour.
- **Réflexion du soir** : au coucher, le LLM relit la journée, en tire 1 ou 2 constats (« l'argent
  m'inquiète »), désigne les souvenirs marquants et peut fixer un objectif pour le lendemain. Les
  constats sont envoyés dans tous les prompts suivants ; l'objectif rend l'activité visée plus
  attirante (`mind.goal_boost`) jusqu'à ce qu'elle soit faite.
- **Mémoire pondérée** : chaque souvenir a une importance (1 à 10 ; un décès vaut 10, une
  collation 1). Les souvenirs marquants passent en mémoire longue au lieu d'être oubliés, et les
  souvenirs envoyés au LLM sont choisis selon fraîcheur + importance + lien avec la situation
  (personnes présentes, pièce, intention). Une mise à pied peut donc revenir dans une conversation
  des semaines plus tard.

Le panneau d'un personnage affiche son intention, son plan (vert = fait, rouge = manqué), son
objectif et son dernier constat ; les plans et réflexions apparaissent aussi dans l'historique (H).

## Conversations et relations

- **Tour par tour** (`dialogue.mode: tour_par_tour`, par défaut) : chaque réplique est un appel LLM
  séparé, écrit avec la mémoire, les constats et les relations de la personne qui parle seulement.
  Un personnage ne sait donc pas ce que l'autre a vécu : il peut mal comprendre, éviter un sujet ou
  cacher quelque chose. Chaque réplique comporte aussi une pensée non dite (gardée dans sa mémoire)
  et la variation de ce qu'il ressent envers la personne à qui il parle. Les bulles s'affichent au
  fur et à mesure. `mode: scene` revient à un seul appel pour toute la conversation (moins cher).
- **Bilan** : après chaque conversation, un appel relève son importance (qui fixe le poids du
  souvenir), un résumé et les promesses faites.
- **Relations** : pour chaque paire et dans chaque sens, une affection et une tension (0 à 100),
  avec la dernière impression marquante. Elles teintent tous les prompts, rendent l'envie d'aller
  jaser plus ou moins forte et espacent les conversations d'une paire en chicane. Avec le temps,
  la tension retombe et l'affection revient vers la normale.
- **Promesses** : « on joue aux Lego demain après souper » devient un rendez-vous, accepté
  seulement s'il est réaliste (activité connue, personnes libres à cette heure, piscine achetée...).
  À l'heure dite, les personnes concernées y vont d'elles-mêmes (l'horaire et les urgences passent
  avant) ; si l'activité est réservée à l'autre, on va la faire à côté en jasant. Promesse tenue :
  affection en hausse. Promesse brisée : celui qui attendait s'en souvient et la tension monte.

Compter environ 1,5 fois plus d'appels qu'en mode scène ; à vitesse élevée, la limite
`llm.max_calls_per_minute` ralentit les conversations au lieu de dépenser plus.

## Contrôles

| Touche | Effet |
|---|---|
| Espace | pause / reprise |
| 1 à 4 | vitesse (multiplicateurs `sim.speed_multipliers`) |
| Clic sur un agent | besoins, action, humeur et mémoire dans le panneau ; clic dans le vide : vue famille |
| H | historique des dialogues (molette pour défiler) |
| Flèches ou WASD, clic droit glissé | déplacer la vue (grande carte) |
| Molette | zoom (dans l'historique : défiler) |
| Clic sur la mini-carte | centrer la vue à cet endroit |
| F | la caméra suit l'agent sélectionné |
| Échap | sauvegarde dans `save.json` et quitte |

## Configuration (`config.yaml`)

| Section | Clés principales |
|---|---|
| `display` | `pixel_scale` (`auto` = le plus grand agrandissement qui tient dans l'écran, ou 1, 1.5, 2, 3), `fps`, `hud_width` |
| `sim` | `tick_minutes` (minutes simulées par tick), `base_ticks_per_second`, `speed_multipliers`, `start_day` (0 = lundi), `start_time`, `seed` |
| `llm` | `provider` (`mock`, `claude`, `ollama`), `claude_model`, `claude_effort`, `max_calls_per_minute` (limite par minute réelle), `decisions_enabled`, `decision_cooldown_minutes`, `decision_max_wait_minutes`, `mock_invalid_rate` |
| `dialogue` | `mode` (`tour_par_tour` ou `scene`), `max_turns`, `max_minutes`, `pair_cooldown_minutes` (cooldown social par paire), `tense_cooldown_factor`, `tension_decay_per_day`, `promise_window_minutes`, `promise_max_days`, `max_participants`, `line_display_s` |
| `memory` | `short_term_size`, `recall_count` (souvenirs envoyés au LLM), `summary_every`, `max_summaries`, `long_term_size`, `keep_from_importance`, `recency_half_life_hours`, `max_beliefs` |
| `mind` | `plans_enabled`, `reflections_enabled`, `plan_item_window_minutes`, `max_replans_per_day`, `goal_boost` |
| `economy` | `enabled`, `start_money`, `start_pantry`, `portion_price`, `weekly_bills`, `bills_weekday`, `grocery_days`, `low_pantry_days`, `overtime_below` |
| `health` | `mortality`, `starvation_per_hour`, `exhaustion_per_hour`, `regen_per_hour`, `hospital_days`, `grief_days` |
| `events` | `enabled`, `check_time`, `frequency` (0 = jamais, 2 = deux fois plus souvent), `narrate` |
| `life` | `enabled`, `days_per_year`, `pregnancy_days`, `min_happiness`, `min_affection`, `talk_every_days`, `max_children`, `parental_leave_years`, `daycare_fee` |
| `world` | `scenario` (`maison` ou `terrain`) ; `terrain` : `width`, `height`, `seed`, `tree_density`, `family_file`, `start_money`, `start_pantry`, `weekly_bills`, `instant_build` |

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
sauvegarde et chargement, économie, santé, événements, extérieur, mémoire pondérée, plan et
réflexion, répliques tour par tour (point de vue de chacun), relations et promesses.

## Architecture

```
main.py              boucle pygame (tick fixe, poll LLM non bloquant, rendu)
world/               monde générique (house.py), terrain boisé (terrain.py), pièces et meubles (building.py), A*
agents/              persona, besoins, actions, horaire, mémoire pondérée, plan du jour, relations, état de l'agent
llm/                 interface + factory, Claude, Ollama, mock, prompts (décision, plan, réplique, bilan), service
sim/                 horloge, moteur, vie intérieure (mind.py), conversations (social.py), architecte (architect.py),
                     famille (family.py), économie,
                     événements aléatoires, bus, journal, config
ui/                  rendu pixel art (sprites générés dans sprites.py), bulles et historique, HUD
data/family.yaml     les personas
```

Le LLM ne gère jamais le mouvement : il choisit parmi des options calculées par le moteur, et ses
réponses sont validées (pydantic + vérification métier). Les appels tournent dans un pool de
threads ; pendant l'attente, l'agent affiche « … » et la boucle pygame continue.
