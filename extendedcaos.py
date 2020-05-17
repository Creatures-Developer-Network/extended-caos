import itertools
import json
import re
import string
import sys

from caoslexer import *
from caosparser import parse


def move_comments_to_own_line(tokens):
    tokens = tokens[:]

    newline_style = "\n"
    for nt in tokens:
        if nt[0] == TOK_NEWLINE:
            newline_style = nt[1]
            break

    i = 0
    last_newline = -1  # hack if we haven't seen a newline yet
    last_indent = ""
    while i < len(tokens):
        t = tokens[i]
        if t[0] == TOK_EOI:
            break
        # bookkeeping for newlines and indentation
        if t[0] == TOK_NEWLINE and i + 1 < len(tokens):
            if tokens[i + 1][0] == TOK_WHITESPACE:
                last_indent = tokens[i + 1][1]
            else:
                last_indent = ""
        if i == 0 and t[0] == TOK_WHITESPACE:
            last_indent = t[1]
        if t[0] == TOK_NEWLINE:
            last_newline = i
            i += 1
            continue
        # only care about comments
        if t[0] != TOK_COMMENT:
            i += 1
            continue
        # already at beginning of line
        if i == 0 or tokens[i - 1][0] == TOK_NEWLINE:
            i += 1
            continue
        # already on own line
        if tokens[i - 1][0] == TOK_WHITESPACE and (
            i == 1 or tokens[i - 2][0] == TOK_NEWLINE
        ):
            i += 1
            continue
        # need to move to previous line
        # delete from here, and delete preceding whitespace
        del tokens[i]
        if i >= 1 and tokens[i - 1][0] == TOK_WHITESPACE:
            del tokens[i - 1]
        # figure out where to put it
        i = last_newline + 1
        if last_indent:
            tokens.insert(i, (TOK_WHITESPACE, last_indent))
            i += 1
        tokens.insert(i, t)
        tokens.insert(i + 1, (TOK_NEWLINE, newline_style))
        i += 1  # on the newline we added, to do newline bookkeeping
    return tokens


class script:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.vaxx_vars = []
        self.dollar_vars = []


def namedvariables_to_vaxx(tokens):
    tokens = tokens[:]
    scripts = [script(0, 0)]

    # find script extents
    # TODO: expose this elsewhere too?
    for i, t in enumerate(tokens):
        if t[0] == TOK_WORD and t[1].lower() in ("scrp", "rscr"):
            scripts.append(script(i, i))
            continue
        if t[0] == TOK_WORD and re.match(r"(?i)^va\d\d$", t[1]):
            if t[1].lower() not in scripts[-1].vaxx_vars:
                scripts[-1].vaxx_vars.append(t[1].lower())
        if t[0] == TOK_WORD and t[1][0] == "$":
            if t[1] not in scripts[-1].dollar_vars:
                scripts[-1].dollar_vars.append(t[1])
        scripts[-1].end = i

    # for each script, map named variables to actual variables, then replace the
    # tokens
    for s in scripts:
        var_mapping = {}
        for d in s.dollar_vars:
            possibles = [
                "va{:02}".format(i)
                for i in range(100)
                if "va{:02}".format(i)
                not in itertools.chain(s.vaxx_vars, var_mapping.values())
            ]
            if not possibles:
                raise Exception("Couldn't allocate variable for '%s'" % d)
            var_mapping[d] = possibles[0]
        for i in range(s.start, s.end + 1):
            if tokens[i][0] == TOK_WORD and tokens[i][1][0] == "$":
                tokens[i] = (TOK_WORD, var_mapping[tokens[i][1]])

    return tokens


def get_indentation_at(tokens, i):
    assert tokens[i][0] != TOK_NEWLINE

    while i >= 0:
        if tokens[i][0] == TOK_NEWLINE:
            break
        i -= 1

    indentation = ""
    while tokens[i + 1][0] == TOK_WHITESPACE:
        indentation += tokens[i + 1][1]
        i += 1
    return indentation


