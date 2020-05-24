# encoding: utf-8

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


def get_indentation_at_previous_line(tokens, i):
    assert tokens[i][0] != TOK_NEWLINE
    original_i = i

    while True:
        # go backwards to newline or beginning of input
        while i >= 0:
            if tokens[i][0] == TOK_NEWLINE:
                break
            i -= 1

        # if we hit the beginning of the input, just return the indent of the original line
        if i <= 0:
            return get_indentation_at(tokens, original_i)

        # now we're at the newline ending the previous line
        # we want to know if there's anything here, or if it's just whitespace
        i -= 1
        while i >= 0:
            if tokens[i][0] == TOK_WHITESPACE:
                i -= 1
            else:
                break

        # if we hit the beginning of the input, just return the indent of the original line
        if i <= 0:
            return get_indentation_at(tokens, original_i)

        # if it's a newline, then this line was just whitespace. continue
        if tokens[i][0] == TOK_NEWLINE:
            i -= 1
            continue

        # otherwise we have a line with something other than whitespace
        return get_indentation_at(tokens, i)


def nodes_to_string(nodes):
    parts = []

    def visit(n):
        type = n["type"]
        if type in ("Command",):
            parts.append(n["name"])
            for a in n["args"]:
                visit(a)
        elif type in ("Condition",):
            for a in n["args"]:
                visit(a)
        elif type in ("DotCommand",):
            parts.append(n["targ"] + "." + n["name"])
            for a in n["args"]:
                visit(a)
        elif type in (
            "Variable",
            "LiteralString",
            "LiteralInteger",
            "LiteralFloat",
            "LiteralBytestring",
            "ConditionKeyword",
        ):
            parts.append(n["value"])
        else:
            raise Exception("Unimplemented node type %r" % n)

    for n in nodes:
        visit(n)
    return " ".join(parts)


def node_to_string(node):
    return nodes_to_string([node])


def generate_save_result_to_variable(variable_name, node):
    value = node_to_string(node)

    # TODO: can we look at what the parent is expecting?
    # e.g. "va00", or "FROM" in Docking Station, which can be an agent or a string
    if node["type"] == "Variable" or (
        node["type"] == "Command" and node["commandret"] == "variable"
    ):
        # avoid ELIF because it's hard for other transformations to handle
        return generate_snippet(
            (
                "doif type {value} = 0 or type {value} = 1\n"
                + "    setv {var} {value}\n"
                + "else\n"
                + "    doif type {value} = 2\n"
                + "        sets {var} {value}\n"
                + "    else\n"
                + "        seta {var} {value}\n"
                + "    endi\n"
                + "endi\n"
            ).format(value=value, var=variable_name)
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
        value,
        "\n",
    )


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


def get_endi_index_for(parsetree, p):
    assert parsetree[p]["type"] == "Command"
    assert parsetree[p]["name"] in ("doif", "elif")

    nesting = 0

    while True:
        p += 1
        if parsetree[p]["type"] == "Command" and parsetree[p]["name"] == "doif":
            nesting += 1
        elif parsetree[p]["type"] == "Command" and parsetree[p]["name"] == "endi":
            if nesting == 0:
                return p
            else:
                nesting -= 1
    raise Exception("Couldn't find matching endi")


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


