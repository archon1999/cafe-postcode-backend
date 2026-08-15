from rest_framework import status


CLASSIFICATION_RETRY = "retry"
CLASSIFICATION_ACTION_REQUIRED = "action_required"
CLASSIFICATION_QUARANTINED = "quarantined"
CLASSIFICATION_SUPERSEDED = "superseded"


def mutation_result_metadata(
    *,
    response_status,
    response_body=None,
    retryable=False,
    reconciled=False,
    code="",
    classification="",
    resolution_hint="",
):
    if not classification:
        if reconciled:
            classification = CLASSIFICATION_SUPERSEDED
        elif retryable or response_status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            classification = CLASSIFICATION_RETRY
        elif response_status >= status.HTTP_400_BAD_REQUEST:
            classification = CLASSIFICATION_ACTION_REQUIRED

    if not code and isinstance(response_body, dict):
        body_code = response_body.get("code")
        if isinstance(body_code, str):
            code = body_code.strip()
    if not code:
        if classification == CLASSIFICATION_SUPERSEDED:
            code = "MUTATION_ALREADY_APPLIED"
        elif classification == CLASSIFICATION_RETRY:
            code = "MUTATION_TEMPORARILY_UNAVAILABLE"
        elif classification == CLASSIFICATION_ACTION_REQUIRED:
            code = f"MUTATION_HTTP_{response_status}"
        elif classification == CLASSIFICATION_QUARANTINED:
            code = "MUTATION_CONTRACT_ERROR"

    if not resolution_hint:
        resolution_hint = {
            CLASSIFICATION_RETRY: "Local Agent will retry this operation automatically.",
            CLASSIFICATION_ACTION_REQUIRED: (
                "Review the operation in POS or admin, then retry or resolve it."
            ),
            CLASSIFICATION_QUARANTINED: (
                "Check the Local Agent/backend contract before retrying this operation."
            ),
            CLASSIFICATION_SUPERSEDED: (
                "Server state already reflects the intended outcome; no retry is needed."
            ),
        }.get(classification, "")

    metadata = {}
    if classification:
        metadata["classification"] = classification
    if code:
        metadata["code"] = code
    if resolution_hint:
        metadata["resolutionHint"] = resolution_hint
    return metadata


def mutation_error_result(
    *,
    operation_id="",
    response_status,
    error,
    retryable=False,
    code="",
    classification="",
    resolution_hint="",
):
    result = {
        "operationId": operation_id,
        "ok": False,
        "status": response_status,
        "error": error,
        "retryable": retryable,
    }
    result.update(
        mutation_result_metadata(
            response_status=response_status,
            retryable=retryable,
            code=code,
            classification=classification,
            resolution_hint=resolution_hint,
        )
    )
    return result