def toplevel_explicit_targ(tokens):
    tokens = tokens[:]
    parsetree = parse(tokens)
    insertions = []

    for toplevel in parsetree:
        if toplevel.get("type", "") != "DotCommand":
            continue

        indent = get_indentation_at(tokens, toplevel["start_token"])
        insertion_point = toplevel["start_token"]
        insertions.append(
            (
                insertion_point,
                [
                    (TOK_WORD, "seta"),
                    (TOK_WHITESPACE, " "),
                    (TOK_DOLLARWORD, "$__saved_targ"),
                    (TOK_WHITESPACE, " "),
                    (TOK_WORD, "targ"),
                    (TOK_NEWLINE, "\n"),  # todo: newline style
                    (TOK_WHITESPACE, indent),
                    (TOK_WORD, "targ"),
                    (TOK_WHITESPACE, " "),
                    (TOK_WORD, toplevel["targ"]),
                    (TOK_NEWLINE, "\n"),
                    (TOK_WHITESPACE, indent),
                ]
                + tokens[toplevel["start_token"] + 2 : toplevel["end_token"] + 1]
                + [
                    (TOK_NEWLINE, "\n"),
                    (TOK_WHITESPACE, indent),
                    (TOK_WORD, "targ"),
                    (TOK_WHITESPACE, " "),
                    (TOK_DOLLARWORD, "$__saved_targ"),
                ],
            )
        )

        for i in range(toplevel["start_token"], toplevel["end_token"] + 1):
            tokens[i] = (TOK_WHITESPACE, "")

    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)

    return tokens


def get_setx_for_command(node):
    if node["type"] == "LiteralString":
        return "sets"
    if node["type"] == "LiteralInteger":
        return "setv"
    if node["type"] not in ("Command", "DotCommand"):
        raise Exception(node)
    if node["commandret"] in ("integer", "float"):
        return "setv"
    elif node["commandret"] in ("string",):
        return "sets"
    elif node["commandret"] in ("agent",):
        return "seta"
    else:
        # TODO: if it's 'variable'.. look at what the parent is expecting?
        raise Exception(
            "Don't know how to save result type '{}' of  {}.{}".format(
                node["commandret"], node["targ"], node["command"]
            )
        )


def explicit_targs_visitor(node, tokens, statement_start, in_dotcommand):
    if node.get("type", "") == "DotCommand":
        insertions = []
        for a in node["args"]:
            insertions += explicit_targs_visitor(a, tokens, statement_start, True)

        set_command = get_setx_for_command(node)
        indent = get_indentation_at(tokens, statement_start)
        value_variable = "$__{}_{}__t{}".format(
            node["targ"].lstrip("$"), node["command"], node["start_token"]
        )
        insertions.append(
            (
                statement_start,
                [
                    (TOK_WORD, "seta"),
                    (TOK_WHITESPACE, " "),
                    (TOK_WORD, "$__saved_targ"),
                    (TOK_WHITESPACE, " "),
                    (TOK_WORD, "targ"),
                    (TOK_NEWLINE, "\n"),  # todo: newline style
                    (TOK_WHITESPACE, indent),
                    (TOK_WORD, "targ"),
                    (TOK_WHITESPACE, " "),
                    (TOK_WORD, node["targ"]),
                    (TOK_NEWLINE, "\n"),
                    (TOK_WHITESPACE, indent),
                    (TOK_WORD, set_command),
                    (TOK_WHITESPACE, " "),
                    (TOK_WORD, value_variable),
                    (TOK_WHITESPACE, " "),
                ]
                + tokens[node["start_token"] + 2 : node["end_token"] + 1]
                + [
                    (TOK_NEWLINE, "\n"),
                    (TOK_WHITESPACE, indent),
                    (TOK_WORD, "targ"),
                    (TOK_WHITESPACE, " "),
                    (TOK_WORD, "$__saved_targ"),
                    (TOK_NEWLINE, "\n"),
                    (TOK_WHITESPACE, indent),
                ],
            )
        )

        tokens[node["start_token"]] = (TOK_WORD, value_variable)
        for i in range(node["start_token"] + 1, node["end_token"] + 1):
            tokens[i] = (TOK_WHITESPACE, "")

        return insertions
    elif node.get("type", "") in ("Command", "Condition"):
        insertions = []
        for a in node["args"]:
            insertions += explicit_targs_visitor(
                a, tokens, statement_start, in_dotcommand
            )

        if in_dotcommand:
            set_command = get_setx_for_command(node)
            indent = get_indentation_at(tokens, statement_start)
            value_variable = "$__targ_{}__t{}".format(node["name"], node["start_token"])
            insertions.append(
                (
                    statement_start,
                    [
                        (TOK_WORD, set_command),
                        (TOK_WHITESPACE, " "),
                        (TOK_WORD, value_variable),
                        (TOK_WHITESPACE, " "),
                    ]
                    + tokens[node["start_token"] : node["end_token"] + 1]
                    + [(TOK_NEWLINE, "\n"), (TOK_WHITESPACE, indent),],
                )
            )

            tokens[node["start_token"]] = (TOK_WORD, value_variable)
            for i in range(node["start_token"] + 1, node["end_token"] + 1):
                tokens[i] = (TOK_WHITESPACE, "")

        return insertions
    else:
        return []