def explicit_targs(tokens, parsetree):
    def visit(node, in_dotcommand):
        if node["type"] == "DotCommand" or (
            node["type"] in ("Command", "Condition") and in_dotcommand
        ):
            insertions = []
            for a in node["args"]:
                insertions += visit(a, True)

            startp = node["start_token_in_parent"] + toplevel["start_token"]
            value_variable = "$__{}_{}__t{}".format(
                node.get("targ", "").lstrip("$"), node["name"], startp
            )

            indent = get_indentation_at(tokens, toplevel["start_token"])
            if node["type"] == "DotCommand":
                newnode = dict(node)
                newnode.update({"type": "Command"})
                insertions.append(
                    add_indent(
                        generate_snippet(
                            "seta $__saved_targ targ\n",
                            "targ {}\n".format(node["targ"]),
                            generate_save_result_to_variable(value_variable, newnode),
                            "targ $__saved_targ\n",
                        ),
                        indent,
                    )
                )
            else:
                insertions.append(
                    add_indent(
                        generate_save_result_to_variable(value_variable, node), indent,
                    )
                )
            whiteout_child_node_from_tokens(toplevel, node, tokens)
            tokens[startp] = (TOK_WORD, value_variable)
            node.clear()
            node.update(
                {"type": "Variable", "value": value_variable,}
            )
            return insertions

        elif node.get("type", "") in ("Command", "Condition"):
            insertions = []
            for a in node["args"]:
                insertions += visit(a, in_dotcommand)
            return insertions
        else:
            return []

    node_index = 0
    while node_index < len(parsetree):
        toplevel = parsetree[node_index]
        if toplevel["type"] not in ("Command", "Condition", "DotCommand"):
            node_index += 1
            continue

        insertion_point = toplevel["start_token"]
        if toplevel["type"] == "Command" and toplevel["name"] == "elif":
            raise Exception("Can't handle ELIF commands")

        while tokens[insertion_point - 1][0] == TOK_WHITESPACE:
            insertion_point -= 1

        insertions = []
        for a in toplevel["args"]:
            insertions += visit(a, toplevel["type"] == "DotCommand")

        for snippet in insertions:
            node_index = insert_before_node(tokens, parsetree, node_index, snippet)

        if toplevel["type"] == "DotCommand":
            indent = get_indentation_at(tokens, toplevel["start_token"])
            node_index = insert_before_node(
                tokens,
                parsetree,
                node_index,
                add_indent(
                    generate_snippet(
                        "seta $__saved_targ targ\n",
                        "targ {}\n".format(toplevel["targ"]),
                        tokens[toplevel["start_token"] + 2 : toplevel["end_token"] + 1],
                        "\ntarg $__saved_targ\n",
                    ),
                    indent,
                ),
            )
            whiteout_node_and_line(tokens, parsetree, node_index)
        else:
            node_index += 1


def remove_extraneous_targ_saving(tokens, parsetree):
    node_index = 0
    while node_index < len(parsetree) - 1:
        if (
            parsetree[node_index]["type"] == "Command"
            and parsetree[node_index]["name"] == "targ"
            and len(parsetree[node_index]["args"]) == 1
            and parsetree[node_index]["args"][0]["type"] == "Variable"
            and parsetree[node_index + 1]["type"] == "Command"
            and parsetree[node_index + 1]["name"] == "seta"
            and len(parsetree[node_index + 1]["args"]) == 2
            and parsetree[node_index + 1]["args"][0]["type"] == "Variable"
            and parsetree[node_index + 1]["args"][0]["value"]
            == parsetree[node_index]["args"][0]["value"]
            and parsetree[node_index + 1]["args"][1]["type"] == "Command"
            and parsetree[node_index + 1]["args"][1]["name"] == "targ"
        ):
            whiteout_node_and_line(tokens, parsetree, node_index + 1)
        elif (
            parsetree[node_index]["type"] == "Command"
            and parsetree[node_index]["name"] == "targ"
            and len(parsetree[node_index]["args"]) == 1
            and parsetree[node_index]["args"][0]["type"] == "Command"
            and re.match(r"^va\d\d$", parsetree[node_index]["args"][0]["name"])
            and parsetree[node_index + 1]["type"] == "Command"
            and parsetree[node_index + 1]["name"] == "seta"
            and len(parsetree[node_index + 1]["args"]) == 2
            and parsetree[node_index + 1]["args"][0]["type"] == "Command"
            and parsetree[node_index + 1]["args"][0]["name"]
            == parsetree[node_index]["args"][0]["name"]
            and parsetree[node_index + 1]["args"][1]["type"] == "Command"
            and parsetree[node_index + 1]["args"][1]["name"] == "targ"
        ):
            whiteout_node_and_line(tokens, parsetree, node_index + 1)
        else:
            node_index += 1


