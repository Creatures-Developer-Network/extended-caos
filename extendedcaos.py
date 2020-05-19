import itertools
import json
import re
import string
import sys

from caoslexer import *
from caosparser import *


def move_comments_to_own_line(tokens):
    tokens = tokens[:]

    i = 0
    last_newline = -1  # hack if we haven't seen a newline yet
    while i < len(tokens):
        t = tokens[i]
        if t[0] == TOK_EOI:
            break
        # bookkeeping for newlines
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
        tokens.insert(i, (TOK_WHITESPACE, get_indentation_at(tokens, i)))
        tokens.insert(i + 1, t)
        tokens.insert(i + 2, (TOK_NEWLINE, "\n"))
        i += 2  # on the newline we added, to do newline bookkeeping
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


def generate_save_result_to_variable(variable_name, node, tokens):
    startp = node.get("start_token", node.get("token"))
    endp = node.get("end_token", node.get("token"))

    # TODO: can we look at what the parent is expecting?
    # e.g. "va00", or "FROM" in Docking Station, which can be an agent or a string
    if node["type"] == "Variable" or (
        node["type"] == "Command" and node["commandret"] == "variable"
    ):
        value = tokens_to_string(tokens[startp : endp + 1])
        return generate_snippet(
            "doif type {value} = 0 or type {value} = 1 setv {var} {value} elif type {value} = 2 sets {var} {value} else seta {var} {value} endi\n".format(
                value=value, var=variable_name
            )
        )

    if node["type"] == "LiteralString":
        setx_command = "sets"
    elif node["type"] == "LiteralInteger":
        setx_command = "setv"
    elif node["type"] in ("Command", "DotCommand"):
        if node["commandret"] in ("integer", "float"):
            setx_command = "setv"
        elif node["commandret"] in ("string",):
            setx_command = "sets"
        elif node["commandret"] in ("agent",):
            setx_command = "seta"
        else:
            raise Exception("Don't know how to save result type of {}".format(node))
    else:
        raise Exception("Don't know how to save result type of {}".format(node))

    return generate_snippet(
        "{setx} {varname} ".format(setx=setx_command, varname=variable_name),
        tokens[startp : endp + 1],
        "\n",
    )


def explicit_targs_visitor(node, tokens, statement_start, in_dotcommand):
    if node.get("type", "") == "DotCommand":
        insertions = []
        for a in node["args"]:
            insertions += explicit_targs_visitor(a, tokens, statement_start, True)

        value_variable = "$__{}_{}__t{}".format(
            node["targ"].lstrip("$"), node["name"], node["start_token"]
        )

        newnode = dict(node)
        newnode.update({"type": "Command", "start_token": node["start_token"] + 2})
        insertions.append(
            (
                statement_start,
                generate_snippet(
                    "seta $__saved_targ targ\n",
                    "targ {}\n".format(node["targ"]),
                    generate_save_result_to_variable(value_variable, newnode, tokens),
                    "targ $__saved_targ\n",
                ),
            )
        )
        whiteout_node_from_tokens(node, tokens)
        tokens[node["start_token"]] = (TOK_WORD, value_variable)
        return insertions

    elif node.get("type", "") in ("Command", "Condition"):
        insertions = []
        for a in node["args"]:
            insertions += explicit_targs_visitor(
                a, tokens, statement_start, in_dotcommand
            )

        if in_dotcommand:
            value_variable = "$__targ_{}__t{}".format(node["name"], node["start_token"])
            insertions.append(
                (
                    statement_start,
                    generate_save_result_to_variable(value_variable, node, tokens),
                )
            )
            whiteout_node_from_tokens(node, tokens)
            tokens[node["start_token"]] = (TOK_WORD, value_variable)

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


def generate_snippet(*args):
    snippet = ""
    for a in args:
        if isinstance(a, str):
            snippet += a
        elif isinstance(a, list) and isinstance(a[0], tuple):
            # must be tokens
            snippet += tokens_to_string(a)
        else:
            raise Exception("Don't know how to generate snippet for %r" % a)
    # TODO: either get rid of TOK_EOI or skip it, or something
    return lexcaos(snippet)[:-1]


