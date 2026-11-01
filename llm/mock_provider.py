"""Fournisseur factice : réponses plausibles, sans clé ni coût, avec latence simulée."""

from __future__ import annotations

import json
import random
import threading
import time

from llm.provider import LLMProvider, LLMRequest, LLMResponse

# Répliques d'ouverture par persona ; {other} = prénom d'un autre participant
OPENERS: dict[str, list[str]] = {
    "pere": [
        "Bon ben, {other}, t'as-tu vu le score d'hier? Moi non plus, je dormais.",
        "J'ai réparé le robinet. Il coule juste un peu plus qu'avant.",
        "{other}, si quelqu'un cherche la télécommande, c'est pas moi qui l'a.",
        "Y fait frette dehors, j'ai vu un pingouin passer en Corolla.",
        "On mange-tu du spaghat' encore ce soir? Pas que je me plains.",
    ],
    "mere": [
        "{other}, ton lunch est dans le frigo, oublie-le pas comme hier.",
        "Bon, là, on se grouille un peu, l'autobus attendra pas.",
        "Qui a laissé ses bottes au milieu de l'entrée? Encore.",
        "J'ai mis ça sur le calendrier du frigo, personne le regarde, hein?",
        "{other}, as-tu fini tes devoirs avant de t'installer?",
    ],
    "ado": [
        "Genre, quelqu'un peut arrêter de chanter dans la douche le matin?",
        "{other}, c'est full cringe ce que tu portes, juste pour dire.",
        "J'ai pas faim. Bon, peut-être un peu.",
        "Ma gang va au Tim après l'école, je peux-tu y aller?",
        "Le wifi est encore lent, c'est quoi l'affaire?",
    ],
    "enfant": [
        "{other}, pourquoi le ciel est bleu pis pas vert?",
        "Est-ce que les dinosaures avaient des chats?",
        "C'est vrai que si on avale une gomme, ça reste sept ans dans le ventre?",
        "{other}, regarde mon Lego, c'est une fusée qui va sur Mars!",
        "Est-ce qu'on peut avoir un chien? Juste un petit?",
    ],
}

REPLIES: dict[str, list[str]] = {
    "pere": [
        "Voyons donc. C'est ben correct de même.",
        "Demande à ta mère, elle a l'horaire.",
        "Ça dépend. As-tu demandé gentiment?",
        "Hmm. Laisse-moi finir mon café pis je te reviens là-dessus.",
        "Bonne question. La réponse courte : non.",
    ],
    "mere": [
        "On en reparle après le souper, là j'ai pas le temps.",
        "Oui, mais juste si ta chambre est rangée.",
        "Bon, ça, c'est une bonne nouvelle, au moins.",
        "Pas ce soir, mon cœur, il y a de l'école demain.",
        "Je vais l'écrire sur le calendrier, comme ça c'est clair.",
    ],
    "ado": [
        "Ok boomer.",
        "Pas rapport, mais oui, j'imagine.",
        "Genre... non?",
        "Laisse faire, je vais m'arranger.",
        "C'est pas si pire, finalement.",
    ],
    "enfant": [
        "Mais pourquoi?",
        "Wow! Pis après, qu'est-ce qui arrive?",
        "Moi aussi je veux!",
        "C'est pas juste!",
        "Hihi, t'es drôle!",
    ],
}

ROOM_OPENERS: dict[str, list[str]] = {
    "Cuisine": ["Ça sent bon, c'est quoi pour souper?", "Il reste-tu du lait?",
                "Qui a fini les céréales pis remis la boîte vide?"],
    "Salon": ["Qu'est-ce qu'on écoute?", "Tasse-toi un peu, il y a de la place pour deux.",
              "Y a-tu une game ce soir?"],
    "Salle de bain": ["Ça fait vingt minutes que t'es là!", "Quelqu'un a pris ma brosse à cheveux?"],
}

MONEY_OPENERS: dict[str, list[str]] = {
    "pere": ["Bon, va falloir se serrer la ceinture.", "J'ai regardé le compte... Kraft Dinner toute la semaine."],
    "mere": ["On est dans le rouge, faut couper quelque part.", "J'ai refait le budget trois fois, ça balance pas."],
    "ado": ["Genre, on est pauvres maintenant?", "Je pourrais me trouver une job au dépanneur."],
    "enfant": ["Pourquoi on achète plus les céréales avec des guimauves?", "Est-ce qu'on va devoir vendre la télé?"],
}
GRIEF_OPENERS: dict[str, list[str]] = {
    "pere": ["C'est tranquille, la maison, sans {absent}."],
    "mere": ["{absent} me manque tellement."],
    "ado": ["J'arrête pas de penser à {absent}."],
    "enfant": ["Est-ce que {absent} peut nous voir d'en haut?"],
}