def get_doif_for(parsetree, p):
    assert parsetree[p]["type"] == "Command"
    assert parsetree[p]["name"] == "elif"

    nesting = 0

    while True:
        p -= 1
        if parsetree[p]["type"] == "Command" and parsetree[p]["name"] == "endi":
            nesting += 1
        elif parsetree[p]["type"] == "Command" and parsetree[p]["name"] == "doif":
            if nesting == 0:
                return parsetree[p]
            else:
                nesting -= 1
    raise Exception("Couldn't find matching doif")


def explicit_targs(tokens):
    tokens = tokens[:]
    parsetree = parse(tokens)

    insertions = []
    for i, toplevel in enumerate(parsetree):
        if toplevel["type"] not in ("Command", "Condition", "DotCommand"):
            continue
        indent = get_indentation_at(tokens, toplevel["start_token"])

        insertion_point = toplevel["start_token"]
        if toplevel["type"] == "Command" and toplevel["name"] == "elif":
            # uh-oh. go find last doif
            matching_doif = get_doif_for(parsetree, i)
            insertion_point = matching_doif["start_token"]

        for a in toplevel["args"]:
            insertions += explicit_targs_visitor(
                a, tokens, insertion_point, toplevel["type"] == "DotCommand"
            )

        if toplevel["type"] == "DotCommand":
            saved_targ_variable = object()
            insertions.append(
                (
                    insertion_point,
                    [
                        (TOK_WORD, "seta"),
                        (TOK_WHITESPACE, " "),
                        (TOK_WORD, "$__saved_targ"),
                        (TOK_WHITESPACE, " "),
                        (TOK_WORD, "targ"),
                        (TOK_NEWLINE, "\n"),  # todo: newline style
                        (TOK_WHITESPACE, indent),
                        (TOK_WORD, "targ"),
                        (TOK_WHITESPACE, " "),
                        (TOK_WORD, toplevel["targ"]),
                        (TOK_NEWLINE, "\n"),
                        (TOK_WHITESPACE, indent),
                    ]
                    + tokens[toplevel["start_token"] + 2 : toplevel["end_token"] + 1]
                    + [
                        (TOK_NEWLINE, "\n"),
                        (TOK_WHITESPACE, indent),
                        (TOK_WORD, "targ"),
                        (TOK_WHITESPACE, " "),
                        (TOK_WORD, "$__saved_targ"),
                    ],
                )
            )

            for j in range(toplevel["start_token"], toplevel["end_token"] + 1):
                tokens[j] = (TOK_WHITESPACE, "")

    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)

    return tokens


def remove_extraneous_targ_saving(tokens):
    tokens = tokens[:]
    for i in range(len(tokens)):
        if not (tokens[i][0] == TOK_WORD and tokens[i][1].lower() == "targ"):
            continue
        p = i + 1
        while tokens[p][0] in (TOK_WHITESPACE, TOK_NEWLINE):
            p += 1
        if not (tokens[p][0] == TOK_WORD and tokens[p][1].lower()[0:2] == "va"):
            continue
        var_name = tokens[p][1]
        p += 1
        startdelp = p
        while tokens[p][0] in (TOK_WHITESPACE, TOK_NEWLINE):
            p += 1
        if not (tokens[p][0] == TOK_WORD and tokens[p][1].lower() == "seta"):
            continue
        p += 1
        while tokens[p][0] in (TOK_WHITESPACE, TOK_NEWLINE):
            p += 1
        if not (tokens[p][0] == TOK_WORD and tokens[p][1].lower() == var_name):
            continue
        p += 1
        while tokens[p][0] in (TOK_WHITESPACE, TOK_NEWLINE):
            p += 1
        if not (tokens[p][0] == TOK_WORD and tokens[p][1].lower() == "targ"):
            continue
        enddelp = p

        for j in range(startdelp, enddelp + 1):
            tokens[j] = (TOK_WHITESPACE, "")
    return tokens