def explicit_targs(tokens):
    tokens = tokens[:]
    parsetree = parse(tokens)

    insertions = []
    for i, toplevel in enumerate(parsetree):
        if toplevel["type"] not in ("Command", "Condition", "DotCommand"):
            continue

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
                    generate_snippet(
                        "seta $__saved_targ targ\n",
                        "targ {}\n".format(toplevel["targ"]),
                        tokens[toplevel["start_token"] + 2 : toplevel["end_token"] + 1],
                        "\ntarg $__saved_targ",
                    ),
                )
            )

            for j in range(toplevel["start_token"], toplevel["end_token"] + 1):
                tokens[j] = (TOK_WHITESPACE, "")

    for insertion_point, toks in reversed(insertions):
        indent = get_indentation_at(tokens, insertion_point)
        for t in reversed(toks):
            if t[0] == TOK_NEWLINE:
                tokens.insert(insertion_point, (TOK_WHITESPACE, indent))
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
        if not (
            tokens[p][0] == TOK_WORD
            and (tokens[p][1].lower()[0:2] == "va" or tokens[p][1][0] == "$")
        ):
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


def whiteout_node_from_tokens(node, tokens):
    startp = node.get("start_token", node.get("token"))
    endp = node.get("end_token", node.get("token"))

    newstartp = startp
    while newstartp > 0 and tokens[newstartp - 1][0] == TOK_WHITESPACE:
        newstartp -= 1

    newendp = endp
    while tokens[newendp + 1][0] == TOK_WHITESPACE:
        newendp += 1
    if tokens[newendp + 1][0] == TOK_NEWLINE:
        newendp += 1

    # if it's on its own line, get rid of the entire line
    if (newstartp == 0 or tokens[newstartp - 1][0] == TOK_NEWLINE) and (
        tokens[newendp][0] in (TOK_NEWLINE, TOK_EOI)
    ):
        startp = newstartp
        endp = newendp

    for j in range(startp, endp + 1):
        tokens[j] = (TOK_WHITESPACE, "")


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
            break

        second_targ = parsetree[i + 2]
        if not (
            second_targ["type"] == "Command"
            and second_targ["name"] == "targ"
            and second_targ["args"][0]["type"] == "Command"
            and second_targ["args"][0]["name"] == first_targ_name
        ):
            continue

        whiteout_node_from_tokens(second_targ, tokens)

    return tokens


def expand_agentvariables(tokens):
    tokens = tokens[:]

    # build object variable mapping
    var_mapping = {}

    parsetree = parse(tokens)
    for toplevel in parsetree:
        if not toplevel["type"] == "AgentVariableDefinition":
            continue
        var_mapping[toplevel["name"]] = toplevel["value"]

        whiteout_node_from_tokens(toplevel, tokens)

    # do replacements
    insertions = []

    def visit(node):
        if node["type"] == "DotVariable":
            insertion_point = node["start_token"]
            variable_index = var_mapping[node["name"]][2:4]
            if node["targ"] == "targ":
                insertions.append(
                    (insertion_point, generate_snippet("ov" + variable_index))
                )
            elif node["targ"] == "ownr":
                insertions.append(
                    (insertion_point, generate_snippet("mv" + variable_index))
                )
            else:
                insertions.append(
                    (
                        insertion_point,
                        generate_snippet(
                            "avar {} {}".format(node["targ"], variable_index)
                        ),
                    )
                )
            whiteout_node_from_tokens(node, tokens)
        elif node.get("args"):
            for a in node["args"]:
                visit(a)

    for toplevel in parsetree:
        visit(toplevel)

    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)

    return tokens


def strip_indent(tokens):
    tokens = tokens[:]
    indent = get_indentation_at(tokens, 0)
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
            if tokens[i][1][0] == "$":
                raise Exception(
                    "Macro argument names can't start with '$', got '%s'" % tokens[i][1]
                )
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

        macros.append((macro_name, argnames, tokens[bodypstart : bodypend + 1]))

        for j in range(startp, endp + 1):
            tokens[j] = (TOK_WHITESPACE, "")

    # fixup macros
    for i in range(len(macros)):
        (name, argnames, body) = macros[i]
        newbody = body[:]
        # TODO: better way to make sure these don't conflict with user variables
        newargnames = ["$__macro_{}_{}".format(name, a) for a in argnames]
        argnames_to_newargnames = {"$" + a: n for (a, n) in zip(argnames, newargnames)}

        # add EOI for strip_indent and then remove it, ugh
        newbody = strip_indent(newbody + [(TOK_EOI, "")])[:-1]

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

            insertions.append(
                (insertion_point, generate_save_result_to_variable(argvar, a, tokens))
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


def replace_constants(tokens):
    tokens = tokens[:]
    parsetree = parse(tokens)

    insertions = []

    constant_definitions = {}  # TODO: expose from parse(tokens)

    for toplevel in parsetree:
        if toplevel["type"] == "ConstantDefinition":
            whiteout_node_from_tokens(toplevel, tokens)
            constant_definitions[toplevel["name"]] = toplevel["values"]

    for i, t in enumerate(tokens):
        if not (t[0] == TOK_WORD and t[1][0] == ":"):
            continue
        values = []
        for v in constant_definitions[t[1]]:
            if values:
                values.append((TOK_WHITESPACE, " "))
            values.append(v)
        insertions.append((i, values))
        tokens[i] = (TOK_WHITESPACE, "")

    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)

    return tokens


