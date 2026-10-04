"""Run many mmd commands in one process.

A batch file holds one command per line, written as the command line would be after `mmd`
(global options such as --pid belong to the `mmd batch` invocation, not to the lines):

    # comments and blank lines are skipped
    new
    model load "C:\\models\\miku.pmx"
    ["bone", "set", "右腕", "--rot", "0", "0", "35", "--frame", "30"]
    {"id": "wink", "args": ["morph", "set", "ウィンク", "1.0"]}

Plain lines are split on spaces, double quotes group words, and backslashes are kept as they
are (Windows paths).  JSON lines avoid any quoting question.  One process attaches to MMD once
and keeps the focus shield up for the whole run, so a long script costs far less than one
`mmd` process per command.
"""
import contextlib
import io
import json

from . import cli

GLOBAL_OPTIONS = ("--pid", "--out", "--timeout", "--in-place", "--in-user-session", "--no-relay", "--job",
                  "--version", "-h", "--help")


class BatchSyntaxError(ValueError):
    pass


class UsageError(ValueError):
    pass


def split_args(line):
    """split like a shell for the simple cases: spaces separate, "..." groups, backslashes are literal"""
    out = []
    cur = []
    quoted = False
    have = False
    for ch in line:
        if ch == '"':
            quoted = not quoted
            have = True
        elif ch.isspace() and not quoted:
            if have:
                out.append("".join(cur))
                cur = []
                have = False
        else:
            cur.append(ch)
            have = True
    if quoted:
        raise ValueError("unbalanced double quote")
    if have:
        out.append("".join(cur))
    return out


def parse_lines(text):
    entries = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ident = None
        if line[0] in "[{":
            try:
                obj = json.loads(line)
            except ValueError as exc:
                raise BatchSyntaxError("line %d: not valid JSON (%s)" % (number, exc))
            if isinstance(obj, list):
                argv = [str(x) for x in obj]
            elif isinstance(obj, dict):
                argv = [str(x) for x in obj.get("args", [])]
                ident = obj.get("id")
            else:
                raise BatchSyntaxError("line %d: a JSON line must be an array or an object" % number)
        else:
            try:
                argv = split_args(line)
            except ValueError as exc:
                raise BatchSyntaxError("line %d: %s" % (number, exc))
        if argv and argv[0] == "mmd":
            argv = argv[1:]
        if not argv:
            raise BatchSyntaxError("line %d: empty command" % number)
        offending = [a for a in argv if a.split("=", 1)[0] in GLOBAL_OPTIONS]
        if offending:
            raise BatchSyntaxError("line %d: %s is an option of 'mmd batch' itself, not of a line"
                                   % (number, offending[0]))
        entry = {"line": number, "argv": argv}
        if ident is not None:
            entry["id"] = ident
        entries.append(entry)
    return entries


def parse_quietly(parser, argv):
    """argparse prints and exits on a usage error; turn that into an exception with the message"""
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            return parser.parse_args(argv)
    except SystemExit:
        lines = [l for l in stderr.getvalue().splitlines() if l.strip()]
        raise UsageError(lines[-1] if lines else "invalid arguments: %s" % " ".join(argv))


def run_batch(entries, make_mmd, dispatch, parser, stop_on_error=True):
    """entries from parse_lines; make_mmd() attaches the instance when a line first needs it;
    dispatch(mmd, args) runs one parsed command (cli._dispatch).  Returns (results, exit_code)."""
    results = []
    code = 0
    mmd = None
    for entry in entries:
        record = {"line": entry["line"], "argv": entry["argv"]}
        if "id" in entry:
            record["id"] = entry["id"]
        failure_code = 0
        try:
            args = parse_quietly(parser, entry["argv"])
            if args.command not in ("file", "launch", "ps") and mmd is None:
                mmd = make_mmd()
            target = None if args.command in ("file", "launch", "ps") else mmd
            result = dict(dispatch(target, args))
            instance = result.pop("_instance", None)
            if instance is not None:
                mmd = instance
            record["ok"] = True
            record.update(result)
        except UsageError as exc:
            record.update({"ok": False, "error": {"type": "UsageError", "message": str(exc)}})
            failure_code = 2
        except Exception as exc:
            payload, failure_code = cli.failure(exc)
            record.update(payload)
        if mmd is not None and hasattr(mmd, "take_events"):
            events = mmd.take_events()
            if events:
                record["answered_dialogs"] = events
        results.append(record)
        if failure_code:
            code = max(code, failure_code)
            if stop_on_error:
                break
    return results, code


def summary(results, code):
    return {"ok": code == 0, "ran": len(results), "failed": sum(1 for r in results if not r.get("ok")),
            "exit_code": code, "results": results}