def whiteout_node_from_tokens(node, tokens):
    startp = node["start_token"]
    endp = node["end_token"]
    for j in range(startp, endp + 1):
        tokens[j] = (TOK_WHITESPACE, "")


def whiteout_child_node_from_tokens(parent_node, child_node, tokens):
    startp = parent_node["start_token"] + child_node["start_token_in_parent"]
    endp = parent_node["start_token"] + child_node["end_token_in_parent"]
    for j in range(startp, endp + 1):
        tokens[j] = (TOK_WHITESPACE, "")


def whiteout_node_and_line(tokens, nodes, node_index):
    whiteout_node_and_line_from_tokens(nodes[node_index], tokens)
    del nodes[node_index]


def whiteout_node_and_line_from_tokens(node, tokens):
    startp = node["start_token"]
    endp = node["end_token"]

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


def remove_double_targ(tokens, parsetree):
    node_index = 0
    while node_index < len(parsetree) - 1:
        if (
            parsetree[node_index]["type"] == "Command"
            and parsetree[node_index]["name"] == "targ"
            and parsetree[node_index + 1]["type"] == "Command"
            and parsetree[node_index + 1]["name"] == "targ"
        ):
            whiteout_node_and_line(tokens, parsetree, node_index)
        else:
            node_index += 1

    node_index = 0
    while node_index < len(parsetree) - 2:
        if (
            parsetree[node_index]["type"] == "Command"
            and parsetree[node_index]["name"] == "targ"
            and parsetree[node_index]["args"][0]["type"] == "Command"
            and len(parsetree[node_index]["args"][0]["args"]) == 0
            and parsetree[node_index + 1]["type"] == "Command"
            and parsetree[node_index + 1]["name"] == "setv"
            and parsetree[node_index + 2]["type"] == "Command"
            and parsetree[node_index + 2]["name"] == "targ"
            and parsetree[node_index + 2]["args"][0]["type"] == "Command"
            and parsetree[node_index + 2]["args"][0]["name"]
            == parsetree[node_index]["args"][0]["name"]
        ):
            whiteout_node_and_line(tokens, parsetree, node_index + 2)
        else:
            node_index += 1


def expand_agentvariables(tokens, parsetree):

    # build object variable mapping
    var_mapping = {}
    for toplevel in parsetree:
        if not toplevel["type"] == "AgentVariableDefinition":
            continue
        var_mapping[toplevel["name"]] = toplevel["value"]

        whiteout_node_and_line_from_tokens(toplevel, tokens)

    # do replacements
    def visit(node, toplevel_node):
        if node["type"] == "DotVariable":
            insertion_point = node["start_token_in_parent"]
            variable_index = var_mapping[node["name"]][2:4]
            whiteout_child_node_from_tokens(toplevel_node, node, tokens)

            if node["targ"] == "targ":
                return [(insertion_point, generate_snippet("ov" + variable_index))]
            elif node["targ"] == "ownr":
                return [(insertion_point, generate_snippet("mv" + variable_index))]
            else:
                return [
                    (
                        insertion_point,
                        generate_snippet(
                            "avar {} {}".format(node["targ"], variable_index)
                        ),
                    )
                ]
        elif node.get("args"):
            insertions = []
            for a in node["args"]:
                insertions += visit(a, toplevel_node)
            return insertions
        else:
            return []

    node_index = 0
    while node_index < len(parsetree):
        toplevel = parsetree[node_index]
        insertions = []
        for a in toplevel.get("args", []):
            insertions += visit(a, toplevel)

        if insertions:
            for insertion_point, toks in reversed(insertions):
                for t in reversed(toks):
                    tokens.insert(insertion_point + toplevel["start_token"], t)

            num_tokens_inserted = sum(len(_[1]) for _ in insertions)
            add_token_offset_to_nodes(parsetree[node_index + 1 :], num_tokens_inserted)

            reparsednodes = parse(
                tokens[
                    toplevel["start_token"] : toplevel["end_token"]
                    + num_tokens_inserted
                    + 1
                ]
                + [(TOK_EOI, "")]
            )
            add_token_offset_to_nodes(reparsednodes, toplevel["start_token"])
            assert len(reparsednodes) == 1
            parsetree[node_index] = reparsednodes[0]

        node_index += 1


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
    for i, t in enumerate(tokens):
        newtokens.append(t)
        if t[0] == TOK_NEWLINE and i + 1 != len(tokens):
            newtokens.append((TOK_WHITESPACE, indent))

    return newtokens