def handle_condition_short_circuiting(tokens):
    tokens = tokens[:]

    insertions = []
    parsetree = parse(tokens)
    for node in parsetree:
        if not (node["type"] == "Command" and node["name"].lower() == "doif"):
            continue

        assert len(node["args"]) == 1
        assert node["args"][0]["type"] == "Condition"

        condition_args = node["args"][0]["args"]
        needs_short_circuit = len(condition_args) > 3
        if not needs_short_circuit:
            continue

        # this is the tricky part
        conditionvar = "$__condition_" + str(node["start_token"])
        snippet_parts = [
            "setv {} 0\n".format(conditionvar),
        ]
        i = 0
        combiner = None
        while i < len(condition_args):
            startp = condition_args[i].get(
                "start_token", condition_args[i].get("token")
            )
            endp = condition_args[i + 2].get(
                "end_token", condition_args[i + 2].get("token")
            )
            if combiner is None:
                snippet_parts += [
                    "doif ",
                    tokens[startp : endp + 1],
                    "\n",
                    "  setv {} 1\n".format(conditionvar),
                    "endi\n",
                ]
            elif combiner == "and":
                # TODO: negate this condition instead of the weird empty doif body?
                snippet_parts += [
                    "doif {} = 1\n".format(conditionvar),
                    "  doif ",
                    tokens[startp : endp + 1],
                    "\n",
                    "  else\n".format(conditionvar),
                    "    setv {} 0\n".format(conditionvar),
                    "  endi\n",
                    "endi\n",
                ]
            elif combiner == "or":
                snippet_parts += [
                    "doif {} = 0\n".format(conditionvar),
                    "  doif ",
                    tokens[startp : endp + 1],
                    "\n",
                    "    setv {} 1\n".format(conditionvar),
                    "  endi\n",
                    "endi\n",
                ]
            else:
                assert False
            i += 3
            if i < len(condition_args):
                combiner = condition_args[i]["value"].lower()
                i += 1

        snippet_parts.append("doif {} = 1\n".format(conditionvar))

        insertions.append((node["start_token"], generate_snippet(*snippet_parts)))

        whiteout_node_from_tokens(node, tokens)

        # print(tokens_to_string(generate_snippet(*snippet_parts)))

        #
        # insertions.append(
        #     (node["start_token"], generate_snippet(
        #
        #     "setv {} 0\n".format(conditionvar)
        #
        #
        #
        # ))
        # )

        # print(node)
        # print(needs_manual_short_circuit)

    for insertion_point, toks in reversed(insertions):
        indent = get_indentation_at(tokens, insertion_point)
        for t in reversed(toks):
            if t[0] == TOK_NEWLINE:
                tokens.insert(insertion_point, (TOK_WHITESPACE, indent))
            tokens.insert(insertion_point, t)

    return tokens


def extendedcaos_to_caos(s):
    tokens = lexcaos(s)
    # this has to come first
    tokens = move_comments_to_own_line(tokens)
    # TODO: teach parser about macros, so this doesn't have to happen before parsing
    tokens = expand_macros(tokens)
    tokens = handle_condition_short_circuiting(
        tokens
    )  # TODO: move above macro expansion
    tokens = explicit_targs(tokens)  # TODO: make this ignore conditions?
    tokens = replace_constants(tokens)
    tokens = remove_extraneous_targ_saving(tokens)
    tokens = remove_double_targ(tokens)
    tokens = expand_agentvariables(tokens)
    tokens = namedvariables_to_vaxx(tokens)

    return tokens_to_string(tokens)
