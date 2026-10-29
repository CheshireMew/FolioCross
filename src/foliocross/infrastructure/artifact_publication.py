"""Recoverable publication of immutable export versions and optional delivery copies."""

import os
import shutil
from pathlib import Path

from .repository import json_text, sha256_file, utc_now


def finish_publication(repository, publication_id: str) -> dict:
    workspace = repository.workspace
    with workspace.transaction(immediate=True) as connection:
        row = connection.execute(
            "SELECT * FROM export_publications WHERE id=?", (publication_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Export publication not found")
        item = dict(row)
        artifact = Path(workspace.resolve_path(item["artifact_path"]))
        delivery = Path(workspace.resolve_path(item["delivery_path"]))
        if item["status"] == "completed":
            return {
                "path": str(delivery),
                "artifact_id": publication_id,
                "artifact_path": str(artifact),
            }
        stage = Path(workspace.resolve_path(item["stage_path"]))
        if stage.is_file():
            if sha256_file(stage) != item["sha256"]:
                raise ValueError("Export staging checksum mismatch")
            os.replace(stage, artifact)
        if not artifact.is_file() or sha256_file(artifact) != item["sha256"]:
            raise ValueError("Export version is missing or corrupted")
        newer_delivery = connection.execute(
            "SELECT 1 FROM export_publications WHERE delivery_path=? AND status='completed' AND rowid>(SELECT rowid FROM export_publications WHERE id=?)",
            (item["delivery_path"], publication_id),
        ).fetchone()
        if delivery != artifact and not newer_delivery:
            delivery.parent.mkdir(parents=True, exist_ok=True)
            delivery_stage = delivery.with_name(f".{delivery.name}.{publication_id}.partial")
            shutil.copyfile(artifact, delivery_stage)
            with delivery_stage.open("rb+") as stream:
                os.fsync(stream.fileno())
            os.replace(delivery_stage, delivery)
        # The receipt and all consumer-visible records commit together. A crash
        # after a rename replays this same publication, with the same identity.
        connection.execute(
            "INSERT INTO artifacts(id,job_id,kind,format,path,sha256,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                publication_id,
                item["job_id"],
                "translation",
                item["format"],
                item["artifact_path"],
                item["sha256"],
                json_text(
                    {
                        "delivery_path": item["delivery_path"],
                        "delivery_superseded": bool(newer_delivery),
                    }
                ),
                item["created_at"],
            ),
        )
        connection.execute(
            "UPDATE export_publications SET status='completed',error_message=NULL WHERE id=?",
            (publication_id,),
        )
        repository._insert_event(
            connection, item["job_id"], "artifact.published", {"artifact_id": publication_id}
        )
        return {
            "path": str(delivery),
            "artifact_id": publication_id,
            "artifact_path": str(artifact),
        }


def publish_export(repository, *, publication_id, job_id, format_name, stage, artifact, delivery):
    with repository.workspace.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO export_publications(id,job_id,format,stage_path,artifact_path,delivery_path,sha256,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                publication_id,
                job_id,
                format_name,
                repository.workspace.store_path(stage),
                repository.workspace.store_path(artifact),
                repository.workspace.store_path(delivery),
                sha256_file(stage),
                utc_now(),
            ),
        )
    return finish_publication(repository, publication_id)


def recover_publications(repository):
    with repository.workspace.session() as connection:
        pending = connection.execute(
            "SELECT id FROM export_publications WHERE status='pending' ORDER BY created_at"
        ).fetchall()
    for row in pending:
        try:
            finish_publication(repository, row[0])
        except (OSError, ValueError) as error:
            # Unavailable external delivery directories must not prevent opening
            # the workspace. Keep the version and pending receipt for next retry.
            with repository.workspace.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE export_publications SET error_message=? WHERE id=?",
                    (str(error), row[0]),
                )
