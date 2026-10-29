# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``varuna360 --tool``: run one capability headless (AIC plan 2 W8).

    varuna360 --tool list
    varuna360 --tool describe get_dasha
    varuna360 --tool get_dasha --chart FILE.chtk [--level 2 --side right ...]
              [--varga 9 ...] [--factory-defaults] [--json] [--out FILE]
    varuna360 --tool get_dasha --input INPUT.json  (a CalculationInput)
    varuna360 --tool get_dasha --input CAPTURE_DIR [--region ID]  (replay a capture)
    varuna360 --tool search_charts [--text ...]  (library scope: no chart)

A library-scope capability (``Capability.scope == "library"``) runs on the
chart library, not one chart: it takes no ``--chart``, ``--input``,
``--region`` or view flag, and invoke builds its ``LibraryInput`` from the
resolved settings.

Settings are not arguments (SPEC-SET-003 D-9, W4c): the frame (mode,
ayanamsa, houses...) and every option that follows a setting (year length,
Chara method, date format...) resolve in the TERMINAL context (INV-4b, W6):
``--set key=value`` (advanced mode only, a key this capability uses) > the
tools' settings file (``settings.py set``) > the running app's live value >
the saved setting > the factory default; ``--factory-defaults`` keeps only
``--set`` > factory. A child process the running app started with its
trusted app block resolves in the app context instead (never the tools'
file). The parser has no flag for a setting, so argparse refuses one as an
unrecognized argument (exit 2). Per-call options (level, drill, cycle, side, view...) and the
view values (varga, ascendant override, Human Design, reference instant) stay
flags. With ``--input``, the frame and view values the file carries are kept;
a view flag overrides the file's view value. Nothing is ever written except
``--out``. The output is the result envelope as JSON (``--json`` is accepted
for symmetry with the older CLIs).

A capture (``--input`` naming a capture folder, or its input.json with the
frozen ``live`` block) replays in the FROZEN settings context (SPEC-SET-003
INV-4b, §4.6a): ``packet.load_for_replay`` reads capture.json and input.json,
upgrades a version 1 packet in memory and gives the region's frozen settings;
nothing is read from the running app or the saved file. ``--region`` names the
region (required when the capture holds several for the tool). The result
carries a ``replay`` block (packet version, region, assumed settings).

Exit codes: 0 ok, 2 bad arguments, 3 calculation error (the error envelope is
still written). No Qt is imported.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

EXIT_OK, EXIT_USAGE, EXIT_CALC = 0, 2, 3

# The view flags: the one list (core.capabilities.catalog VIEW_ARGS, from
# inputs.VIEW_DEFAULTS), shared with the in-process adapter
# (pro/managers/tool_definitions.py). The frame entries are settings: no flag.
from core.capabilities.inputs import VIEW_DEFAULTS as _VIEW

_VIEW_FLAGS = tuple(_VIEW)
SOURCE_INPUT = "input"  # a frame value carried by the --input file


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse exits 2 already; keep its message
        self.print_usage(sys.stderr)
        raise _Usage(message)


class _Usage(Exception):
    pass


class _Refused(Exception):
    """A settings refusal already worded by the D-21 gate (printed as is)."""


def option_flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def _bool(text: str) -> bool:
    low = str(text).lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {text!r}")


