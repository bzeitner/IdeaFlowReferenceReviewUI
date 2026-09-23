import io
import json
import re
import tarfile

from django.core.exceptions import ValidationError


HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_MEMBER_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_CASES = 200
PACKET_KEYS = {
    "plan_hash",
    "case_id",
    "case_hash",
    "rubric_hash",
    "rubric",
    "evidence",
    "response_schema",
    "notice",
}
ASSISTED_KEYS = PACKET_KEYS | {"automated_assessment", "automated_result", "review_mode"}
STATUSES = {"pass", "fail", "not_applicable", "insufficient_evidence"}


def _validate_packet(packet):
    if not isinstance(packet, dict) or frozenset(packet) not in {frozenset(PACKET_KEYS), frozenset(ASSISTED_KEYS)}:
        raise ValidationError("A packet has unexpected or missing fields.")
    if type(packet["case_id"]) is not int or packet["case_id"] < 1:
        raise ValidationError("A packet has an invalid case ID.")
    for field in ("plan_hash", "case_hash", "rubric_hash"):
        if not isinstance(packet[field], str) or not HASH.fullmatch(packet[field]):
            raise ValidationError(f"A packet has an invalid {field}.")
    rubric = packet["rubric"]
    criteria = rubric.get("criteria") if isinstance(rubric, dict) else None
    if not isinstance(criteria, list) or not criteria or len(criteria) > 50:
        raise ValidationError("A packet has an invalid rubric.")
    criterion_ids = set()
    for criterion in criteria:
        required = {"id", "description", "severity", "required_inputs", "applicability"}
        if not isinstance(criterion, dict) or not required <= set(criterion):
            raise ValidationError("A rubric criterion is malformed.")
        if criterion["id"] in criterion_ids:
            raise ValidationError("A rubric contains duplicate criterion IDs.")
        criterion_ids.add(criterion["id"])
    evidence = packet["evidence"]
    if not isinstance(evidence, dict) or not evidence or len(evidence) > 200:
        raise ValidationError("A packet has invalid evidence.")
    for ref, item in evidence.items():
        if (
            not isinstance(ref, str)
            or not ref
            or not isinstance(item, dict)
            or set(item) != {"kind", "value"}
            or not isinstance(item["kind"], str)
            or not isinstance(item["value"], str)
        ):
            raise ValidationError("A packet evidence entry is malformed.")
    assisted = "automated_assessment" in packet
    if assisted:
        if packet["review_mode"] != "model_assisted_error_audit_v1":
            raise ValidationError("The assisted review mode is unsupported.")
        result = packet["automated_result"]
        if (
            not isinstance(result, dict)
            or set(result) != {"id", "hash"}
            or type(result["id"]) is not int
            or result["id"] < 1
            or not isinstance(result["hash"], str)
            or not HASH.fullmatch(result["hash"])
        ):
            raise ValidationError("The automated result fingerprint is malformed.")
        assessment = packet["automated_assessment"]
        if not isinstance(assessment, dict) or set(assessment) != {"criterion_results", "progress_score"}:
            raise ValidationError("The automated assessment is malformed.")
        rows = assessment["criterion_results"]
        if not isinstance(rows, list) or len(rows) != len(criteria):
            raise ValidationError("The automated assessment does not cover every criterion.")
        expected = {criterion["id"] for criterion in criteria}
        observed = set()
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != {"id", "status", "reason", "evidence_refs"}
                or row["id"] not in expected
                or row["id"] in observed
                or row["status"] not in STATUSES
                or not isinstance(row["reason"], str)
                or not row["reason"].strip()
                or not isinstance(row["evidence_refs"], list)
                or any(ref not in evidence for ref in row["evidence_refs"])
            ):
                raise ValidationError("An automated criterion result is malformed.")
            observed.add(row["id"])
        if observed != expected:
            raise ValidationError("The automated assessment criterion IDs do not match the rubric.")


def read_packet_archive(upload):
    raw = upload.read(MAX_TOTAL_BYTES + 1)
    if len(raw) > MAX_TOTAL_BYTES:
        raise ValidationError("The archive exceeds the 10 MiB limit.")
    packets = []
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_CASES + 20:
                raise ValidationError("The archive contains too many members.")
            for member in members:
                if member.isdir():
                    continue
                if not member.isfile() or member.issym() or member.islnk():
                    raise ValidationError("The archive contains an unsupported member type.")
                if not member.name.endswith(".json") or member.size > MAX_MEMBER_BYTES:
                    raise ValidationError("The archive contains an invalid packet file.")
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise ValidationError("The uncompressed packets exceed the size limit.")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValidationError("A packet could not be read.")
                packet = json.loads(extracted.read().decode("utf-8"))
                _validate_packet(packet)
                packets.append(packet)
    except (tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("The file is not a valid reviewer packet archive.") from exc
    if not packets or len(packets) > MAX_CASES:
        raise ValidationError("The archive must contain 1–200 packet files.")
    packets.sort(key=lambda packet: packet["case_id"])
    if len({packet["case_id"] for packet in packets}) != len(packets):
        raise ValidationError("The archive contains duplicate case IDs.")
    plan_hashes = {packet["plan_hash"] for packet in packets}
    rubric_hashes = {packet["rubric_hash"] for packet in packets}
    rubrics = {json.dumps(packet["rubric"], sort_keys=True) for packet in packets}
    modes = {packet.get("review_mode", "independent_blinded_v1") for packet in packets}
    if len(plan_hashes) != 1 or len(rubric_hashes) != 1 or len(rubrics) != 1 or len(modes) != 1:
        raise ValidationError("All packets must belong to one plan and exact rubric.")
    return packets
