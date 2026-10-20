"""The one place that declares what a capture renumbers and masks.

Everything else in a response is kept exactly as the API returned it.

Renumbered (consistently within one scenario, in order of first appearance):
  random ids, as values, dict keys and inside longer text.
Masked:
  - timestamps minted by the run (ISO 8601 date-times dated on a day the run ran)
  - the running Larch version string, wherever it appears
  - `input_sha256` and `current_input_sha256` (they hash the Larch version)
  - a fit's `metadata.seconds` (wall-clock timings)
"""
import re

# Random ids the backend mints: athena's uid() (secrets.token_urlsafe(18), 24
# url-safe characters) and uuid4().hex (32 lowercase hex digits).
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{24}|[0-9a-f]{32}")
TIMESTAMP_PATTERN = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
MASKED_KEYS = {"input_sha256": "<input_sha256>", "current_input_sha256": "<input_sha256>"}
MASKED_CHILD_KEYS = {("metadata", "seconds"): "<seconds>"}


def normalize(document, *, larch_version, run_dates):
    """Return `document` with ids renumbered and the declared volatile fields masked.

    `run_dates` are the ISO dates (YYYY-MM-DD) the run spanned; only timestamps
    on those dates are treated as minted by the run.
    """
    ids = {}

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                collect(key)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str) and ID_PATTERN.fullmatch(value):
            ids.setdefault(value, f"ID#{len(ids) + 1}")

    def timestamp(match):
        return "<timestamp>" if match.group("date") in run_dates else match.group(0)

    def text(value):
        if value in ids:
            return ids[value]
        if embedded:
            # An id already seen whole may also sit inside text (file names, messages).
            value = embedded.sub(lambda match: ids[match.group(0)], value)
        if larch_version:
            value = value.replace(larch_version, "<larch_version>")
        return TIMESTAMP_PATTERN.sub(timestamp, value)

    def rewrite(value, parent=None):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key in MASKED_KEYS:
                    out[text(key)] = MASKED_KEYS[key]
                elif (parent, key) in MASKED_CHILD_KEYS:
                    out[text(key)] = MASKED_CHILD_KEYS[(parent, key)]
                else:
                    out[text(key)] = rewrite(item, key)
            return out
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str):
            return text(value)
        return value

    collect(document)
    embedded = re.compile("|".join(map(re.escape, sorted(ids, key=len, reverse=True)))) if ids else None
    return rewrite(document)
