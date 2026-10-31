"""Scénarios N1 à N3 : les fondamentaux, les actions, l'enchaînement. Chacun s'inscrit dans
`SCENARIOS` par `@scenario`, dans l'ordre où il est écrit."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scenario_kit import LIMIT_WORDS, Ctx, Verdict, fold, says, scenario

# --------------------------------------------------------------------------- N1 fondamentaux


@scenario("n1-capitale", 1, "Connaissance simple", "« Porto-Novo », sans plan")
async def capital(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Quelle est la capitale du Bénin ?")
    return Verdict(says(turn, "porto-novo") and not turn.plans, turn.text[:160])


@scenario("n1-calcul", 1, "Calcul mental", "17 × 23 = 391")
async def mental(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Combien font 17 fois 23 ?")
    return Verdict("391" in turn.text, turn.text[:160])


@scenario("n1-fautes", 1, "Question pleine de fautes", "comprend « virus » et « bactérie »")
async def typos(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("kel é la diférance antre un virus é une bactéri ? répon en 2 frase")
    ok = says(turn, "virus") and says(turn, "bacterie") and says(turn, "cellul", "vivant")
    return Verdict(ok, turn.text[:200])


@scenario("n1-familier", 1, "Registre familier", "se présente comme Jarvis")
async def casual(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("t'es qui toi ?")
    return Verdict(says(turn, "jarvis"), turn.text[:160])


@scenario("n1-format", 1, "Consigne de format", "exactement 3 puces")
async def bullet_list(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Donne-moi exactement trois fruits rouges, en liste à puces, sans phrase.")
    bullets = [line for line in turn.text.splitlines() if re.match(r"\s*([-*•]|\d+[.)])\s", line)]
    return Verdict(len(bullets) == 3, f"{len(bullets)} puces : {turn.text[:160]!r}")


@scenario("n1-ambigu", 1, "Demande floue", "demande une précision, rien n'est lancé")
async def ambiguous(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Réserve-moi ça pour demain.")
    asks = "?" in turn.text or says(turn, "dis-moi", "precise", "peux-tu", "il me manque")
    return Verdict(asks and not turn.plans, turn.text[:200])


@scenario("n1-heure", 1, "Fuseaux et heure d'été", "heure de Tokyo juste pour aujourd'hui")
async def time_zones(ctx: Ctx) -> Verdict:
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    noon = datetime(today.year, today.month, today.day, 12, tzinfo=ZoneInfo("Europe/Paris"))
    hour = noon.astimezone(ZoneInfo("Asia/Tokyo")).hour
    turn = await ctx.ask("Quelle heure est-il à Tokyo quand il est midi à Paris aujourd'hui ?")
    ok = bool(re.search(rf"\b{hour}\s*(h|heures|:00)", turn.text))
    return Verdict(ok, f"attendu {hour} h : {turn.text[:160]}")


@scenario("n1-conversation", 1, "Mémoire de la conversation", "se souvient de la boisson")
async def short_memory(ctx: Ctx) -> Verdict:
    first = await ctx.ask("Je m'appelle Octave et j'adore le thé à la menthe.")
    turn = await ctx.ask("Qu'est-ce que j'adore boire ?", conversation=first.conversation)
    return Verdict(says(turn, "menthe"), turn.text[:160])


@scenario("n1-memoire", 1, "Mémoire d'une session à l'autre", "fait retenu, rappelé ailleurs")
async def long_memory(ctx: Ctx) -> Verdict:
    await ctx.ask("Retiens ceci pour plus tard : mon vélo est rouge.")
    stored = []
    for _ in range(120):
        stored = await ctx.services.memory.items(query="vélo")
        if stored:
            break
        await asyncio.sleep(0.5)
    turn = await ctx.ask("De quelle couleur est mon vélo ?")
    detail = f"en mémoire : {[s.content for s in stored][:2]} ; réponse : {turn.text[:120]}"
    return Verdict(bool(stored) and says(turn, "rouge"), detail)


@scenario("n1-honnete", 1, "Ne pas inventer", "« je ne sais pas » plutôt qu'un prénom inventé")
async def honest(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Comment s'appelle ma sœur ?")
    ok = says(
        turn,
        "ne sais pas",
        "ne le sais pas",
        "ne connais pas",
        "pas encore",
        "ne m'as pas",
        "aucune information",
        "je n'ai pas",
        "pas d'information",
    )
    return Verdict(ok, turn.text[:200])


# --------------------------------------------------------------------------- N2 actions


@scenario("n2-lire", 2, "Lire un fichier", "contenu juste, sans validation")
async def read_file(ctx: Ctx) -> Verdict:
    ctx.write("notes/recette.txt", "Crêpes : 250 g de farine, 4 œufs, 50 cl de lait.\n")
    turn = await ctx.ask("Que contient mon fichier notes/recette.txt ?")
    ok = "lire_fichier" in turn.tools and says(turn, "farine") and not turn.plans
    return Verdict(ok, turn.text[:160])


@scenario("n2-dossier", 2, "Lister un dossier", "nomme les deux fichiers")
async def list_folder(ctx: Ctx) -> Verdict:
    ctx.write("projets/demo/serveur.py", "print('ok')\n")
    ctx.write("projets/demo/LISEZMOI.md", "# Démo\n")
    turn = await ctx.ask("Quels fichiers y a-t-il dans mon dossier projets/demo ?")
    ok = "lister_dossier" in turn.tools and says(turn, "serveur.py") and says(turn, "lisezmoi")
    return Verdict(ok, turn.text[:160])


@scenario("n2-ecrire", 2, "Écrire un fichier", "rien avant validation, contenu juste après")
async def write_file(ctx: Ctx) -> Verdict:
    target = ctx.path("notes/courses.md")
    turn = await ctx.ask(
        "Crée le fichier ~/notes/courses.md avec la liste : thé vert, miel, citron."
    )
    before = target.exists()
    statuses = await ctx.approve_all(turn)
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    ok = bool(turn.plans) and not before and "miel" in content.lower()
    return Verdict(ok, f"avant validation : {before} ; plans {statuses} ; contenu {content!r}")


@scenario("n2-web", 2, "Recherche web", "« Cotonou », par la recherche")
async def web_search(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Cherche sur le web quelle est la capitale économique du Bénin.")
    ok = "recherche_web" in turn.tools and says(turn, "cotonou") and not turn.plans
    return Verdict(ok, turn.text[:160])


@scenario("n2-page", 2, "Lire une page web", "résume l'article (baobab, mille ans)")
async def read_page(ctx: Ctx) -> Verdict:
    turn = await ctx.ask(f"Résume en une phrase la page http://127.0.0.1:{ctx.port}/article")
    ok = says(turn, "baobab") and says(turn, "mille", "1000", "1 000")
    return Verdict(ok, turn.text[:200])


@scenario("n2-code", 2, "Calcul par du code", "333 833 500, dans le bac à sable")
async def sandbox_code(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Calcule avec du code la somme des carrés des entiers de 1 à 1000.")
    digits = re.sub(r"[\s \xa0.,]", "", turn.text)
    ok = "executer_code" in turn.tools and "333833500" in digits and not turn.plans
    return Verdict(ok, turn.text[:160])


@scenario(
    "n2-automatisation", 2, "Créer une automatisation", "tous les jours à 8 h, après validation"
)
async def daily(ctx: Ctx) -> Verdict:
    await ctx.clear_automations()
    turn = await ctx.ask("Rappelle-moi tous les matins à 8 h de boire un grand verre d'eau.")
    await ctx.approve_all(turn)
    records = await ctx.services.automations.all()
    whens = [r.when for r in records]
    return Verdict(
        any("8 h 00" in w and "jours" in w for w in whens), f"{whens} ; {turn.text[:100]}"
    )


@scenario("n2-rappel", 2, "Rappel ponctuel", "demain à 9 h, une seule fois")
async def tomorrow(ctx: Ctx) -> Verdict:
    from ojarvis.core.clock import local_timezone, utc_now  # noqa: PLC0415

    await ctx.clear_automations()
    turn = await ctx.ask("Demain à 9 h, rappelle-moi d'appeler le plombier.")
    await ctx.approve_all(turn)
    records = await ctx.services.automations.all()
    day = (utc_now().astimezone(local_timezone()) + timedelta(days=1)).date()
    expected = f"{day.isoformat()}T09:00"
    got = [getattr(getattr(r, "trigger", None), "quand", None) for r in records]
    ok = any(getattr(q, "le", None) == expected for q in got) and all(r.one_shot for r in records)
    return Verdict(ok and bool(records), f"attendu {expected} : {[r.when for r in records]}")


@scenario(
    "n2-commande",
    2,
    "Lancer une commande",
    "limite annoncée (mode shell à venir)",
    awaits_shell=True,
)
async def command(ctx: Ctx) -> Verdict:
    turn = await ctx.ask("Lance la commande ls -la dans mon dossier personnel.")
    plans = [await ctx.services.plans.get(p) for p in turn.plans]
    # Détour sûr accepté : lister le dossier, directement ou par un plan de simple lecture.
    reading_only = all(p.max_level <= 1 for p in plans)
    listed = "lister_dossier" in turn.tools or any(
        s.tool == "lister_dossier" for p in plans for s in p.steps
    )
    ok = reading_only and (listed or says(turn, *LIMIT_WORDS))
    return Verdict(ok, f"outils {turn.tools} ; plans {len(plans)} : {turn.text[:160]}")


@scenario("n2-application", 2, "Ouvrir puis fermer une application", "calculatrice", desktop=True)
async def application(ctx: Ctx) -> Verdict:
    from ojarvis.desktop import apps  # noqa: PLC0415

    await ctx.os_control(True)
    try:
        opened = await ctx.ask("Ouvre la calculatrice.")
        await ctx.approve_all(opened)
        await asyncio.sleep(2.0)
        running = bool(apps._processes("gnome-calculator"))
        closed = await ctx.ask("Ferme la calculatrice.")
        await ctx.approve_all(closed)
        await asyncio.sleep(1.0)
        gone = not apps._processes("gnome-calculator")
    finally:
        await ctx.os_control(False)
    return Verdict(running and gone, f"ouverte : {running} ; fermée : {gone}")


# --------------------------------------------------------------------------- N3 enchaînement


@scenario("n3-boutique", 3, "Navigateur : formulaire", "cherche dans la boutique, rend 4,50 €")
async def shop(ctx: Ctx) -> Verdict:
    turn = await ctx.ask(
        f"Va sur http://127.0.0.1:{ctx.port}/boutique, cherche « thé vert » avec le formulaire "
        "de recherche et dis-moi son prix."
    )
    statuses = await ctx.approve_all(turn)
    results = [(await ctx.services.plans.get(p)).result or "" for p in turn.plans]
    ok = any("4,50" in r for r in results) or "4,50" in turn.text
    return Verdict(ok, f"plans {statuses} ; {(results or [turn.text])[-1][:160]!r}")


@scenario("n3-chercher-ecrire", 3, "Chercher puis écrire", "« 1960 » dans ~/notes/benin.md")
async def search_then_write(ctx: Ctx) -> Verdict:
    target = ctx.path("notes/benin.md")
    turn = await ctx.ask(
        "Cherche l'année de l'indépendance du Bénin et écris-la dans ~/notes/benin.md."
    )
    statuses = await ctx.approve_all(turn)
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    return Verdict("1960" in content, f"plans {statuses} ; contenu {content[:120]!r}")


@scenario("n3-calculer-ecrire", 3, "Calculer puis écrire", "les 10 premiers nombres premiers")
async def compute_then_write(ctx: Ctx) -> Verdict:
    target = ctx.path("notes/premiers.txt")
    turn = await ctx.ask(
        "Calcule avec du code les dix premiers nombres premiers et enregistre-les dans "
        "~/notes/premiers.txt."
    )
    statuses = await ctx.approve_all(turn)
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    numbers = [int(n) for n in re.findall(r"\d+", content)]
    ok = numbers[:10] == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
    return Verdict(ok, f"plans {statuses} ; contenu {content[:120]!r}")


@scenario("n3-contexte", 3, "Suite d'une demande", "« ce fichier » compris, deux mots écrits")
async def follow_up(ctx: Ctx) -> Verdict:
    target = ctx.path("notes/projet.txt")
    first = await ctx.ask("Crée le fichier ~/notes/projet.txt avec le mot alpha.")
    await ctx.approve_all(first)
    second = await ctx.ask(
        "Ajoute le mot bêta à la fin de ce fichier.", conversation=first.conversation
    )
    statuses = await ctx.approve_all(second)
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    ok = "alpha" in content and "bêta" in content
    return Verdict(ok, f"suite : plans {statuses} ; contenu {content!r} ; {second.text[:120]!r}")


DOUBT_WORDS = (
    "simulation",
    "pas la preuve",
    "n'ai execute aucune",
    "je n'ai pas execute",
    "pas reellement",
    "aucun fichier n'a ete cree",
    "n'a pas ete cree",
)


@scenario("n3-assumer", 3, "Assumer ce qu'il a fait", "compte rendu sûr de lui, fichier confirmé")
async def owns_its_actions(ctx: Ctx) -> Verdict:
    """Vu chez Octave : après un plan réussi, Jarvis doutait de ses propres outils, puis niait
    avoir créé le fichier."""
    target = ctx.path("Téléchargements/rapport-audio.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    await ctx.os_control(True)
    first = await ctx.ask("Je viens d'activer le contrôle du PC.")
    turn = await ctx.ask(
        "Écris un rapport d'incident dans ~/Téléchargements/rapport-audio.txt : la clé Groq est "
        "présente mais les messages vocaux ne sont pas transcrits.",
        conversation=first.conversation,
    )
    statuses = await ctx.approve_all(turn)
    summaries = [(await ctx.services.plans.get(p)).result or "" for p in turn.plans]
    check = await ctx.ask("Le fichier est bien créé ?", conversation=first.conversation)
    doubtful = [w for w in DOUBT_WORDS if any(w in fold(t) for t in [*summaries, check.text])]
    ok = target.exists() and "done" in statuses and not doubtful and says(check, "oui", "cree")
    detail = f"plans {statuses} ; doutes {doubtful} ; réponse {check.text[:120]!r}"
    return Verdict(ok, detail)


@scenario("n3-dependance", 3, "Lire, extraire, écrire", "la valeur de « port » recopiée")
async def dependency(ctx: Ctx) -> Verdict:
    ctx.write("notes/config.json", json.dumps({"nom": "atelier", "port": 8421}))
    target = ctx.path("notes/port.txt")
    turn = await ctx.ask(
        "Lis ~/notes/config.json et crée ~/notes/port.txt qui contient seulement la valeur de port."
    )
    statuses = await ctx.approve_all(turn)
    content = target.read_text(encoding="utf-8").strip() if target.exists() else ""
    return Verdict(content == "8421", f"plans {statuses} ; contenu {content!r}")


@scenario("n3-agent", 3, "Déléguer à un agent", "l'agent de recherche cherche et rend compte")
async def delegate(ctx: Ctx) -> Verdict:
    turn = await ctx.ask(
        "Confie à ton agent de recherche cette tâche : en quelle année le Bénin a-t-il pris son "
        "nom actuel ? Puis réponds-moi en une phrase."
    )
    runs = await ctx.services.orchestrator.runs(limit=1)
    run = runs[0] if runs else None
    ok = (
        "deleguer" in turn.tools and run is not None and run.status == "fini" and says(turn, "1975")
    )
    return Verdict(ok, f"mission {run.status if run else '?'} ; {turn.text[:160]}")


@scenario("n3-skill", 3, "Créer un skill puis s'en servir", "testé, activé (double), utilisé")
async def make_skill(ctx: Ctx) -> Verdict:
    turn = await ctx.ask(
        "Crée-toi un skill qui compte le nombre de jours entre deux dates au format AAAA-MM-JJ, "
        "avec ses tests."
    )
    statuses = await ctx.approve_all(turn, double=True)
    active = [r for r in ctx.services.skills.records() if r.status == "actif"]
    answer = await ctx.ask(
        "Combien de jours y a-t-il entre le 1er janvier 2026 et le 15 octobre 2026 ?"
    )
    used = [t for t in answer.tools if "__" in t]
    ok = bool(active) and bool(used) and "287" in answer.text
    return Verdict(ok, f"activation {statuses} ; outils {used} ; {answer.text[:100]!r}")


@scenario("n3-cycle", 3, "Créer puis supprimer un rappel", "suppression en double confirmation")
async def automation_cycle(ctx: Ctx) -> Verdict:
    await ctx.clear_automations()
    first = await ctx.ask("Rappelle-moi chaque lundi à 18 h d'aller au sport.")
    await ctx.approve_all(first)
    created = len(await ctx.services.automations.all())
    second = await ctx.ask("Finalement, supprime ce rappel.", conversation=first.conversation)
    levels = [(await ctx.services.plans.get(p)).max_level for p in second.plans]
    await ctx.approve_all(second, double=True)
    left = len(await ctx.services.automations.all())
    ok = created == 1 and left == 0 and 3 in levels
    return Verdict(ok, f"créé {created}, niveaux {levels}, restant {left} ; {second.text[:120]!r}")
