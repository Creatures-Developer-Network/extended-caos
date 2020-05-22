import re

from caoscommandinfo import *
from caoslexer import *


class ParserState:
    __slots__ = [
        "p",
        "tokens",
        "commands",
        "command_namespaces",
        "constant_definitions",
        "macro_definitions",
    ]

    def __init__(self, tokens, commands):
        self.tokens = tokens
        self.commands = commands
        self.command_namespaces = {
            _.get("namespace") for _ in commands.values() if _.get("namespace")
        }
        self.constant_definitions = {}
        self.macro_definitions = {}
        self.p = 0

    def peekmatch(self, newp, toktypes):
        if not isinstance(toktypes, (tuple, list, set)):
            toktypes = (toktypes,)
        if self.tokens[newp][0] not in toktypes:
            raise Exception("Expected %r, got %s\n" % (toktypes, self.tokens[newp][0]))


def caoscondition(args, start_token):
    end_token = args[-1].get("end_token") or args[-1].get("token")
    return {
        "type": "Condition",
        "args": args,
        "start_token": start_token,
        "end_token": end_token,
    }


def caosconditionkeyword(value):
    return {"type": "ConditionKeyword", "value": value}


def maybe_eat_whitespace(state):
    ate_whitespace = False
    while state.tokens[state.p][0] == TOK_WHITESPACE:
        ate_whitespace = True
        state.p += 1
    return ate_whitespace


def maybe_eat_whitespace_or_newline(state):
    ate_whitespace = False
    while state.tokens[state.p][0] in (TOK_WHITESPACE, TOK_NEWLINE):
        ate_whitespace = True
        state.p += 1
    return ate_whitespace


def maybe_eat_whitespace_or_newline_or_comment(state):
    ate_whitespace = False
    while state.tokens[state.p][0] in (TOK_WHITESPACE, TOK_NEWLINE, TOK_COMMENT):
        ate_whitespace = True
        state.p += 1
    return ate_whitespace


