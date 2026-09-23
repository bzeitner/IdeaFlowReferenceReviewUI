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


def _validate_packet(packet):
    if not isinstance(packet, dict) or set(packet) != PACKET_KEYS:
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
    if len(plan_hashes) != 1 or len(rubric_hashes) != 1 or len(rubrics) != 1:
        raise ValidationError("All packets must belong to one plan and exact rubric.")
    return packets
