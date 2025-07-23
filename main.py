import json
from ortools.sat.python import cp_model
import collections
from pathlib import Path

def load_config(config_path="schedule_config.json"):
    """
    Charge la configuration depuis un fichier JSON.
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"✅ Configuration chargée depuis {config_path}")
        return config
    except FileNotFoundError:
        print(f"❌ Fichier de configuration {config_path} non trouvé.")
        print("Veuillez créer le fichier avec la structure JSON appropriée.")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Erreur dans le fichier JSON: {e}")
        return None

def generate_cours_from_config(config):
    """
    Génère la liste des cours à partir de la configuration.
    """
    cours_a_planifier = []
    cours_id = 0
    
    for groupe_info in config["groupes_eleves"]:
        groupe_nom = groupe_info["nom"]
        niveau = groupe_info["niveau"]
        
        if niveau in config["curriculum"]:
            matieres_obligatoires = config["curriculum"][niveau]["matieres_obligatoires"]
            
            for matiere, nb_cours in matieres_obligatoires.items():
                for i in range(nb_cours):
                    cours_a_planifier.append((groupe_nom, matiere, cours_id))
                    cours_id += 1
    
    return cours_a_planifier

def validate_config(config):
    """
    Valide la cohérence de la configuration.
    """
    errors = []
    
    # Vérifier que tous les professeurs peuvent enseigner des matières existantes
    matieres_existantes = set(config["matieres"].keys())
    for prof_nom, prof_info in config["professeurs"].items():
        for matiere in prof_info["matieres_enseignees"]:
            if matiere not in matieres_existantes:
                errors.append(f"Le professeur {prof_nom} enseigne '{matiere}' qui n'existe pas dans les matières définies")
    
    # Vérifier que chaque matière du curriculum a au moins un professeur compétent
    for niveau, curriculum in config["curriculum"].items():
        for matiere in curriculum["matieres_obligatoires"]:
            profs_competents = [p for p, pinfo in config["professeurs"].items() 
                              if matiere in pinfo["matieres_enseignees"]]
            if not profs_competents:
                errors.append(f"Aucun professeur ne peut enseigner '{matiere}' requise pour le niveau {niveau}")
    
    # Vérifier que chaque matière a le bon type de salle disponible
    types_salles_disponibles = set(salle_info["type"] for salle_info in config["salles"].values())
    for matiere, matiere_info in config["matieres"].items():
        if matiere_info["salle_requise"] not in types_salles_disponibles:
            errors.append(f"La matière '{matiere}' requiert une salle de type '{matiere_info['salle_requise']}' mais aucune n'est disponible")
    
    return errors

def create_schedule_from_config(config_path="schedule_config.json"):
    """
    Génère un emploi du temps à partir d'un fichier de configuration JSON.
    """
    # Chargement de la configuration
    config = load_config(config_path)
    if not config:
        return
    
    # Validation de la configuration
    errors = validate_config(config)
    if errors:
        print("❌ Erreurs dans la configuration:")
        for error in errors:
            print(f"  - {error}")
        return
    
    print(f"📚 Génération de l'emploi du temps pour {config['etablissement']['nom']}")
    print(f"    Année scolaire: {config['etablissement']['annee_scolaire']}")
    
    # Extraction des données de configuration
    groupes_eleves = [g["nom"] for g in config["groupes_eleves"]]
    salles = config["salles"]
    professeurs = {p: pinfo["matieres_enseignees"] for p, pinfo in config["professeurs"].items()}
    infos_matieres = {m: {"salle_requise": minfo["salle_requise"]} for m, minfo in config["matieres"].items()}
    jours = config["planning"]["jours"]
    heures = config["planning"]["heures"]
    
    # Génération des cours à planifier
    cours_a_planifier = generate_cours_from_config(config)
    
    liste_salles = list(salles.keys())
    liste_professeurs = list(professeurs.keys())

    print(f"📊 Statistiques:")
    print(f"   - {len(groupes_eleves)} groupes d'élèves")
    print(f"   - {len(cours_a_planifier)} cours à planifier")
    print(f"   - {len(liste_professeurs)} professeurs")
    print(f"   - {len(liste_salles)} salles")
    print(f"   - {len(jours) * len(heures)} créneaux par jour")

    # ------------------
    # MODÈLE ET VARIABLES
    # ------------------
    model = cp_model.CpModel()
    assignments = {}
    
    for (groupe, matiere, cours_id) in cours_a_planifier:
        for prof in liste_professeurs:
            # Vérifier que le prof peut enseigner cette matière
            if matiere not in professeurs[prof]:
                continue
            
            # Vérifier les contraintes de disponibilité du professeur
            prof_info = config["professeurs"][prof]
            
            for salle in liste_salles:
                # Vérifier que la salle est du bon type
                type_salle_requis = infos_matieres[matiere]['salle_requise']
                if salles[salle]['type'] != type_salle_requis:
                    continue
                    
                for jour in jours:
                    # Vérifier si le professeur est disponible ce jour
                    if jour in prof_info["contraintes"]["jours_indisponibles"]:
                        continue
                        
                    for heure in heures:
                        # Vérifier si le professeur est disponible à cette heure
                        if heure in prof_info["contraintes"]["heures_indisponibles"]:
                            continue
                            
                        key = (groupe, matiere, cours_id, prof, salle, jour, heure)
                        assignments[key] = model.NewBoolVar(f'assign_{cours_id}_{prof}_{salle}_{jour}_{heure}')

    print(f"🔧 {len(assignments)} variables créées")

    # ------------------
    # CONTRAINTES
    # ------------------
    # C1: Chaque cours de la liste doit avoir lieu exactement une fois.
    for (groupe, matiere, cours_id) in cours_a_planifier:
        cours_vars = [assignments[key] for key in assignments if key[2] == cours_id]
        if cours_vars:
            model.AddExactlyOne(cours_vars)

    # C2: Un professeur ne peut donner qu'un cours à la fois.
    for prof in liste_professeurs:
        for jour in jours:
            for heure in heures:
                prof_vars = [assignments[key] for key in assignments 
                           if key[3] == prof and key[5] == jour and key[6] == heure]
                if prof_vars:
                    model.AddAtMostOne(prof_vars)

    # C3: Une salle ne peut être occupée que par un cours à la fois.
    for salle in liste_salles:
        for jour in jours:
            for heure in heures:
                salle_vars = [assignments[key] for key in assignments 
                            if key[4] == salle and key[5] == jour and key[6] == heure]
                if salle_vars:
                    model.AddAtMostOne(salle_vars)

    # C4: Un groupe d'élèves ne peut assister qu'à un cours à la fois.
    for groupe in groupes_eleves:
        for jour in jours:
            for heure in heures:
                groupe_vars = [assignments[key] for key in assignments 
                             if key[0] == groupe and key[5] == jour and key[6] == heure]
                if groupe_vars:
                    model.AddAtMostOne(groupe_vars)

    # ------------------
    # RÉSOLUTION
    # ------------------
    solver = cp_model.CpSolver()
    params = config["parametres_solveur"]
    solver.parameters.max_time_in_seconds = params["temps_max_seconds"]
    solver.parameters.log_search_progress = params["log_progression"]
    
    print("🔍 Recherche d'une solution...")
    status = solver.Solve(model)

    # ------------------
    # AFFICHAGE
    # ------------------
    if status == cp_model.OPTIMAL:
        print('✅ Solution optimale trouvée !')
    elif status == cp_model.FEASIBLE:
        print('✅ Solution faisable trouvée !')
    else:
        print(f"❌ Aucune solution trouvée. Statut: {solver.StatusName(status)}")
        
        # Diagnostics
        print(f"Nombre de conflits: {solver.NumConflicts()}")
        print(f"Nombre de branches: {solver.NumBranches()}")
        
        # Analyse des matières problématiques
        print("\n--- Analyse des contraintes ---")
        for matiere in set(c[1] for c in cours_a_planifier):
            profs_competents = [p for p in professeurs if matiere in professeurs[p]]
            cours_matiere = len([c for c in cours_a_planifier if c[1] == matiere])
            salles_compatibles = [s for s in salles if salles[s]["type"] == infos_matieres[matiere]["salle_requise"]]
            print(f"{matiere}: {cours_matiere} cours, {len(profs_competents)} prof(s), {len(salles_compatibles)} salle(s)")
        
        return

    # Préparation de la solution
    solution = collections.defaultdict(list)
    for key, var in assignments.items():
        if solver.Value(var) == 1:
            groupe, matiere, cours_id, prof, salle, jour, heure = key
            solution[groupe].append((jour, heure, matiere, prof, salle))
    
    # Affichage par classe
    for groupe in sorted(solution.keys()):
        print(f"\n--- Emploi du temps pour la classe {groupe} ---")
        schedule = sorted(solution[groupe], key=lambda x: (jours.index(x[0]), heures.index(x[1])))
        for item in schedule:
            jour, heure, matiere, prof, salle = item
            emoji = config["matieres"][matiere].get("emoji", "")
            print(f"{jour} {heure}: {matiere:<12} ({prof:<13}) dans {salle:<12} {emoji}")
    
    # Affichage des salles libres
    afficher_salles_libres(solution, config)
    
    # Vérification de la solution
    verifier_solution(solution, cours_a_planifier, professeurs, salles, infos_matieres, jours, heures)
    
    return solution

def afficher_salles_libres(solution, config):
    """
    Affiche les salles libres par créneau horaire.
    """
    print("\n" + "="*60)
    print("📊 DISPONIBILITÉ DES SALLES")
    print("="*60)
    
    jours = config["planning"]["jours"]
    heures = config["planning"]["heures"]
    salles = config["salles"]
    
    # Créer un dictionnaire des salles occupées par créneau
    salles_occupees = collections.defaultdict(set)
    for groupe, cours_list in solution.items():
        for jour, heure, matiere, prof, salle in cours_list:
            salles_occupees[(jour, heure)].add(salle)
    
    # Affichage par créneau
    for jour in jours:
        print(f"\n🗓️  {jour.upper()}")
        print("-" * 50)
        
        for heure in heures:
            creneau = (jour, heure)
            salles_occupees_creneau = salles_occupees.get(creneau, set())
            salles_libres = set(salles.keys()) - salles_occupees_creneau
            
            print(f"\n⏰ {heure}")
            
            # Salles occupées
            if salles_occupees_creneau:
                print("  🔴 Occupées:")
                for salle in sorted(salles_occupees_creneau):
                    # Trouver qui occupe cette salle
                    occupant = None
                    for groupe, cours_list in solution.items():
                        for j, h, mat, prof, s in cours_list:
                            if j == jour and h == heure and s == salle:
                                occupant = f"{groupe} - {mat} ({prof})"
                                break
                        if occupant:
                            break
                    
                    salle_type = salles[salle]["type"]
                    capacite = salles[salle].get("capacite", "?")
                    type_emoji = "💻" if salle_type == "computer_lab" else "🔬" if salle_type == "science_lab" else "📚"
                    print(f"     • {salle:<12} {type_emoji} (cap: {capacite}) → {occupant}")
            
            # Salles libres
            if salles_libres:
                print("  🟢 Libres:")
                # Grouper par type
                salles_par_type = collections.defaultdict(list)
                for salle in salles_libres:
                    salle_type = salles[salle]["type"]
                    salles_par_type[salle_type].append(salle)
                
                for type_salle, liste_salles in sorted(salles_par_type.items()):
                    type_emoji = "💻" if type_salle == "computer_lab" else "🔬" if type_salle == "science_lab" else "📚"
                    type_nom = {
                        "standard": "Standard",
                        "computer_lab": "Informatique",
                        "science_lab": "Sciences"
                    }.get(type_salle, type_salle)
                    
                    for salle in sorted(liste_salles):
                        capacite = salles[salle].get("capacite", "?")
                        equipements = ", ".join(salles[salle].get("equipements", []))
                        print(f"     • {salle:<12} {type_emoji} (cap: {capacite}) {type_nom}")
                        if equipements:
                            print(f"       └─ Équipements: {equipements}")
            else:
                print("  🔴 Toutes les salles sont occupées")
    
    # Statistiques globales
    print(f"\n" + "="*60)
    print("📈 STATISTIQUES D'OCCUPATION")
    print("="*60)
    
    total_creneaux = len(jours) * len(heures)
    total_salles = len(salles)
    total_creneaux_salles = total_creneaux * total_salles
    
    # Calculer le taux d'occupation par salle
    occupation_par_salle = collections.defaultdict(int)
    for creneau, salles_occ in salles_occupees.items():
        for salle in salles_occ:
            occupation_par_salle[salle] += 1
    
    print(f"\n🏢 Occupation par salle:")
    for salle in sorted(salles.keys()):
        nb_occupations = occupation_par_salle[salle]
        taux = (nb_occupations / total_creneaux) * 100
        barre = "█" * int(taux // 5) + "░" * (20 - int(taux // 5))
        salle_type = salles[salle]["type"]
        type_emoji = "💻" if salle_type == "computer_lab" else "🔬" if salle_type == "science_lab" else "📚"
        print(f"  {salle:<12} {type_emoji} │{barre}│ {taux:5.1f}% ({nb_occupations}/{total_creneaux})")
    
    # Taux global
    total_occupations = sum(len(salles_occ) for salles_occ in salles_occupees.values())
    taux_global = (total_occupations / total_creneaux_salles) * 100
    print(f"\n🎯 Taux d'occupation global: {taux_global:.1f}% ({total_occupations}/{total_creneaux_salles} créneaux-salles)")
    
    # Créneaux les plus/moins chargés
    occupation_par_creneau = {creneau: len(salles_occ) for creneau, salles_occ in salles_occupees.items()}
    if occupation_par_creneau:
        creneau_max = max(occupation_par_creneau.items(), key=lambda x: x[1])
        creneau_min = min(occupation_par_creneau.items(), key=lambda x: x[1])
        
        print(f"\n⚡ Créneau le plus chargé: {creneau_max[0][0]} {creneau_max[0][1]} ({creneau_max[1]}/{total_salles} salles)")
        print(f"💤 Créneau le moins chargé: {creneau_min[0][0]} {creneau_min[0][1]} ({creneau_min[1]}/{total_salles} salles)")


def verifier_solution(solution, cours_planifies, professeurs, salles, infos_matieres, jours, heures):
    """
    Vérifie si la solution générée respecte toutes les contraintes.
    """
    print("\n🔬 Vérification de la solution...")
    is_valid = True

    # Dictionnaires pour vérifier les conflits
    conflits_prof = collections.defaultdict(list)
    conflits_salle = collections.defaultdict(list)
    conflits_groupe = collections.defaultdict(list)
    
    cours_assignes = 0
    for groupe, assignations in solution.items():
        for jour, heure, matiere, prof, salle in assignations:
            cours_assignes += 1
            timeslot = (jour, heure)
            conflits_prof[prof].append(timeslot)
            conflits_salle[salle].append(timeslot)
            conflits_groupe[groupe].append(timeslot)

            # Test 1: Le professeur peut-il enseigner cette matière ?
            if matiere not in professeurs[prof]:
                print(f"❌ ERREUR Compétence: {prof} ne peut pas enseigner {matiere}")
                is_valid = False

            # Test 2: La salle est-elle du bon type ?
            salle_requise = infos_matieres[matiere]['salle_requise']
            if salles[salle]['type'] != salle_requise:
                print(f"❌ ERREUR Salle: {matiere} requiert '{salle_requise}' mais est dans {salle}")
                is_valid = False

    # Test 3: Tous les cours ont-ils été planifiés ?
    if cours_assignes != len(cours_planifies):
        print(f"❌ ERREUR Nombre: {len(cours_planifies)} cours à planifier, {cours_assignes} assignés")
        is_valid = False

    # Test 4-6: Conflits temporels
    for resource_type, conflicts_dict, resource_name in [
        ("professeurs", conflits_prof, "professeur"),
        ("salles", conflits_salle, "salle"),
        ("groupes", conflits_groupe, "groupe")
    ]:
        for resource, slots in conflicts_dict.items():
            slot_counts = collections.Counter(slots)
            for slot, count in slot_counts.items():
                if count > 1:
                    print(f"❌ ERREUR Conflit: {resource_name} '{resource}' a {count} cours simultanés à {slot}")
                    is_valid = False
            
    if is_valid:
        print("✅ Solution valide !")
        print(f"📈 Statistiques: {cours_assignes} cours planifiés avec succès")
    
    return is_valid

def export_schedule_to_json(solution, config, output_path="emploi_du_temps_genere.json"):
    """
    Exporte l'emploi du temps généré vers un fichier JSON.
    """
    if not solution:
        return
        
    export_data = {
        "etablissement": config["etablissement"],
        "date_generation": "2024-07-23",  # Vous pouvez utiliser datetime.now()
        "emploi_du_temps": {}
    }
    
    for groupe, cours_list in solution.items():
        export_data["emploi_du_temps"][groupe] = []
        for jour, heure, matiere, prof, salle in cours_list:
            export_data["emploi_du_temps"][groupe].append({
                "jour": jour,
                "heure": heure,
                "matiere": matiere,
                "professeur": prof,
                "salle": salle,
                "emoji": config["matieres"][matiere].get("emoji", "")
            })
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        print(f"💾 Emploi du temps exporté vers {output_path}")
    except Exception as e:
        print(f"❌ Erreur lors de l'export: {e}")

def export_salles_libres_to_json(solution, config, output_path="salles_libres.json"):
    """
    Exporte la disponibilité des salles vers un fichier JSON.
    """
    if not solution:
        return
    
    jours = config["planning"]["jours"]
    heures = config["planning"]["heures"]
    salles = config["salles"]
    
    # Créer un dictionnaire des salles occupées par créneau
    salles_occupees = collections.defaultdict(set)
    occupation_details = collections.defaultdict(dict)
    
    for groupe, cours_list in solution.items():
        for jour, heure, matiere, prof, salle in cours_list:
            creneau = f"{jour} {heure}"
            salles_occupees[(jour, heure)].add(salle)
            occupation_details[creneau][salle] = {
                "groupe": groupe,
                "matiere": matiere,
                "professeur": prof
            }
    
    export_data = {
        "etablissement": config["etablissement"],
        "date_generation": "2024-07-23",
        "disponibilite_salles": {},
        "statistiques": {
            "total_salles": len(salles),
            "total_creneaux": len(jours) * len(heures),
            "occupation_par_salle": {}
        }
    }
    
    # Données par créneau
    for jour in jours:
        for heure in heures:
            creneau = f"{jour} {heure}"
            salles_occupees_creneau = salles_occupees.get((jour, heure), set())
            salles_libres = set(salles.keys()) - salles_occupees_creneau
            
            export_data["disponibilite_salles"][creneau] = {
                "jour": jour,
                "heure": heure,
                "salles_occupees": [],
                "salles_libres": []
            }
            
            # Salles occupées avec détails
            for salle in sorted(salles_occupees_creneau):
                details = occupation_details[creneau].get(salle, {})
                export_data["disponibilite_salles"][creneau]["salles_occupees"].append({
                    "nom": salle,
                    "type": salles[salle]["type"],
                    "capacite": salles[salle].get("capacite"),
                    "occupe_par": details
                })
            
            # Salles libres avec détails
            for salle in sorted(salles_libres):
                export_data["disponibilite_salles"][creneau]["salles_libres"].append({
                    "nom": salle,
                    "type": salles[salle]["type"],
                    "capacite": salles[salle].get("capacite"),
                    "equipements": salles[salle].get("equipements", [])
                })
    
    # Statistiques d'occupation par salle
    total_creneaux = len(jours) * len(heures)
    for salle in salles.keys():
        nb_occupations = sum(1 for salles_occ in salles_occupees.values() if salle in salles_occ)
        taux = (nb_occupations / total_creneaux) * 100
        export_data["statistiques"]["occupation_par_salle"][salle] = {
            "occupations": nb_occupations,
            "total_creneaux": total_creneaux,
            "taux_occupation": round(taux, 1)
        }
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        print(f"🏢 Disponibilité des salles exportée vers {output_path}")
    except Exception as e:
        print(f"❌ Erreur lors de l'export des salles: {e}")


if __name__ == '__main__':
    # Génération de l'emploi du temps
    solution = create_schedule_from_config("schedule_config.json")
    
    # Export optionnel vers JSON
    if solution:
        config = load_config("schedule_config.json")
        export_schedule_to_json(solution, config)
        export_salles_libres_to_json(solution, config)