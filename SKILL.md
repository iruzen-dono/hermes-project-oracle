---
name: hermes-project-oracle
description: "Analyse un projet et génère des fichiers de contexte agent."
version: 1.0.0
author: Iruzen & Hermes Agent
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [project-analysis, onboarding, context-setup, architecture, documentation]
    category: software-development
    related_skills: [agents-md, project-specification, legacy-project-audit, context-engineering]
---

# Hermes Project Oracle Skill

Analyse en profondeur n'importe quel projet et génère des fichiers de contexte (AGENTS.md, CLAUDE.md, note Obsidian) pour qu'un agent comprenne instantanément l'architecture, les conventions et les points d'entrée.

## When to Use

- Première fois sur un projet — génère son AGENTS.md
- Projet avec conventions implicites que les agents ne captent pas
- Transition entre projets — switch de contexte propre
- Documentation d'architecture dans Obsidian

## Prerequisites

- Python 3.11+
- git (optionnel, pour le contexte git dans le scan)
- Obsidian vault (optionnel, pour `oracle_vault.py`)

## How to Run

### Phase 1 — Scan

```bash
python <skill_dir>/scripts/oracle_scan.py --path <projet> --output .oracle/
```

Retourne un JSON structuré avec langage, framework, build system, arborescence, dépendances, conventions, routes API.

### Phase 2 — Generate

```bash
python <skill_dir>/scripts/oracle_generate.py \
  --scan .oracle/scan-report.json \
  --output <projet>/AGENTS.md \
  --template agents-md
```

Templates disponibles : `agents-md`, `claude-md`, `obsidian`, `full`.

### Phase 3 — Vault (optionnel)

```bash
python <skill_dir>/scripts/oracle_vault.py \
  --scan .oracle/scan-report.json
```

## Quick Reference

| Script | Rôle | Output |
|--------|------|--------|
| `oracle_scan.py` | Scan complet du projet | JSON structuré |
| `oracle_generate.py` | Génération context files | AGENTS.md / CLAUDE.md |
| `oracle_vault.py` | Push note Obsidian | Note dans vault |

## Procedure

1. **Demande** à l'utilisateur de quoi parle le projet (le scan détecte la stack, pas l'intention)
2. **Scan** avec `oracle_scan.py --path <projet> --output .oracle/`
3. **Analyse** le rapport : entry points, structure données, flux, conventions, footguns
4. **Génère** le fichier de contexte avec `oracle_generate.py`
5. **Valide** : `cat AGENTS.md | head -20` — le projet a-t-il l'air bien décrit ?
6. **Propose** vault : "Tu veux que je pousse ça dans le vault aussi ?"

### Options avancées

- `--depth 3` — contrôle la profondeur d'arborescence (défaut: 3)
- `--skip-gitignore` — inclut les dossiers git-ignorés
- `--template full` — génère tous les formats en une passe
- Combine avec `context-engineering` skill pour optimiser la session

## Pitfalls

- **AGENTS.md existant** : ne pas écraser sans demander — le projet en a peut-être un fait main
- **Gros projets (>10K fichiers)** : le scan peut prendre 5-10s. Préviens l'utilisateur.
- **Pas de détection d'intention** : le scan détecte la stack technique, pas le business — demande toujours "c'est quoi ce projet ?"
- **Spring Boot + Kotlin** : détecté comme Kotlin+Spring, pas juste "Java"
- **Monorepo** : scanner à la racine ou au niveau du module ? Demande à l'utilisateur

## Verification

- `cat AGENTS.md` — la structure, les conventions et les entry points sont-ils justes ?
- Lance une tâche simple sur le projet pour vérifier que le contexte est chargé
- Vérifie qu'aucun secret/path absolu n'a fuité dans le fichier généré
