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
    ]

    def __init__(self, tokens, commands):
        self.tokens = tokens
        self.commands = commands
        self.command_namespaces = {
            _.get("namespace") for _ in commands.values() if _.get("namespace")
        }
        self.constant_definitions = {}
        self.p = 0

    def peekmatch(self, newp, toktypes):
        if not isinstance(toktypes, (tuple, list, set)):
            toktypes = (toktypes,)
        if self.tokens[newp][0] not in toktypes:
            raise Exception("Expected %r, got %s\n" % (toktypes, self.tokens[newp][0]))


def caosvariable(value, token):
    return {"type": "Variable", "value": value, "token": token}


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
    if comparison not in ("eq", "lt", "gt", "ne", "=", "<>", ">", ">=", "<", "<="):
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


def parse_command(state, is_toplevel):
    startp = state.p
    dotcommand = False

    if state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1][0] == "$":
        if state.tokens[state.p + 1][0] != TOK_DOT:
            value = state.tokens[state.p][1]
            state.p += 1
            state.peekmatch(
                state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE)
            )
            return caosvariable(value, startp)
        dotcommand = True
        namespace = ""
        targ = state.tokens[state.p][1].lower()
        state.p += 2
        command = state.tokens[state.p][1].lower()
    elif state.tokens[state.p][0] == TOK_WORD:
        if state.tokens[state.p][1].lower() in state.command_namespaces:
            namespace = state.tokens[state.p][1].lower()
            state.p += 1
            eat_whitespace(state)
            command = state.tokens[state.p][1].lower()
        elif state.tokens[state.p + 1][0] == TOK_DOT:
            dotcommand = True
            namespace = ""
            targ = state.tokens[state.p][1].lower()
            # TODO: check it's a valid command
            state.p += 2
            command = state.tokens[state.p][1].lower()
        else:
            namespace = ""
            command = state.tokens[state.p][1].lower()
    else:
        raise Exception(
            "Expected command name, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )

    commandnormalized = command
    if re.match(r"(?i)^va\d\d$", command):
        commandnormalized = "vaxx"
    if re.match(r"(?i)^ov\d\d$", command):
        commandnormalized = "ovxx"
    if re.match(r"(?i)^mv\d\d$", command):
        commandnormalized = "mvxx"

    commandinfos = [
        _
        for _ in state.commands.values()
        if _.get("namespace", "").lower() == namespace
        and _.get("match", "").lower() == commandnormalized
        and (
            (is_toplevel and _.get("type") == "command")
            or (not is_toplevel and _.get("type") != "command")
        )
    ]
    if not commandinfos:
        raise Exception(
            "Unknown command '%s'" % ((namespace + " " if namespace else "") + command)
        )
    assert len(commandinfos) == 1
    state.p += 1

    args = []
    num_args_parsed = 0
    while num_args_parsed < len(commandinfos[0]["arguments"]):
        _ = commandinfos[0]["arguments"][num_args_parsed]
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
            "command": command,
            "commandtype": ("statement" if is_toplevel else "expression"),
            "commandret": commandinfos[0]["type"],
            "args": args,
            "start_token": startp,
            "end_token": end_token,
        }
    else:
        return {
            "type": "Command",
            "name": (namespace + " " if namespace else "") + command,
            "commandtype": ("statement" if is_toplevel else "expression"),
            "commandret": commandinfos[0]["type"],
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


def parse_toplevel(state):
    if state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1] == "constant":
        return parse_constant_definition(state)
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
        return parse_command(state, False)
    elif state.tokens[state.p][0] == TOK_INTEGER:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return {"type": "LiteralInteger", "value": value, "token": startp}
    elif state.tokens[state.p][0] == TOK_STRING:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return {"type": "LiteralString", "value": value, "token": startp}
    else:
        raise Exception("Unimplemented token type %s" % state.tokens[state.p][0])


def parse(tokens, extra_command_info={}):
    command_info = dict(COMMAND_INFO["variants"]["c3"])
    command_info.update(extra_command_info)
    state = ParserState(tokens, command_info)
    fst = []
    while True:
        maybe_eat_whitespace_or_newline_or_comment(state)
        if state.tokens[state.p][0] == TOK_EOI:
            break
        fst.append(parse_toplevel(state))
    return fst