def expand_macros(tokens, parsetree):
    # collect macros
    macros = []
    p = 0
    while p < len(parsetree):
        if parsetree[p]["type"] != "MacroDefinitionStart":
            p += 1
            continue

        start_node = parsetree[p]
        for a in parsetree[p]["argnames"]:
            if a[0] == "$":
                raise Exception(
                    "Macro argument name mustn't start with '$', got %r" % a
                )
        p += 1

        while True:
            if p >= len(tokens):
                raise Exception("Didn't see 'endmacro'")
            if parsetree[p]["type"] == "MacroDefinitionEnd":
                break
            p += 1

        end_node = parsetree[p]
        macros.append(
            (
                start_node["name"],
                start_node["argnames"],
                tokens[
                    start_node["body_start_token"] : parsetree[p - 1]["end_token"] + 1
                ],
            )
        )
        p += 1

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

    macros_by_name = {
        name.lower(): (argnames, body) for (name, argnames, body) in macros
    }

    # parse and do expansions
    last_macro_start_index = None
    node_index = 0
    while node_index < len(parsetree):
        toplevel = parsetree[node_index]
        if toplevel["type"] == "MacroDefinitionEnd":
            startp = parsetree[last_macro_start_index]["start_token"]
            while startp > 0 and tokens[startp - 1][0] == TOK_WHITESPACE:
                startp -= 1
            endp = toplevel["end_token"]
            while tokens[endp + 1][0] == TOK_WHITESPACE:
                endp += 1
            if tokens[endp + 1][0] == TOK_NEWLINE:
                endp += 1
            for j in range(startp, endp + 1):
                tokens[j] = (TOK_WHITESPACE, "")
            del parsetree[last_macro_start_index : node_index + 1]
            node_index = last_macro_start_index
            continue
        if toplevel["type"] == "MacroDefinitionStart":
            last_macro_start_index = node_index
            node_index += 1
            continue
        if toplevel["type"] != "Command":
            node_index += 1
            continue
        if toplevel["name"].lower() not in macros_by_name:
            node_index += 1
            continue

        indent = get_indentation_at(tokens, toplevel["start_token"])

        argvars = []
        argnames = macros_by_name[toplevel["name"].lower()][0]
        for i, a in enumerate(toplevel["args"]):
            argvar = argnames[i]

            node_index = insert_before_node(
                tokens,
                parsetree,
                node_index,
                add_indent(generate_save_result_to_variable(argvar, a), indent),
            )

        node_index = insert_before_node(
            tokens,
            parsetree,
            node_index,
            add_indent(macros_by_name[toplevel["name"].lower()][1], indent)
            + [(TOK_NEWLINE, "\n")],
        )

        whiteout_node_and_line(tokens, parsetree, node_index)


