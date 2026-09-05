"""User-facing FolioCross errors."""

from __future__ import annotations

ERROR_MESSAGES_EN = {
    "api_key_missing": "No API key was found for this model profile. Add it in Settings or set the configured environment variable.",
    "background_operation_active": "This book already has a background operation queued or running. Wait for it to finish and try again.",
    "background_operation_not_queued": "The background operation is no longer queued.",
    "book_already_imported": "This book is already in FolioCross. The existing copy was left unchanged.",
    "book_not_found": "The requested book could not be found.",
    "budget_exceeded": "The configured budget limit has been reached. Adjust the limit before resuming.",
    "calibre_failed": "Calibre could not convert this book. See the job log for details.",
    "calibre_missing": "Calibre is not configured or ebook-convert could not be found.",
    "calibre_timeout": "The ebook conversion timed out.",
    "dependency_missing": "A required local dependency is missing. Run the environment check for details.",
    "docx_document_missing": "The DOCX file does not contain word/document.xml.",
    "docx_mapping_incomplete": "Some DOCX paragraphs no longer match their original locations, so export was stopped.",
    "docx_no_text": "The DOCX file contains no translatable body text.",
    "ebook_drm": "This book may be DRM-protected. FolioCross does not remove DRM.",
    "empty_edit": "The translation cannot be empty.",
    "empty_response": "The model returned no usable content.",
    "epub_mapping_incomplete": "Some EPUB content no longer matches its original location, so export was stopped.",
    "epub_note_resource_missing": "An EPUB note resource referenced by the book is missing.",
    "epub_spine_resource_missing": "An EPUB spine resource referenced by the book is missing.",
    "file_not_found": "The selected file could not be found.",
    "glossary_file_missing": "The glossary file could not be found.",
    "glossary_json_invalid": "The glossary file is not valid JSON.",
    "glossary_shape_invalid": "The glossary JSON must contain an array at the top level.",
    "html_mapping_incomplete": "Some HTML content no longer matches its original location, so export was stopped.",
    "invalid_action": "The requested job action is not supported.",
    "invalid_background_action": "The requested background action is not supported.",
    "invalid_budget": "The budget values are invalid. Check the alert and hard-limit amounts.",
    "invalid_issue_status": "The requested issue status is not supported.",
    "invalid_json": "The model did not return valid JSON.",
    "invalid_model_profile": "The model name and API endpoint are required.",
    "invalid_provider": "This model provider is not supported.",
    "invalid_term": "Both the source term and its translation are required.",
    "issue_has_no_suggestion": "This issue has no complete suggestion that can be applied.",
    "issue_not_found": "The requested quality issue could not be found.",
    "job_already_running": "Another Worker is already running this job.",
    "job_is_running": "Pause the job before changing this setting or archiving it.",
    "job_not_found": "The requested job could not be found.",
    "kindleunpack_failed": "KindleUnpack could not extract this book. See the job log for details.",
    "kindleunpack_missing": "KindleUnpack is not configured or unavailable.",
    "kindleunpack_output_invalid": "KindleUnpack did not produce a valid OPF package.",
    "model_connection_invalid": "The model responded, but the response was not in the expected format.",
    "operation_failed": "The background operation failed. See the job log for details.",
    "parse_failed": "FolioCross could not parse this book. See the error log for details.",
    "preview_unsupported": "This file type cannot be previewed inside FolioCross.",
    "review_not_ready": "There is no translated text to review yet.",
    "revision_not_found": "The requested revision could not be found.",
    "segment_changed": "This segment changed after you opened it. Reload it before saving again.",
    "segment_job_mismatch": "This segment does not belong to the selected job.",
    "segment_locked": "An automated operation cannot overwrite a manually locked segment.",
    "segment_not_found": "The requested segment could not be found.",
    "translation_alignment_failed": "The model repeatedly returned the wrong number of translated segments.",
    "unsupported_format": "This input format is not supported.",
    "unsupported_output": "This output format is not supported.",
    "wenyi_converted_source_missing": "The Wenyi task has no converted EPUB cache required for lossless migration.",
    "wenyi_manifest_missing": "The selected Wenyi task has no manifest.",
    "wenyi_source_mismatch": "The selected source book does not match this Wenyi task.",
    "wenyi_state_missing": "No Wenyi state directory was found at the selected location.",
    "wenyi_task_running": "The Wenyi task is still running. Pause it safely before importing.",
    "working_source_missing": "The normalized source file could not be found.",
}


class FolioCrossError(Exception):
    """An expected failure with a stable error code and actionable message."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def localized(self, language: str) -> str:
        if language != "en":
            return self.message
        return ERROR_MESSAGES_EN.get(self.code, f"Operation failed ({self.code}).")

    def as_dict(self) -> dict:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message, "details": self.details},
        }


def localized_error(code: str | None, language: str, fallback: str = "") -> str:
    if language != "en":
        return fallback
    if code:
        return ERROR_MESSAGES_EN.get(code, f"Operation failed ({code}).")
    return "The operation failed. See the job log for details."
