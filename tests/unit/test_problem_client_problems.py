from typing import Any

import pytest
from pydantic import ValidationError

from mthds.protocol.problem.client_problems import make_client_problem, render_template
from mthds.protocol.problem.registry import CORE_CODE_SPECS, CoreCode, ParamType, RaisedAs


class TestClientProblems:
    @pytest.mark.parametrize(
        ("topic", "template", "params", "expected"),
        [
            ("a parameter", "The input '{input}' is missing.", {"input": "contract"}, "The input 'contract' is missing."),
            ("a list joined", "Inputs it never reads: {variables}.", {"variables": ["draft", "notes"]}, "Inputs it never reads: draft, notes."),
            ("an integral number", "Within {seconds} seconds.", {"seconds": 30.0}, "Within 30 seconds."),
            ("a fractional number", "Within {seconds} seconds.", {"seconds": 2.5}, "Within 2.5 seconds."),
            ("literal braces", "Write {{name}} for {name}.", {"name": "x"}, "Write {name} for x."),
            ("no parameter", "The runtime is unavailable.", {}, "The runtime is unavailable."),
        ],
    )
    def test_render_template_fills_the_parameters(self, topic: str, template: str, params: dict[str, Any], expected: str) -> None:
        """`{name}` takes the parameter's value, a list joined with ", ", and doubled braces are literal."""
        assert render_template(template, params=params) == expected, topic

    @pytest.mark.parametrize(
        ("topic", "template"),
        [
            ("a parameter not given", "The input '{input}' is missing."),
            ("an unclosed brace", "The input '{input is missing."),
            ("a lone closing brace", "The input input} is missing."),
            ("a closing brace after a literal one", "Write {{name}}} for it."),
        ],
    )
    def test_render_template_refuses_what_it_cannot_fill(self, topic: str, template: str) -> None:
        with pytest.raises(ValueError, match="template"):
            render_template(template, params={})
        assert topic

    @pytest.mark.parametrize(
        ("code", "params", "expected_step_kind"),
        [
            # The caller is the actor of the input domain, and whoever reads a runtime problem is its actor.
            (CoreCode.CLIENT_ARGUMENT_INVALID, {"argument": "pipe_code", "reason": "missing"}, "change_input"),
            (CoreCode.CLIENT_UNREACHABLE, {"base_url": "http://localhost:8081"}, "retry"),
            # The operator is not the caller, so the caller reads the step aimed at any other reader.
            (CoreCode.CLIENT_LINK_REFUSED, {"reason": "plain_http"}, "report"),
        ],
    )
    def test_the_caller_reads_the_step_aimed_at_it(self, code: CoreCode, params: dict[str, Any], expected_step_kind: str) -> None:
        """The step is the actor's for the domains `input` and `runtime`, and the other reader's for `method`, `account` and `operator`."""
        problem = make_client_problem(code, params=params)

        assert problem.as_wire()["next_step"]["kind"] == expected_step_kind
        assert problem.type == f"https://mthds.ai/errors/{code}"
        assert problem.title == CORE_CODE_SPECS[code].title
        assert problem.status is None

    def test_an_operator_only_parameter_is_left_out_and_params_stays_present(self) -> None:
        """A code that declares parameters carries `params` even when every one it holds is operator-only, so it may be empty."""
        problem = make_client_problem(CoreCode.RUNTIME_UNAVAILABLE, params={"dependency": "postgres"}, status=503, retry_after=5)

        assert problem.as_wire() == {
            "type": "https://mthds.ai/errors/runtime.unavailable",
            "title": "The runtime or a service it depends on is unavailable",
            "status": 503,
            "detail": "The runtime, or a service it depends on, is unavailable.",
            "code": "runtime.unavailable",
            "domain": "runtime",
            "retry": "yes",
            "retry_after": 5,
            "next_step": {"kind": "retry", "detail": "Send the request again after a while."},
            "params": {},
        }

    def test_a_code_without_parameters_carries_no_params(self) -> None:
        problem = make_client_problem(CoreCode.CLIENT_ABORTED)

        assert "params" not in problem.as_wire()

    def test_an_integral_time_limit_is_written_as_an_integer(self) -> None:
        """A client's float time limit of 30.0 is written `30`, as a JavaScript client writes it."""
        problem = make_client_problem(CoreCode.CLIENT_TIMEOUT, params={"seconds": 30.0})

        assert problem.as_wire()["params"] == {"seconds": 30}
        assert isinstance(problem.as_wire()["params"]["seconds"], int)
        assert problem.detail == "The runtime did not answer within 30 seconds."

    def test_an_undeclared_or_mistyped_parameter_is_refused(self) -> None:
        with pytest.raises(ValueError, match="declares no parameter"):
            make_client_problem(CoreCode.CLIENT_TIMEOUT, params={"seconds": 30, "route": "/models"})
        with pytest.raises(ValidationError):
            make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": "five hundred"})
        # A number is read strictly: pydantic's lax mode would coerce these two.
        with pytest.raises(ValidationError):
            make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": "500"})
        with pytest.raises(ValidationError):
            make_client_problem(CoreCode.CLIENT_TIMEOUT, params={"seconds": True})

    @pytest.mark.parametrize("code", [code for code, spec in CORE_CODE_SPECS.items() if spec.raised_as is RaisedAs.CLIENT])
    def test_every_client_code_builds_from_its_parameters(self, code: str) -> None:
        """Every code a client raises builds into a problem from sample values of its parameters, its sentences fully filled."""
        spec = CORE_CODE_SPECS[code]
        params: dict[str, Any] = {}
        for param in spec.params:
            if param.optional or param.operator_only:
                continue
            match param.param_type:
                case ParamType.INTEGER | ParamType.SECONDS | ParamType.BYTES:
                    params[param.name] = 7
                case ParamType.LIST:
                    params[param.name] = ["one", "two"]
                case ParamType.ENUM:
                    params[param.name] = param.values[0]
                case ParamType.SHA256:
                    params[param.name] = "0" * 64
                case ParamType.IDENTIFIER | ParamType.CALLER_TEXT:
                    params[param.name] = "sample"
        problem = make_client_problem(CoreCode(code), params=params)

        assert problem.code == code
        assert "{" not in problem.detail
        assert "{" not in problem.next_step.detail

    @pytest.mark.parametrize("code", list(CORE_CODE_SPECS))
    def test_every_core_template_renders_with_its_braces_matched(self, code: str) -> None:
        """Every sentence of every core code renders from its declared parameters, so no registry template holds an unmatched brace."""
        spec = CORE_CODE_SPECS[code]
        params = {param.name: "sample" for param in spec.params}

        for template in (spec.detail, spec.actor_step.detail, spec.other_step.detail):
            rendered = render_template(template, params=params)
            for param in spec.params:
                assert f"{{{param.name}}}" not in rendered, f"{code}: {template}"