def replace_constants(tokens, parsetree):

    constant_definitions = {}  # TODO: expose from parse(tokens)
    node_index = 0
    while node_index < len(parsetree):
        toplevel = parsetree[node_index]
        if toplevel["type"] == "ConstantDefinition":
            whiteout_node_and_line(tokens, parsetree, node_index)
            constant_definitions[toplevel["name"]] = toplevel["values"]
            continue

        insertions = []
        for i, t in enumerate(
            tokens[toplevel["start_token"] : toplevel["end_token"] + 1]
        ):
            if not (t[0] == TOK_WORD and t[1][0] == ":"):
                continue
            values = []
            for v in constant_definitions[t[1]]:
                if values:
                    values.append((TOK_WHITESPACE, " "))
                values.append(v)
            insertions.append((i, values))
            tokens[toplevel["start_token"] + i] = (TOK_WHITESPACE, "")

        if insertions:
            for insertion_point, toks in reversed(insertions):
                for t in reversed(toks):
                    tokens.insert(insertion_point + toplevel["start_token"], t)

            num_tokens_inserted = sum(len(_[1]) for _ in insertions)
            add_token_offset_to_nodes(parsetree[node_index + 1 :], num_tokens_inserted)

            reparsednodes = parse(
                tokens[
                    toplevel["start_token"] : toplevel["end_token"]
                    + num_tokens_inserted
                    + 1
                ]
                + [(TOK_EOI, "")]
            )
            add_token_offset_to_nodes(reparsednodes, toplevel["start_token"])
            assert len(reparsednodes) == 1
            parsetree[node_index] = reparsednodes[0]

        node_index += 1


def add_token_offset_to_nodes(nodes, offset):
    for n in nodes:
        n["start_token"] += offset
        n["end_token"] += offset


def insert_before_node(tokens, nodes, node_index, snippet):
    insertion_point = nodes[node_index]["start_token"]
    while tokens[insertion_point - 1][0] == TOK_WHITESPACE:
        insertion_point -= 1

    for i, x in enumerate(snippet):
        tokens.insert(insertion_point + i, x)
    offset = len(snippet)
    add_token_offset_to_nodes(nodes[node_index:], offset)

    parsedsnippet = parse(snippet + [(TOK_EOI, "")])
    add_token_offset_to_nodes(parsedsnippet, insertion_point)
    for i, x in enumerate(parsedsnippet):
        nodes.insert(node_index + i, x)

    return node_index + len(parsedsnippet)


def turn_elifs_into_elses(tokens, nodes):
    p = 0
    while p < len(nodes):
        node = nodes[p]
        if not (node["type"] == "Command" and node["name"] == "elif"):
            p += 1
            continue

        # add new else before us
        indent = get_indentation_at(tokens, node["start_token"])
        p = insert_before_node(
            tokens, nodes, p, generate_snippet(indent + "else\n" + "    ")
        )

        # change us to a doif
        tokens[node["start_token"]] = (TOK_WORD, "doif")
        node["name"] = "doif"

        # find everything until the matching endi
        endi_index = get_endi_index_for(nodes, p)

        # indent everything up to next endi
        for j in range(p + 1, endi_index):
            insert_before_node(tokens, nodes, j, generate_snippet("    "))

        # add new endi
        snippet = generate_snippet(indent + "    endi\n")
        insert_before_node(tokens, nodes, endi_index, snippet)

        # not necessary, as we're now a DOIF and will be skipped on next iteration,
        # but good practice
        p += 1


