"""git と同じ形式の競合マーカーを使う、行単位のテキストマージ。"""

import re
from difflib import SequenceMatcher

LOCAL_MARKER = "<<<<<<< ローカル"
SEPARATOR = "======="
REMOTE_MARKER = ">>>>>>> eLabFTW"

# "=======" alone is also a setext heading underline in Markdown, and a
# document may show git markers as an example, so only esync's own opening
# and closing markers identify a conflict.
_OPEN_RE = re.compile(rf"^{re.escape(LOCAL_MARKER)}$", re.MULTILINE)
_CLOSE_RE = re.compile(rf"^{re.escape(REMOTE_MARKER)}( .*)?$", re.MULTILINE)


def has_conflict_markers(text: str) -> bool:
    return bool(_OPEN_RE.search(text) and _CLOSE_RE.search(text))


def _conflict(local, remote, remote_label):
    return [LOCAL_MARKER, *local, SEPARATOR, *remote, f"{REMOTE_MARKER} {remote_label}".rstrip()]


def _sync_regions(base, local, remote):
    """Base ranges unchanged on both sides, as (base, local, remote) start/end triples."""
    local_blocks = SequenceMatcher(None, base, local, autojunk=False).get_matching_blocks()
    remote_blocks = SequenceMatcher(None, base, remote, autojunk=False).get_matching_blocks()
    regions = []
    il = ir = 0
    while il < len(local_blocks) and ir < len(remote_blocks):
        lbase, lstart, llen = local_blocks[il]
        rbase, rstart, rlen = remote_blocks[ir]
        start, end = max(lbase, rbase), min(lbase + llen, rbase + rlen)
        if start < end:
            ls, rs = lstart + start - lbase, rstart + start - rbase
            regions.append((start, end, ls, ls + end - start, rs, rs + end - start))
        if lbase + llen < rbase + rlen:
            il += 1
        else:
            ir += 1
    regions.append((len(base), len(base), len(local), len(local), len(remote), len(remote)))
    return regions


def merge_text(base: str | None, local: str, remote: str, remote_label: str = "") -> tuple[str, int]:
    """Merge local and remote edits of base; return (text, number of conflicts).

    Changes made on only one side are taken as is. Where both sides changed
    the same lines differently, both versions are kept between markers. When
    base is unknown, every difference between local and remote is a conflict.
    """
    local_lines, remote_lines = local.splitlines(), remote.splitlines()
    out, conflicts = [], 0
    if base is None:
        matcher = SequenceMatcher(None, local_lines, remote_lines, autojunk=False)
        for tag, l1, l2, r1, r2 in matcher.get_opcodes():
            if tag == "equal":
                out += local_lines[l1:l2]
            else:
                out += _conflict(local_lines[l1:l2], remote_lines[r1:r2], remote_label)
                conflicts += 1
        return "\n".join(out), conflicts
    base_lines = base.splitlines()
    ib = il = ir = 0
    for bstart, bend, lstart, lend, rstart, rend in _sync_regions(base_lines, local_lines, remote_lines):
        b, l, r = base_lines[ib:bstart], local_lines[il:lstart], remote_lines[ir:rstart]
        if l == r:
            out += l
        elif l == b:
            out += r
        elif r == b:
            out += l
        else:
            out += _conflict(l, r, remote_label)
            conflicts += 1
        out += base_lines[bstart:bend]
        ib, il, ir = bend, lend, rend
    return "\n".join(out), conflicts