def remove_double_targ(tokens):
    tokens = tokens[:]
    for i in range(len(tokens)):
        p = i
        startdelp = p
        if not (tokens[i][0] == TOK_WORD and tokens[i][1].lower() == "targ"):
            continue
        p = i + 1
        while tokens[p][0] in (TOK_WHITESPACE, TOK_NEWLINE):
            p += 1
        if not tokens[p][0] == TOK_WORD:
            continue
        p += 1
        while tokens[p][0] in (TOK_WHITESPACE, TOK_NEWLINE):
            p += 1
        if not (tokens[p][0] == TOK_WORD and tokens[p][1].lower() == "targ"):
            continue
        enddelp = p - 1

        for j in range(startdelp, enddelp + 1):
            tokens[j] = (TOK_WHITESPACE, "")

    parsetree = parse(tokens)

    for i, toplevel in enumerate(parsetree):
        if not (toplevel["type"] == "Command" and toplevel["name"] == "targ"):
            continue
        first_targ = toplevel["args"][0]

        if not (first_targ["type"] == "Command" and first_targ["args"] == []):
            continue
        first_targ_name = first_targ["name"]

        if not (i + 2 < len(parsetree)):
            continue

        second_targ = parsetree[i + 2]
        if not (
            second_targ["type"] == "Command"
            and second_targ["name"] == "targ"
            and second_targ["args"][0]["type"] == "Command"
            and second_targ["args"][0]["name"] == first_targ_name
        ):
            continue

        startp = second_targ["start_token"]
        endp = second_targ["end_token"]

        while startp > 0 and tokens[startp - 1][0] == TOK_WHITESPACE:
            startp -= 1

        while tokens[endp + 1][0] == TOK_WHITESPACE:
            endp += 1
        if tokens[endp + 1][0] == TOK_NEWLINE:
            endp += 1

        for j in range(startp, endp + 1):
            tokens[j] = (TOK_WHITESPACE, "")

    return tokens


def objectvariables_to_ovxx(tokens):
    tokens = tokens[:]

    # build object variable mapping
    var_mapping = {}
    i = 0
    while i < len(tokens):
        if not (tokens[i][0] == TOK_WORD and tokens[i][1] == "agent_variable"):
            i += 1
            continue
        startp = i
        i += 1

        if tokens[i][0] not in (TOK_WHITESPACE, TOK_NEWLINE, TOK_COMMENT):
            raise Exception(
                "Expected whitespace after 'agent_variable', got %s %s" % tokens[i]
            )
        while tokens[i][0] in (TOK_WHITESPACE, TOK_NEWLINE, TOK_COMMENT):
            i += 1

        if not (tokens[i][0] == TOK_WORD and tokens[i][1][0] == "$"):
            raise Exception(
                "Expected variable name after 'agent_variable', got %s %s" % tokens[i]
            )
        variable_name = tokens[i][1]
        i += 1

        if tokens[i][0] not in (TOK_WHITESPACE, TOK_NEWLINE, TOK_COMMENT):
            raise Exception(
                "Expected whitespace after '%s', got %s %s"
                % (variable_name, tokens[i][0], tokens[i][1])
            )
        while tokens[i][0] in (TOK_WHITESPACE, TOK_NEWLINE, TOK_COMMENT):
            i += 1

        if not (tokens[i][0] == TOK_WORD and re.match(r"(?i)^ov\d\d$", tokens[i][1])):
            raise Exception(
                "Expected ovXX after '%s', got %s %s"
                % (variable_name, tokens[i][0], tokens[i][1])
            )
        variable_definition = tokens[i][1]
        i += 1

        while tokens[i][0] == TOK_WHITESPACE:
            i += 1
        if tokens[i][0] not in (TOK_NEWLINE, TOK_EOI):
            raise Exception(
                "Expected newline after agent_variable directive, got %s %s" % tokens[i]
            )
        endp = i
        i += 1

        var_mapping[variable_name] = variable_definition

        for j in range(startp, endp):
            tokens[j] = (TOK_WHITESPACE, "")

    # do replacements
    insertions = []
    i = 0
    while i < len(tokens):
        if not (
            tokens[i][0] == TOK_WORD
            and tokens[i + 1][0] == TOK_DOT
            and tokens[i + 2][0] == TOK_WORD
            and tokens[i + 2][1][0] == "$"
        ):
            i += 1
            continue
        variable_name = tokens[i + 2][1]
        if tokens[i][1].lower() == "targ":
            insertions.append(
                (i, [(TOK_WORD, "ov" + var_mapping[variable_name][2:4]),])
            )
        elif tokens[i][1].lower() == "ownr":
            insertions.append(
                (i, [(TOK_WORD, "mv" + var_mapping[variable_name][2:4]),])
            )
        else:
            insertions.append(
                (
                    i,
                    [
                        (TOK_WORD, "avar"),
                        (TOK_WHITESPACE, " "),
                        tokens[i],
                        (TOK_WHITESPACE, " "),
                        (TOK_INTEGER, int(var_mapping[variable_name][2:4])),
                    ],
                )
            )
        tokens[i] = (TOK_WHITESPACE, "")
        tokens[i + 1] = (TOK_WHITESPACE, "")
        tokens[i + 2] = (TOK_WHITESPACE, "")
        i += 3

    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)

    return tokens


