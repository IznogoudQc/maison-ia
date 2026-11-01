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

REASONS: dict[str, list[str]] = {
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

        def opener(speaker: dict, other: dict) -> str:
            pool = OPENERS.get(speaker["id"], ["Salut {other}."])
            if room in ROOM_OPENERS and self.rng.random() < 0.35:
                pool = ROOM_OPENERS[room]
            return self.rng.choice(pool).format(other=other["name"])

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