def handle_condition_short_circuiting(tokens, parsetree):
    node_index = 0
    while node_index < len(parsetree):
        node = parsetree[node_index]
        if not (
            node["type"] == "Command"
            and len(node["args"]) == 1
            and node["args"][0]["type"] == "Condition"
        ):
            node_index += 1
            continue

        condition_args = node["args"][0]["args"]
        needs_short_circuit = len(condition_args) > 3
        if not needs_short_circuit:
            node_index += 1
            continue

        # this is the tricky part
        conditionvar = "$__condition_" + str(node["start_token"])
        snippet_parts = [
            "setv {} 0\n".format(conditionvar),
        ]
        i = 0
        combiner = None
        while i < len(condition_args):
            value = nodes_to_string(condition_args[i : i + 3])
            if combiner is None:
                snippet_parts += [
                    "doif ",
                    value,
                    "\n",
                    "    setv {} 1\n".format(conditionvar),
                    "endi\n",
                ]
            elif combiner == "and":
                # TODO: negate this condition instead of the weird empty doif body?
                snippet_parts += [
                    "doif {} = 1\n".format(conditionvar),
                    "    doif ",
                    value,
                    "\n",
                    "    else\n".format(conditionvar),
                    "        setv {} 0\n".format(conditionvar),
                    "    endi\n",
                    "endi\n",
                ]
            elif combiner == "or":
                snippet_parts += [
                    "doif {} = 0\n".format(conditionvar),
                    "    doif ",
                    value,
                    "\n",
                    "        setv {} 1\n".format(conditionvar),
                    "    endi\n",
                    "endi\n",
                ]
            else:
                assert False
            i += 3
            if i < len(condition_args):
                combiner = condition_args[i]["value"].lower()
                i += 1

        # remove last newline, or the wrong indentation will be added to it
        if snippet_parts[-1][-1] == "\n":
            snippet_parts[-1] = snippet_parts[-1][:-1]

        # figure out indentation - if we're coming down a level, we want these insertions to be at the previous indentation
        previous_indent = get_indentation_at_previous_line(tokens, node["start_token"])
        current_indent = get_indentation_at(tokens, node["start_token"])

        if len(previous_indent) < len(current_indent):
            # if the previous indent is smaller, we just went up a level, so stay there
            previous_indent = current_indent

        indent = get_indentation_at(tokens, node["start_token"])

        node_index = insert_before_node(
            tokens,
            parsetree,
            node_index,
            add_indent(generate_snippet(*snippet_parts), previous_indent),
        )

        node_index = insert_before_node(
            tokens,
            parsetree,
            node_index,
            (
                [(TOK_NEWLINE, "\n")]
                + add_indent(
                    generate_snippet("{} {} = 1".format(node["name"], conditionvar)),
                    indent,
                )
                + [(TOK_NEWLINE, "\n")]
            ),
        )
        whiteout_node_and_line(tokens, parsetree, node_index)


def extendedcaos_to_caos(s):
    tokens = lexcaos(s)

    # Move comments to own line first, so they stay before any additional lines
    # that get added
    tokens = move_comments_to_own_line(tokens)

    # Get the initial parsetree. Transformations will modify tokens and the parsetree
    # at the same time
    parsetree = parse(tokens)

    # Turn ELIF into ELSE/DOIF. This absolutely must come near the beginning - other
    # transformations make the assumption that commands on a previous line will
    # execute first. ELIF is the one command that breaks that rule!
    # TODO: undo this transformation later on, if no other transformation has
    # added anything in-between the ELSE and DOIF
    turn_elifs_into_elses(tokens, parsetree)

    # Handle condition short-circuiting by extracting boolean logic and doing
    # it manually. This needs to come before macro expansion, explicit targs,
    # or any other transformation that modify the condition; otherwise, the
    # short-circuiting won't actually work
    handle_condition_short_circuiting(tokens, parsetree)

    # Transformations in no particular order
    expand_macros(tokens, parsetree)
    explicit_targs(tokens, parsetree)
    replace_constants(tokens, parsetree)
    expand_agentvariables(tokens, parsetree)

    # Explicit targ adds in a lot of cruft around saving targ and resetting
    # targ. Try to remove the cruft when possible to make the end result
    # easier to read and debug
    remove_extraneous_targ_saving(tokens, parsetree)
    remove_double_targ(tokens, parsetree)

    # Turn namedvariables to vaxx variables. This must come after all transformations
    # that add new variables (targ saving, macro arguments, condition short
    # circuiting, etc.
    tokens = namedvariables_to_vaxx(tokens)

    return tokens_to_string(tokens)