def strip_indent(tokens, indent):
    tokens = tokens[:]
    i = 0

    while True:
        whitespace = ""
        startp = i
        while tokens[i][0] == TOK_WHITESPACE:
            whitespace += tokens[i][1]
            i += 1
        endp = i - 1

        if tokens[startp][0] == TOK_WHITESPACE:
            tokens[startp] = (TOK_WHITESPACE, whitespace[len(indent) :])
            for j in range(startp + 1, endp + 1):
                tokens[j] = (TOK_WHITESPACE, "")
        else:
            # handle non-indented statements
            pass

        while tokens[i][0] not in (TOK_EOI, TOK_NEWLINE):
            i += 1
        if tokens[i][0] == TOK_EOI:
            break
        i += 1

    return tokens


def add_indent(tokens, indent):
    newtokens = [(TOK_WHITESPACE, indent)]

    # TODO: add to existing whitespace tokens, if they exist
    for t in tokens:
        newtokens.append(t)
        if t[0] == TOK_NEWLINE:
            newtokens.append((TOK_WHITESPACE, indent))

    return newtokens


def expand_macros(tokens):
    tokens = tokens[:]

    # collect macros
    macros = []
    i = 0
    while i < len(tokens):
        if not (tokens[i][0] == TOK_WORD and tokens[i][1] == "macro"):
            i += 1
            continue
        startp = i
        i += 1

        if tokens[i][0] != TOK_WHITESPACE:
            raise Exception("Expected whitespace after 'macro', got %s %s" % tokens[i])
        while tokens[i][0] == TOK_WHITESPACE:
            i += 1

        if tokens[i][0] != TOK_WORD:
            raise Exception("Expected macro name got %s %s" % tokens[i])
        macro_name = tokens[i][1]
        i += 1

        argnames = []

        while True:
            if tokens[i][0] in (TOK_NEWLINE, TOK_COMMENT):
                i += 1
                break
            if tokens[i][0] != TOK_WHITESPACE:
                raise Exception(
                    "Expected whitespace, newline, or comment after macro arguments, got %s %s"
                    % tokens[i]
                )
            while tokens[i][0] == TOK_WHITESPACE:
                i += 1
            if tokens[i][0] in (TOK_NEWLINE, TOK_COMMENT):
                i += 1
                break
            if tokens[i][0] != TOK_WORD:
                raise Exception("Expected argument name, got %s %s" % tokens[i])
            argnames.append(tokens[i][1])
            i += 1

        bodypstart = i

        while True:
            if tokens[i][0] == TOK_EOI:
                raise Exception("Got EOI while parsing macro")
            if tokens[i][0] == TOK_WORD and tokens[i][1] == "endmacro":
                break
            i += 1

        bodypend = i - 1
        while tokens[bodypend][0] in (TOK_WHITESPACE, TOK_NEWLINE):
            bodypend -= 1

        while tokens[startp - 1][0] == TOK_WHITESPACE:
            startp -= 1

        endp = i
        while tokens[endp + 1][0] == TOK_WHITESPACE:
            endp += 1
        if tokens[endp + 1][0] == TOK_NEWLINE:
            endp += 1

        macros.append(
            (macro_name, argnames, tokens[bodypstart : bodypend + 1] + [(TOK_EOI, "")])
        )

        for j in range(startp, endp + 1):
            tokens[j] = (TOK_WHITESPACE, "")

    # fixup macros
    for i in range(len(macros)):
        (name, argnames, body) = macros[i]
        newbody = body[:]
        # TODO: better way to make sure these don't conflict with user variables
        newargnames = ["$__macro_{}_{}".format(name, a) for a in argnames]
        argnames_to_newargnames = {"$" + a: n for (a, n) in zip(argnames, newargnames)}

        newbody = strip_indent(newbody, get_indentation_at(body, 0))

        for j in range(len(newbody)):
            if newbody[j][0] == TOK_WORD and newbody[j][1] in argnames_to_newargnames:
                newbody[j] = (TOK_WORD, argnames_to_newargnames[newbody[j][1]])
        macros[i] = (name, newargnames, newbody)

    macros_as_commands = {
        "macro_{}".format(name): {
            "arguments": [
                {"name": argname, "type": "anything"} for argname in argnames
            ],
            "name": name,
            "match": name,
            "type": "command",
        }
        for (name, argnames, body) in macros
    }
    macros_by_name = {
        name.lower(): (argnames, body) for (name, argnames, body) in macros
    }

    # parse and do expansions
    parsetree = parse(tokens, macros_as_commands)
    insertions = []
    for toplevel in parsetree:
        if toplevel.get("type") != "Command":
            continue
        if toplevel["name"].lower() not in macros_by_name:
            continue

        insertion_point = toplevel["start_token"]
        argvars = []
        argnames = macros_by_name[toplevel["name"].lower()][0]
        for i, a in enumerate(toplevel["args"]):
            if "start_token" not in a:
                a["start_token"] = a["token"]
            if "end_token" not in a:
                a["end_token"] = a["token"]
            argvar = argnames[i]

            if a["type"] == "Variable":
                insertions.append(
                    (
                        insertion_point,
                        lexcaos(
                            "doif type {value} = 0 or type {value} = 1 setv {var} {value} elif type {value} = 2 sets {var} {value} else seta {var} {value} endi\n".format(
                                value=a["value"], var=argvar
                            )
                        ),
                    )
                )
            elif a["type"] == "Command" and a["commandret"] == "variable":
                # e.g. FROM in Docking Station, which can be an agent or a string
                insertions.append(
                    (
                        insertion_point,
                        lexcaos(
                            "doif type {value} = 0 or type {value} = 1 setv {var} {value} elif type {value} = 2 sets {var} {value} else seta {var} {value} endi\n".format(
                                value=tokens_to_string(
                                    tokens[a["start_token"] : a["end_token"] + 1]
                                ),
                                var=argvar,
                            )
                        ),
                    )
                )
            else:
                insertions.append(
                    (
                        insertion_point,
                        [
                            (TOK_WORD, get_setx_for_command(a)),
                            (TOK_WHITESPACE, " "),
                            (TOK_WORD, argvar),
                            (TOK_WHITESPACE, " "),
                        ]
                        + tokens[a["start_token"] : a["end_token"] + 1]
                        + [(TOK_NEWLINE, "\n")],  # TODO: correct newline
                    )
                )
            for j in range(a["start_token"], a["end_token"] + 1):
                tokens[j] = (TOK_WHITESPACE, "")
        for j in range(toplevel["start_token"], toplevel["end_token"] + 1):
            tokens[j] = (TOK_WHITESPACE, "")

        indent = get_indentation_at(tokens, insertion_point)
        insertions.append(
            (
                insertion_point,
                add_indent(macros_by_name[toplevel["name"].lower()][1], indent),
            )
        )

    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)

    return tokens


def extendedcaos_to_caos(s):
    tokens = list(lexcaos(s))
    tokens = move_comments_to_own_line(tokens)
    # tokens = remove_dummies(tokens)
    tokens = objectvariables_to_ovxx(tokens)
    # tokens = remove_dummies(tokens)
    tokens = expand_macros(tokens)
    # tokens = remove_dummies(tokens)
    tokens = explicit_targs(tokens)
    # tokens = remove_dummies(tokens)
    tokens = namedvariables_to_vaxx(tokens)
    # tokens = remove_dummies(tokens)
    tokens = remove_extraneous_targ_saving(tokens)
    # tokens = remove_dummies(tokens)
    tokens = remove_double_targ(tokens)
    # tokens = remove_dummies(tokens)

    return tokens_to_string(tokens)