def eat_whitespace(state):
    if not maybe_eat_whitespace(state):
        raise Exception(
            "Expected whitespace, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )


def eat_whitespace_or_newline(state):
    if not maybe_eat_whitespace_or_newline(state):
        raise Exception(
            "Expected whitespace or newline, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )


def parse_condition(state):
    left = parse_value(state)

    eat_whitespace(state)

    if state.tokens[state.p][0] != TOK_WORD:
        raise Exception(
            "Expected comparison, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )
    startp = state.p
    comparison = state.tokens[state.p][1]
    state.p += 1
    if comparison not in (
        "eq",
        "ne",
        "gt",
        "ge",
        "lt",
        "le",
        "=",
        "<>",
        ">",
        ">=",
        "<",
        "<=",
    ):
        raise Exception("Unknown comparison operator '%s'" % comparison)

    eat_whitespace(state)

    right = parse_value(state)

    ate_whitespace = maybe_eat_whitespace(state)
    if (
        ate_whitespace
        and state.tokens[state.p][0] == TOK_WORD
        and state.tokens[state.p][1] in ("and", "or")
    ):
        combiner = state.tokens[state.p][1]
        state.p += 1
        remainder = parse_condition(state)
        return caoscondition(
            [
                left,
                caosconditionkeyword(comparison),
                right,
                caosconditionkeyword(combiner),
            ]
            + remainder["args"],
            startp,
        )
    else:
        return caoscondition([left, caosconditionkeyword(comparison), right], startp)


def get_command_info(state, namespace, command_name, is_toplevel):
    namespace = namespace.lower()
    command_name = command_name.lower()

    commandnormalized = command_name
    if re.match(r"^va\d\d$", command_name):
        commandnormalized = "vaxx"
    if re.match(r"^ov\d\d$", command_name):
        commandnormalized = "ovxx"
    if re.match(r"^mv\d\d$", command_name):
        commandnormalized = "mvxx"

    ci = state.commands.get((namespace, commandnormalized, is_toplevel))
    if ci:
        return ci

    if is_toplevel and namespace == "" and commandnormalized in state.macro_definitions:
        return {
            "arguments": [
                {"name": a, "type": "anything"}
                for a in state.macro_definitions[commandnormalized]["argnames"]
            ],
            "type": "command",
        }

    raise Exception(
        "Unknown command '%s'" % ((namespace + " " if namespace else "") + command_name)
    )


def parse_command(state, is_toplevel):
    startp = state.p
    dotcommand = False

    if state.tokens[state.p][0] != TOK_WORD:
        raise Exception(
            "Expected command name, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )
    if state.tokens[state.p][1][0] == "$" or state.tokens[state.p + 1][0] == TOK_DOT:
        if state.tokens[state.p][1][0] == "$":
            assert state.tokens[state.p + 1][0] == TOK_DOT
        dotcommand = True
        namespace = ""
        targ = state.tokens[state.p][1]
        state.p += 2
        command = state.tokens[state.p][1]
        if command[0] == "$":
            state.p += 1
            return {
                "type": "DotVariable",
                "name": command,
                "targ": targ,
                "start_token": startp,
                "end_token": state.p - 1,
            }
        command = command.lower()
    elif state.tokens[state.p][1].lower() in state.command_namespaces:
        namespace = state.tokens[state.p][1].lower()
        state.p += 1
        eat_whitespace(state)
        command = state.tokens[state.p][1].lower()
    else:
        namespace = ""
        command = state.tokens[state.p][1].lower()

    commandnormalized = command
    if re.match(r"(?i)^va\d\d$", command):
        commandnormalized = "vaxx"
    if re.match(r"(?i)^ov\d\d$", command):
        commandnormalized = "ovxx"
    if re.match(r"(?i)^mv\d\d$", command):
        commandnormalized = "mvxx"

    commandinfo = get_command_info(state, namespace, commandnormalized, is_toplevel)
    state.p += 1

    args = []
    num_args_parsed = 0
    while num_args_parsed < len(commandinfo["arguments"]):
        _ = commandinfo["arguments"][num_args_parsed]
        eat_whitespace(state)
        if _["type"] == "condition":
            args.append(parse_condition(state))
        elif _["type"] == "label":
            if state.tokens[state.p][0] != TOK_WORD:
                raise Exception("Expected label, got %s '%s'\n" % (t[0], t[1]))
            args.append(
                {"type": "Label", "value": state.tokens[state.p][1], "token": state.p}
            )
            state.p += 1
        else:
            args.append(parse_value(state))
        if args[-1]["type"] == "Constant":
            num_args_parsed += len(state.constant_definitions[args[-1]["name"]])
        else:
            num_args_parsed += 1

    end_token = state.p - 1

    if dotcommand:
        return {
            "type": "DotCommand",
            "targ": targ,
            "name": command,
            "commandtype": ("statement" if is_toplevel else "expression"),
            "commandret": commandinfo["type"],
            "args": args,
            "start_token": startp,
            "end_token": end_token,
        }
    else:
        return {
            "type": "Command",
            "name": (namespace + " " if namespace else "") + command,
            "commandtype": ("statement" if is_toplevel else "expression"),
            "commandret": commandinfo["type"],
            "args": args,
            "start_token": startp,
            "end_token": end_token,
        }


def parse_constant_definition(state):
    assert (
        state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1] == "constant"
    )
    startp = state.p

    state.p += 1
    eat_whitespace(state)

    if not (
        state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1][0] == ":"
    ):
        raise Exception(
            "Expected constant name after 'constant', got %r" % (state.tokens[state.p],)
        )
    name = state.tokens[state.p][1]
    state.p += 1

    values = []

    eat_whitespace(state)
    if state.tokens[state.p][0] not in (TOK_INTEGER, TOK_STRING):
        raise Exception(
            "Expected literal in 'constant' definition, got %r"
            % (state.tokens[state.p],)
        )
    values.append(state.tokens[state.p])
    state.p += 1

    while True:
        if state.tokens[state.p][0] in (TOK_NEWLINE, TOK_EOI):
            break
        eat_whitespace(state)
        if state.tokens[state.p][0] in (TOK_NEWLINE, TOK_EOI):
            break
        if state.tokens[state.p][0] not in (TOK_INTEGER, TOK_STRING):
            raise Exception(
                "Expected literal in 'constant' definition, got %r"
                % (state.tokens[state.p],)
            )
        values.append(state.tokens[state.p])
        state.p += 1

    endp = state.p - 1

    state.constant_definitions[name] = values
    return {
        "type": "ConstantDefinition",
        "name": name,
        "values": values,
        "start_token": startp,
        "end_token": endp,
    }


def parse_agent_variable(state):
    assert (
        state.tokens[state.p][0] == TOK_WORD
        and state.tokens[state.p][1] == "agent_variable"
    )
    startp = state.p
    state.p += 1

    eat_whitespace(state)
    if not (
        state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1][0] == "$"
    ):
        raise Exception(
            "Expected variable name after 'agent_variable', got %r"
            % (state.tokens[state.p],)
        )
    variable_name = state.tokens[state.p][1]
    state.p += 1

    eat_whitespace(state)
    if not (
        state.tokens[state.p][0] == TOK_WORD
        and re.match(r"(?i)^ov\d\d$", state.tokens[state.p][1])
    ):
        raise Exception(
            "Expected ovXX after agent variable name, got %r" % (state.tokens[state.p],)
        )
    definition = state.tokens[state.p][1].lower()
    endp = state.p
    state.p += 1

    return {
        "type": "AgentVariableDefinition",
        "name": variable_name,
        "value": definition,
        "start_token": startp,
        "end_token": endp,
    }


def parse_macro_definition(state):
    assert state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1] == "macro"
    startp = state.p
    state.p += 1

    eat_whitespace(state)
    if not (state.tokens[state.p][0] == TOK_WORD):
        raise Exception(
            "Expected macro name after 'macro', got %r" % (state.tokens[state.p],)
        )
    macro_name = state.tokens[state.p][1].lower()
    state.p += 1

    argnames = []
    while True:
        if state.tokens[state.p][0] in (TOK_NEWLINE, TOK_EOI):
            break
        eat_whitespace(state)
        if state.tokens[state.p][0] in (TOK_NEWLINE, TOK_EOI):
            break
        if state.tokens[state.p][0] != TOK_WORD:
            raise Exception(
                "Expected argument name in 'macro' definition, got %r"
                % (state.tokens[state.p],)
            )
        argnames.append(state.tokens[state.p][1])
        state.p += 1

    endp = state.p
    state.p += 1
    bodystartp = state.p

    node = {
        "type": "MacroDefinitionStart",
        "name": macro_name,
        "argnames": argnames,
        "start_token": startp,
        "end_token": endp,
        "body_start_token": bodystartp,
    }
    state.macro_definitions[macro_name] = node
    return node


