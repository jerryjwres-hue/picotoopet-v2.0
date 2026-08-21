from __future__ import annotations

import argparse
import json
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    args = parser.parse_args()
    project = Path(args.project_dir)
    project.mkdir(parents=True, exist_ok=True)

    write_json(project / "project.json", {"schema_version": "1.0", "project_id": "malamute_office_director_001", "title": "PVP CI Fixture"})
    write_json(project / "story/story_contract.json", {"project_id": "malamute_office_director_001", "review_state": "APPROVED", "beats": [{"beat_id": "B01"}, {"beat_id": "B02"}, {"beat_id": "B03"}]})
    write_json(project / "assets/DOG_A.character.json", {"character_id": "DOG_A", "display_name": "DOG_A"})
    write_json(project / "assets/identity_registry.json", {"assets": {"DOG_A_REF": {"character_id": "DOG_A", "sha256": "ci-fixture"}}})
    shots = []
    for index in range(1, 4):
        shot_id = f"SHOT_{index:03d}"
        shots.append(shot_id)
        write_json(project / f"shots/{shot_id}.json", {"shot_id": shot_id, "location": "OFFICE_A", "subjects": {"asset_ids": ["DOG_A"]}, "primary_action": f"action-{index}"})
        write_json(project / f"blocking/{shot_id}.blocking.json", {"shot_id": shot_id, "status": "RESOLVED"})
    write_json(project / "storyboard/storyboard_manifest.json", {"shots": shots})
    write_json(project / "animatic/animatic_manifest.json", {"status": "APPROVED"})
    write_json(project / "production/production_plan.json", {"shots": [{"shot_id": shot_id, "engine": "wan"} for shot_id in shots]})
    print(f"N6E3_CI_FIXTURE=PASS {project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