def _base_parser() -> _Parser:
    p = _Parser(prog="varuna360 --tool", add_help=False)
    p.add_argument("--tool", required=True)
    p.add_argument("target", nargs="?", help="capability id after 'describe'")
    p.add_argument("--chart")
    p.add_argument(
        "--input",
        help="a CalculationInput JSON, or a capture folder "
        "(or its input.json) to replay; the view flags given here "
        "override its view values",
    )
    p.add_argument("--region", help="the capture region to replay (with --input)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.add_argument("--factory-defaults", action="store_true")
    # Advanced mode only (D-15); checked against the capability's uses (D-20).
    p.add_argument(
        "--set", dest="settings_set", action="append", default=None, metavar="KEY=VALUE"
    )
    p.add_argument(
        "-l", "--lite", action="store_true", help="Lite edition (Core tools only)"
    )
    p.add_argument("-h", "--help", action="store_true")
    view = p.add_argument_group(
        "view (default: --input file, else what the running app shows for the "
        "varga and Human Design mode, else the factory value)"
    )
    view.add_argument("--varga", type=int, default=None, help="default 1")
    view.add_argument("--ascendant-override", type=int)
    view.add_argument(
        "--human-design",
        type=_bool,
        nargs="?",
        const=True,
        default=None,
        help="the -88 Design chart (Human Design mode); "
        "--human-design false for the birth chart",
    )
    view.add_argument(
        "--reference-jd",
        type=float,
        help="UT Julian Day used as 'now' (default: current time)",
    )
    return p


def _add_option_flags(parser: _Parser, cap) -> Dict[str, Dict[str, Any]]:
    """Flags for the capability's per-call options only: a property that is
    a setting (its SETTING_ARGS row, SPEC-SET-003 §4.4) gets no flag, so
    argparse refuses it as an unrecognized argument (D-9, D-13)."""
    from core.capabilities.catalog import external_properties

    props = external_properties(cap)
    group = parser.add_argument_group(f"{cap.id} options")
    for name, prop in props.items():
        kind = prop.get("type")
        kwargs: Dict[str, Any] = {
            "dest": f"opt_{name}",
            "default": None,
            "help": prop.get("description"),
        }
        if kind == "boolean":
            kwargs["type"] = _bool
        elif kind == "array":
            kwargs["type"] = str  # JSON list, or comma separated
        elif kind == "object":
            kwargs["type"] = _object_value  # a JSON object
        elif "enum" in prop:
            kwargs["choices"] = prop["enum"]
        group.add_argument(option_flag(name), **kwargs)
    return props


def _object_value(text: str) -> Dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a JSON object: {exc}") from None
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return value


def _array_value(text: str, prop: Dict[str, Any]) -> List[Any]:
    text = text.strip()
    if text.startswith("["):
        return json.loads(text)
    items = [t.strip() for t in text.split(",") if t.strip()]
    if (prop.get("items") or {}).get("type") == "integer":
        return [int(t) for t in items]
    return items


def _emit(payload: Any, out: Optional[str]) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def _describe(cap) -> Dict[str, Any]:
    from core.capabilities.catalog import tool_schemas

    entry = next(e for e in tool_schemas(scope=None) if e["name"] == cap.id)
    return {
        **entry,
        "edition": cap.edition,
        "sources": [list(s) for s in cap.sources],
        "settings_keys": {
            n: p["x-settings-key"]
            for n, p in (cap.options_schema or {}).get("properties", {}).items()
            if "x-settings-key" in p
        },
    }


def _emit_envelope(envelope, out, dumps):
    """The result envelope to --out, else stdout (as ``main`` writes it)."""
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(dumps(envelope) + "\n")
    else:
        sys.stdout.write(dumps(envelope) + "\n")
        sys.stdout.flush()


def _input_from_file(path, args, settings):
    """The --input CalculationInput with the view flags on top.

    A plain CalculationInput file (terminal route; a capture goes through
    ``Replay.calculation_input``). Per frame value: the file's value > the
    settings (live > saved > factory); per view value: flag > the file's value >
    live > factory. A file value keeps the source it recorded (``input`` when
    none). With no view flag and a complete frame, the result equals
    ``CalculationInput.from_dict`` of the file."""
    from core.capabilities.inputs import (
        FRAME_PREFERENCES,
        VIEW_DEFAULTS,
        CalculationInput,
        ChartFrame,
        ChartMoment,
        InputError,
        ViewState,
        view_value,
    )

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise InputError("malformed calculation input: not a JSON object")
    base = CalculationInput.from_dict(data)  # validates the shape
    raw_frame = dict(data.get("frame") or {})
    recorded = raw_frame.pop("sources", None) or {}
    # Every frame preference the file recorded, the Human Design level
    # included: an override replaces only the keys it names.
    carried = {
        k: v for k, v in raw_frame.items() if k in FRAME_PREFERENCES and v is not None
    }
    if set(carried) != set(FRAME_PREFERENCES):
        frame = ChartFrame.resolve(settings, **carried)
        for name in carried:
            frame.sources[name] = recorded.get(name, SOURCE_INPUT)
    else:
        # The file's frame as recorded, its values checked like a partial
        # frame's (W9 R4-L1: a wrong type is the input's error, not a
        # calculation error).
        ChartFrame.resolve(settings, **carried)
        frame = base.frame
    # View: argument > the file's value > live app > factory, per value (the
    # one rule, view_value). A view value the file does not carry (no "view"
    # key, or the key missing or null) resolves like any unset view value.
    file_view = dict(data.get("view") or {})
    unknown = set(file_view) - set(VIEW_DEFAULTS)
    if unknown:
        raise InputError(
            f"malformed calculation input: unknown view option(s) {sorted(unknown)}"
        )
    view_data = {}
    for name in VIEW_DEFAULTS:
        flag = getattr(args, name, None) if name in _VIEW_FLAGS else None
        view_data[name] = view_value(
            name, settings, flag if flag is not None else file_view.get(name)
        )
    try:
        view = ViewState(**view_data)
    except TypeError as exc:
        raise InputError(f"malformed calculation input: {exc}") from exc
    return CalculationInput(
        chart=ChartMoment(**data["chart"]),
        frame=frame,
        view=view,
        settings=dict(data.get("settings", {})),
    )


def main(argv: Optional[List[str]] = None) -> int:
    from core import edition
    from core.edition_features import ai_features
    _ai = ai_features(edition.current_edition(argv))
    pk = _ai.capture_packet() if _ai is not None else None   # Lite: no capture replay
    from core.capabilities import catalog, registry  # noqa: F401  (registers)
    from core.capabilities.inputs import CalculationInput, InputError, resolve_view
    from core.capabilities.result import dumps
    from core.settings_registry import cli as scli
    from core.settings_registry import cli_store, cli_text, effective

    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _base_parser()
    try:
        known, _rest = parser.parse_known_args(argv)
        tool = known.tool
        ed = edition.current_edition(argv)
        if tool in ("list", "describe"):
            # The metadata routes use no setting (W6 review F7): the shared
            # checker with empty USES, before anything is printed. --set is
            # refused as on every terminal route (D-15 while advanced mode is
            # off, D-20 while on), and the tools' settings file is validated
            # as on every terminal run (§4.5a).
            try:
                scli.context_for(known, keys=())
            except (effective.CommandRefused, cli_store.StoreError) as err:
                scli.report(err)
                return EXIT_USAGE
        if tool == "list":
            _emit(
                [
                    {"id": c.id, "title": c.title, "edition": c.edition}
                    for c in catalog.capabilities(ed, scope=None)
                ],
                known.out,
            )
            return EXIT_OK
        if tool == "describe":
            if not known.target:
                raise _Usage("describe needs a capability id")
            _emit(_describe(catalog.get(known.target)), known.out)
            return EXIT_OK
        try:
            cap = catalog.get(tool)
        except catalog.OptionError as exc:
            raise _Usage(str(exc))
        if cap.id not in {c.id for c in catalog.capabilities(ed, scope=None)}:
            raise _Usage(f"{cap.id} is not available in the {ed} edition")
        props = _add_option_flags(parser, cap)
        if known.help:
            parser.print_help(sys.stdout)
            return EXIT_OK
        args = parser.parse_args(argv)
        if args.target:
            raise _Usage(f"unexpected argument {args.target!r}")
        library = cap.scope == catalog.SCOPE_LIBRARY
        if library:
            given = [
                option_flag(n)
                for n in ("chart", "input", "region", *_VIEW_FLAGS)
                if getattr(args, n) is not None
            ]
            if given:
                raise _Usage(
                    f"{cap.id} searches the chart library and takes no chart: "
                    f"remove {', '.join(given)}"
                )
        elif bool(args.chart) == bool(args.input):
            raise _Usage("give exactly one of --chart FILE or --input FILE.json")

        # A capture replays in its frozen settings (SPEC-SET-003 §4.6a): the
        # one replay loader, shared with the AI task tools.
        replay = None
        if args.input and pk is not None and pk.is_capture_input(args.input):
            # A capture answers in its own frozen settings: a factory switch
            # would replace them (INV-4b, W4 review F2). Terminal-only flag.
            if args.factory_defaults:
                raise _Usage(
                    "--factory-defaults cannot be used with a capture replay "
                    "(--input naming a capture): it replays in the capture's "
                    "frozen settings"
                )
            if args.settings_set:
                # The frozen context has no command layer (INV-4b).
                raise _Refused(cli_text.message("set.replay", flag="--set"))
            replay = pk.load_for_replay(args.input, cap.id, args.region)
        elif args.region:
            raise _Usage("--region needs --input naming a capture")
        if replay is not None:
            settings = replay.settings()
        else:
            # The terminal context (or the app context for a child of the
            # app): --set > tools' settings file > live > saved > factory.
            try:
                ctx = scli.context_for(args, keys=scli.capability_uses(cap.id))
            except (effective.CommandRefused, cli_store.StoreError) as err:
                scli.report(err)
                return EXIT_USAGE
            settings = effective.view(ctx)
        options: Dict[str, Any] = {}
        for name, prop in props.items():
            value = getattr(args, f"opt_{name}")
            if value is None:
                continue
            options[name] = (
                _array_value(value, prop) if prop.get("type") == "array" else value
            )
        # The shared boundary (SPEC-SET-003 §4.4): no setting reaches invoke.
        catalog.external_options(cap, options, factory_defaults=True)

        if library:
            inp = None  # invoke builds the LibraryInput from ``settings``
        elif replay is not None:
            # The loader's input (W4 review F3): the region's own view (a D-1
            # region under a centred varga) under the view flags given here,
            # exactly what the task tools run.
            inp = replay.calculation_input(
                settings, view_flags={k: getattr(args, k) for k in _VIEW_FLAGS}
            )
        elif args.input:
            inp = _input_from_file(args.input, args, settings)
        else:
            # argument > live app > factory: the one rule (resolve_view)
            view = resolve_view(settings, **{k: getattr(args, k) for k in _VIEW_FLAGS})
            inp = CalculationInput.from_file(args.chart, settings=settings, view=view)
    except _Refused as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_USAGE
    except InputError as exc:
        # W9 R4-L1: a CalculationInput the command cannot use (a wrong-type
        # frame value in a partial or complete --input file) is the
        # structured error envelope (bad_input) on stdout, as every other
        # failure of a known capability, not prose on stderr.
        from core.capabilities import result as _result

        if "cap" not in locals():
            sys.stderr.write(f"varuna360 --tool: {exc}\n")
            return EXIT_USAGE
        envelope = _result.error(
            cap.id,
            cap.schema_version,
            None,
            locals().get("options"),
            "bad_input",
            str(exc),
        )
        _emit_envelope(envelope, getattr(locals().get("args"), "out", None), dumps)
        return EXIT_USAGE
    except (_Usage, ValueError, OSError) as exc:
        sys.stderr.write(f"varuna360 --tool: {exc}\n")
        return EXIT_USAGE

    envelope = catalog.invoke(cap.id, inp, options, settings=settings)
    if replay is not None:
        # D-19: a setting the capture did not record is named, never silent.
        for line in replay.annotate(envelope)["warnings"]:
            sys.stderr.write(f"varuna360 --tool: {line}\n")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(dumps(envelope) + "\n")
    else:
        sys.stdout.write(dumps(envelope) + "\n")
        sys.stdout.flush()
    if envelope["status"] == "ok":
        return EXIT_OK
    usage = ("bad_option", "invalid_combination")
    return EXIT_USAGE if envelope["error"]["type"] in usage else EXIT_CALC


if __name__ == "__main__":
    sys.exit(main())