def parse_toplevel(state):
    if state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1] == "macro":
        return parse_macro_definition(state)
    elif (
        state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1] == "endmacro"
    ):
        node = {
            "type": "MacroDefinitionEnd",
            "token": state.p,
        }
        state.p += 1
        return node
    if state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1] == "constant":
        return parse_constant_definition(state)
    if (
        state.tokens[state.p][0] == TOK_WORD
        and state.tokens[state.p][1] == "agent_variable"
    ):
        return parse_agent_variable(state)
    return parse_command(state, True)


def parse_value(state):
    maybe_eat_whitespace(state)

    startp = state.p

    if state.tokens[state.p][0] == TOK_WORD:
        if state.tokens[state.p][1][0] == ":":
            state.p += 1
            return {
                "type": "Constant",
                "name": state.tokens[state.p - 1][1],
            }
        elif (
            state.tokens[state.p][1][0] == "$"
            and state.tokens[state.p + 1][0] != TOK_DOT
        ):
            value = state.tokens[state.p][1]
            state.p += 1
            state.peekmatch(
                state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE)
            )
            return {"type": "Variable", "value": value, "token": startp}
        return parse_command(state, False)
    elif state.tokens[state.p][0] == TOK_INTEGER:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return {"type": "LiteralInteger", "value": value, "token": startp}
    elif state.tokens[state.p][0] == TOK_FLOAT:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return {"type": "LiteralFloat", "value": value, "token": startp}
    elif state.tokens[state.p][0] == TOK_STRING:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return {"type": "LiteralString", "value": value, "token": startp}
    elif state.tokens[state.p][0] == TOK_BYTESTRING:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return {"type": "LiteralBytestring", "value": value, "token": startp}
    else:
        raise Exception("Unimplemented token type %s" % state.tokens[state.p][0])


def parse(tokens):
    logger.debug("Parsing...")
    command_info = {}
    for ci in COMMAND_INFO["variants"]["c3"].values():
        is_toplevel = ci["type"] == "command"
        key = (ci.get("namespace", "").lower(), ci["match"].lower(), is_toplevel)
        command_info[key] = ci
    state = ParserState(tokens, command_info)
    fst = []
    while True:
        maybe_eat_whitespace_or_newline_or_comment(state)
        if state.tokens[state.p][0] == TOK_EOI:
            break
        fst.append(parse_toplevel(state))
    return fst