REASONS: dict[str, list[str]] = {
    "epicerie": ["Le frigo est presque vide.", "Faut bien nourrir la gang."],
    "heures_sup": ["On a besoin de cash.", "Quelques heures de plus, ça va aider le budget."],
    "collation": ["J'ai un p'tit creux.", "Mon ventre gargouille."],
    "douche": ["Je me sens pas frais.", "Une douche, ça va me réveiller."],
    "tele": ["J'ai le goût de relaxer devant la télé.", "Il y a peut-être une game."],
    "ordi": ["J'ai un jeu à finir.", "Je veux checker un truc."],
    "jouer": ["Ma fusée Lego est pas finie!", "J'ai le goût de jouer."],
    "lire": ["Un bon livre, ça fait du bien.", "Je veux finir mon chapitre."],
    "telephone": ["Faut que je réponde à ma gang.", "Juste deux minutes sur mon téléphone."],
    "sieste": ["Je suis brûlé.", "Une p'tite sieste s'impose."],
    "jaser": ["Ça fait longtemps qu'on s'est parlé.", "J'ai quelque chose à raconter."],
    "flaner": ["Je sais pas trop quoi faire.", "Je tourne en rond un peu."],
    "couper": ["Faut du bois pour le feu.", "Chaque arbre, c'est de la place pour la maison."],
    "veiller": ["Rien de mieux qu'un feu de camp.", "Une petite veillée sous les étoiles."],
    "construire": ["Encore un mur et on y est.", "J'ai hâte de dormir au chaud."],
    "engager": ["On n'y arrivera jamais tout seuls.", "Ça va coûter cher, mais on va gagner des mois."],
}


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, latency_s: tuple[float, float] = (0.3, 1.2), invalid_rate: float = 0.0,
                 seed: int | None = None) -> None:
        self.latency_s = latency_s
        self.invalid_rate = invalid_rate
        self.rng = random.Random(seed)
        self._lock = threading.Lock()  # random.Random n'est pas garanti thread-safe

    def complete(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            delay = self.rng.uniform(*self.latency_s) if self.latency_s[1] > 0 else 0.0
            invalid = self.rng.random() < self.invalid_rate
            if invalid:
                text = "Euh... je sais pas trop, laisse-moi y penser."
            elif request.kind == "decision":
                text = self._decision(request)
            elif request.kind == "dialogue":
                text = self._dialogue(request)
            elif request.kind == "plan":
                text = self._plan(request)
            elif request.kind == "reflection":
                text = self._reflection(request)
            elif request.kind == "line":
                text = self._line(request)
            elif request.kind == "debrief":
                text = self._debrief(request)
            elif request.kind == "house_plan":
                text = self._house_plan(request)
            elif request.kind == "baby_talk":
                text = self._baby_talk(request)
            elif request.kind == "birth":
                text = self._birth(request)
            else:
                text = self._summary(request)
        if delay:
            time.sleep(delay)
        return LLMResponse(text=text, input_tokens=len(request.system + request.prompt) // 4,
                           output_tokens=len(text) // 4)

    def _decision(self, request: LLMRequest) -> str:
        options = request.meta.get("options", [])
        top = options[:3] or [{"action": "flaner", "target": None}]
        weights = [max(o.get("score", 1.0), 0.01) for o in top]
        choice = self.rng.choices(top, weights=weights, k=1)[0]
        reason = self.rng.choice(REASONS.get(choice["action"], ["Pourquoi pas."]))
        return json.dumps({"action": choice["action"], "target": choice.get("target"), "reason": reason},
                          ensure_ascii=False)

    def _dialogue(self, request: LLMRequest) -> str:
        participants = request.meta.get("participants", [])
        if len(participants) < 2:
            return json.dumps({"lines": []})
        room = request.meta.get("room", "")
        order = participants[:]
        self.rng.shuffle(order)
        first, second = order[0], order[1]

        departed = request.meta.get("departed") or []
        money = request.meta.get("money")
        pantry_days = request.meta.get("pantry_days")
        broke = (money is not None and money < 200) or (pantry_days is not None and pantry_days < 1)

        def opener(speaker: dict, other: dict) -> str:
            pool = OPENERS.get(speaker["id"], ["Salut {other}."])
            if departed and self.rng.random() < 0.5:
                pool = GRIEF_OPENERS.get(speaker["id"], ["{absent} me manque."])
            elif broke and self.rng.random() < 0.6:
                pool = MONEY_OPENERS.get(speaker["id"], ["L'argent manque."])
            elif room in ROOM_OPENERS and self.rng.random() < 0.35:
                pool = ROOM_OPENERS[room]
            absent = self.rng.choice(departed) if departed else ""
            return self.rng.choice(pool).format(other=other["name"], absent=absent)

        def reply(speaker: dict) -> str:
            return self.rng.choice(REPLIES.get(speaker["id"], ["Ah oui?"]))

        lines = [
            {"speaker": first["name"], "text": opener(first, second)},
            {"speaker": second["name"], "text": reply(second)},
        ]
        if len(order) > 2:
            lines.append({"speaker": order[2]["name"], "text": reply(order[2])})
        if self.rng.random() < 0.6:
            lines.append({"speaker": first["name"], "text": reply(first)})
        return json.dumps({"lines": lines}, ensure_ascii=False)

    def _summary(self, request: LLMRequest) -> str:
        events = request.meta.get("events", [])
        if not events:
            summary = "Rien de spécial ces temps-ci."
        else:
            picked = [events[0]] + ([events[-1]] if len(events) > 1 else [])
            # Retire l'horodatage « [HH:MM] » et garde le début de chaque événement
            parts = [e.split("] ", 1)[-1][:90].rstrip() for e in picked]
            summary = "En gros : " + " ; puis ".join(parts)
        return json.dumps({"summary": summary[:300]}, ensure_ascii=False)

    def _plan(self, request: LLMRequest) -> str:
        """3 à 5 activités tirées dans les plages libres, les favorites plus souvent."""
        slots = [tuple(s) for s in request.meta.get("slots", [])]
        catalog = request.meta.get("catalog", [])
        favorites = set(request.meta.get("favorites", []))
        if not slots or not catalog:
            return json.dumps({"intention": "", "plan": []})
        weights = [3.0 if o["action"] in favorites else 1.0 for o in catalog]
        times: set[int] = set()
        for _ in range(self.rng.randint(3, 5)):
            start, end = self.rng.choice(slots)
            times.add(start + self.rng.randrange(0, max(1, end - start - 10), 15))
        plan = []
        for minute in sorted(times):
            option = self.rng.choices(catalog, weights=weights, k=1)[0]
            plan.append({"time": f"{minute // 60:02d}:{minute % 60:02d}", "action": option["action"],
                         "target": option.get("target"),
                         "note": self.rng.choice(REASONS.get(option["action"], ["Ça me tente."]))})
        intention = self.rng.choice(INTENTIONS.get(request.meta.get("agent_id", ""), ["Une journée tranquille."]))
        if request.meta.get("replan"):
            intention = "Avec ce qui arrive, je change mes plans."
        return json.dumps({"intention": intention, "plan": plan}, ensure_ascii=False)

    def _reflection(self, request: LLMRequest) -> str:
        """Un constat selon les mots-clés de la journée, parfois un objectif pour demain."""
        events = request.meta.get("events", [])
        text = " ".join(events).lower()
        for words, insight, importance in INSIGHTS:
            if any(w in text for w in words):
                break
        else:
            insight, importance = "Une journée ordinaire, mais on est ensemble, c'est ça qui compte.", 3
        important = [n for n, e in enumerate(events, 1) if any(w in e.lower() for w in words)][:2] \
            if importance > 3 else []
        catalog = request.meta.get("catalog", [])
        goal = None
        if catalog and self.rng.random() < 0.6:
            option = self.rng.choice(catalog)
            goal = {"action": option["action"], "target": option.get("target"),
                    "why": self.rng.choice(REASONS.get(option["action"], ["Ça va me faire du bien."]))}
        return json.dumps({"insights": [{"text": insight, "importance": importance}],
                           "important": important, "goal": goal}, ensure_ascii=False)

    def _line(self, request: LLMRequest) -> str:
        """Une réplique : ouverture au premier tour, réponse ensuite, parfois une proposition."""
        meta = request.meta
        speaker = meta.get("speaker", {"id": "", "name": "?"})
        listeners = meta.get("listeners", [])
        lines = meta.get("lines", [])
        turn = meta.get("turn", 0)
        if not listeners:
            return json.dumps({"text": ""})
        last = lines[-1][0] if lines else None
        to = next((o for o in listeners if o["name"] == last), listeners[0])
        if turn == 0:
            departed = meta.get("departed") or []
            money, pantry = meta.get("money"), meta.get("pantry_days")
            pool = OPENERS.get(speaker["id"], ["Salut {other}."])
            if departed and self.rng.random() < 0.5:
                pool = GRIEF_OPENERS.get(speaker["id"], ["{absent} me manque."])
            elif ((money is not None and money < 200) or (pantry is not None and pantry < 1)) \
                    and self.rng.random() < 0.6:
                pool = MONEY_OPENERS.get(speaker["id"], ["L'argent manque."])
            elif meta.get("room") in ROOM_OPENERS and self.rng.random() < 0.35:
                pool = ROOM_OPENERS[meta["room"]]
            absent = self.rng.choice(departed) if departed else ""
            text = self.rng.choice(pool).format(other=to["name"], absent=absent)
        elif self.rng.random() < 0.2:
            text = self.rng.choice(PROPOSALS.get(speaker["id"], ["On fait quelque chose ensemble demain?"]))
        else:
            text = self.rng.choice(REPLIES.get(speaker["id"], ["Ah oui?"]))
        tension = self.rng.choice([0, 0, 0, 1, -1])
        if {speaker["id"], to.get("id")} == {"ado", "mere"} and self.rng.random() < 0.3:
            tension = 2  # le téléphone et l'heure du coucher, encore
        return json.dumps({
            "text": text, "to": to["name"], "end": turn >= 1 and self.rng.random() < 0.4,
            "thought": self.rng.choice(THOUGHTS.get(speaker["id"], ["Hmm."])),
            "affection": self.rng.choice([0, 0, 0, 1, 1, -1]), "tension": tension,
        }, ensure_ascii=False)

    def _debrief(self, request: LLMRequest) -> str:
        """Importance modeste ; parfois une promesse (Lego avec Félix, film le lendemain soir)."""
        people = request.meta.get("participants", [])
        names = [p["name"] for p in people]
        promises = []
        if len(people) >= 2 and self.rng.random() < 0.3:
            pair = people[:2]
            child = next((p for p in pair if p["id"] == "enfant"), None)
            action = "jouer" if child else "tele"
            promises.append({"who": [p["name"] for p in pair], "by": pair[0]["name"], "action": action,
                             "time": "19:30", "day": "demain",
                             "text": f"{pair[0]['name']} et {pair[1]['name']} : "
                                     + ("Lego après souper" if child else "un film ensemble") + " demain"})
        feelings = []
        if request.meta.get("with_feelings"):
            feelings = [{"from": a, "to": b, "affection": self.rng.choice([0, 1, 1, 2]), "tension": 0}
                        for a in names for b in names if a != b]
        return json.dumps({"importance": self.rng.randint(2, 5),
                           "summary": f"{' et '.join(names)} ont jasé de tout et de rien.",
                           "promises": promises, "feelings": feelings}, ensure_ascii=False)


    def _house_plan(self, request: LLMRequest) -> str:
        """Plan raisonnable : cuisine d'abord, puis salle de bain, chambre, salon, parfois un atelier."""
        couple = request.meta.get("couple", [])
        existing = request.meta.get("existing") or []
        r = self.rng
        if existing:
            rooms = [{"id": f"chambre_{len(existing) + 1}", "type": "chambre", "name": "Chambre du bébé",
                      "width": 3, "height": 3, "anchor": existing[-1], "side": r.choice(["est", "nord"]),
                      "why": "Il faut une place pour le bébé."}]
        else:
            rooms = [
                {"id": "cuisine", "type": "cuisine", "name": "Cuisine", "width": r.randint(5, 7),
                 "height": r.randint(4, 5), "anchor": None, "side": None, "why": "Manger au chaud avant tout."},
                {"id": "sdb", "type": "salle_de_bain", "name": "Salle de bain", "width": 3, "height": 3,
                 "anchor": "cuisine", "side": "ouest", "why": "Fini le baril d'eau froide."},
                {"id": "chambre", "type": "chambre", "name": "Chambre des maîtres", "width": r.randint(4, 5),
                 "height": 4, "anchor": "cuisine", "side": "est", "why": "Dormir dans un vrai lit."},
                {"id": "salon", "type": "salon", "name": "Salon", "width": r.randint(6, 8), "height": 5,
                 "anchor": "cuisine", "side": "nord", "why": "Une place pour recevoir la famille."},
            ]
            if r.random() < 0.5:
                rooms.append({"id": "atelier", "type": "atelier", "name": "Atelier", "width": 4, "height": 4,
                              "anchor": "chambre", "side": "nord", "why": "Pour bricoler les meubles nous-mêmes."})
        names = [p["name"] for p in couple] or ["Maxime", "Camille"]
        discussion = [
            {"speaker": names[0], "text": "Moi je vois une grande cuisine, avec un îlot. Ça va être malade!"},
            {"speaker": names[-1], "text": "On a-tu les moyens? On commence petit, on agrandira avec les paies."},
        ]
        vision = r.choice(["Une petite maison de bois, chaleureuse, qui grandira avec nous.",
                           "Un chalet simple au bord du bois, bâti de nos mains."])
        return json.dumps({"vision": vision, "discussion": discussion, "rooms": rooms}, ensure_ascii=False)


    def _baby_talk(self, request: LLMRequest) -> str:
        names = [p["name"] for p in request.meta.get("couple", [])] or ["Maxime", "Camille"]
        yes = self.rng.random() < 0.6
        discussion = [
            {"speaker": names[0], "text": "Je nous vois avec un petit, autour du feu. T'en penses quoi?"},
            {"speaker": names[-1], "text": "Moi aussi... mais on a-tu les moyens?" if not yes
             else "J'y pense depuis des semaines. On essaie!"},
        ]
        reason = "On est heureux, la maison avance." if yes else "On veut finir la maison avant."
        return json.dumps({"decision": "oui" if yes else "pas_maintenant", "reason": reason,
                           "discussion": discussion}, ensure_ascii=False)

    def _birth(self, request: LLMRequest) -> str:
        taken = {t.lower() for t in request.meta.get("taken", [])}
        names = [n for n in ("Florence", "Léo", "Rosalie", "Émile", "Alice", "Arthur", "Zoé", "Jacob")
                 if n.lower() not in taken] or ["Charlie"]
        traits = self.rng.sample(["curieux", "rieur", "têtu", "câlin", "énergique", "rêveur", "calme"], 3)
        return json.dumps({"name": self.rng.choice(names), "traits": traits,
                           "interests": self.rng.sample(["les dinosaures", "la musique", "grimper aux arbres",
                                                         "les animaux", "dessiner"], 2),
                           "speech_style": "Pose mille questions, invente des mots.",
                           "color": [self.rng.randint(80, 230) for _ in range(3)],
                           "hair": self.rng.choice([[90, 64, 44], [40, 30, 28], [210, 170, 90]])},
                          ensure_ascii=False)


PROPOSALS: dict[str, list[str]] = {
    "pere": ["On s'écoute un film demain soir? Je fais le popcorn.", "Tu veux m'aider avec le gazon demain?"],
    "mere": ["On relaxe sur le patio demain, juste nous deux?", "Demain soir, on se fait une soirée film."],
    "ado": ["Ok, ok, je vais tondre le gazon demain. Promis.", "On pourrait écouter une série ensemble demain."],
    "enfant": ["Tu joues aux Lego avec moi demain après souper? Dis oui!", "On se baigne demain?"],
}

THOUGHTS: dict[str, list[str]] = {
    "pere": ["J'espère qu'on va finir avant la game.", "Elle a l'air fatiguée, je devrais l'aider plus."],
    "mere": ["J'ai encore mille affaires à faire.", "Faudrait qu'on passe plus de temps ensemble."],
    "ado": ["Ils comprennent rien.", "Bon, c'est pas si pire de jaser des fois."],
    "enfant": ["J'espère qu'il va dire oui!", "Je veux juste jouer."],
}


INTENTIONS: dict[str, list[str]] = {
    "pere": ["Passer à travers la journée sans stress.", "Trouver du temps pour relaxer devant la game."],
    "mere": ["Tenir l'horaire et garder du temps pour moi.", "Que tout le monde soit nourri et à l'heure."],
    "ado": ["Survivre à l'école pis voir ma gang.", "Avoir la paix un peu dans ma chambre."],
    "enfant": ["Finir ma fusée Lego!", "Jouer le plus possible."],
}

# (mots-clés, constat, importance) : le premier qui correspond à la journée l'emporte
INSIGHTS: list[tuple[tuple[str, ...], str, int]] = [
    (("quittés", "décès"), "La maison est vide sans lui ou elle. Faut qu'on se serre les coudes.", 9),
    (("hôpital",), "J'ai eu peur pour la santé de la famille.", 7),
    (("mise à pied", "rouge", "pas assez d'argent"), "L'argent m'inquiète. Faut faire attention à chaque dépense.", 7),
    (("frigo est vide", "sans lunch"), "Manquer de bouffe, ça m'a ébranlé. Faut mieux planifier l'épicerie.", 6),
    (("a acheté",), "Ça fait du bien de se gâter un peu, on l'a mérité.", 5),
    (("bonne nouvelle :",), "Des fois, la vie nous fait des cadeaux.", 4),
    (("plan aujourd'hui",), "J'ai fait à peu près ce que je voulais aujourd'hui. Pas pire.", 3),
    (("jasé",), "Ça m'a fait du bien de jaser avec la famille aujourd'hui.", 4),
]
