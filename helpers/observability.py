"""
Observability backend selector.

The demo can log to either:

- ``galileo``   — the legacy Galileo console (``galileo`` SDK, GALILEO_API_KEY + GALILEO_CONSOLE_URL)
- ``splunk_ao`` — Splunk Agent Observability in Splunk Observability Cloud
                  (``splunk-ao`` SDK, SPLUNK_AO_REALM + SPLUNK_AO_O11Y_TOKEN)

Select with ``OBSERVABILITY_BACKEND`` (default: ``galileo``). Everything else in the
app imports SDK objects from here so that it does not care which SDK is loaded.

The two SDKs share an API surface; the differences handled here are naming only
(``log_stream`` → ``agent_stream``, ``galileo_logger=`` → ``splunk_ao_logger=``,
``GalileoScorers`` → ``SplunkAOEvaluators``).
"""
from __future__ import annotations

import os
from typing import Any, Optional

_SPLUNK_ALIASES = {"splunk_ao", "splunk-ao", "splunk", "sao"}

BACKEND = (os.environ.get("OBSERVABILITY_BACKEND") or "galileo").strip().lower()
IS_SPLUNK_AO = BACKEND in _SPLUNK_ALIASES
BACKEND_LABEL = "Splunk Agent Observability" if IS_SPLUNK_AO else "Galileo"

if IS_SPLUNK_AO:
    from splunk_ao import SplunkAOLogger as Logger
    from splunk_ao import splunk_ao_context as context
    from splunk_ao import SplunkAOEvaluators as _Evaluators
    from splunk_ao.handlers.langchain import SplunkAOCallback as _Callback
    from splunk_ao.experiments import run_experiment
    from splunk_ao.datasets import get_dataset, create_dataset, list_datasets
    from splunk_ao.projects import Projects
    from splunk_ao.agent_streams import get_agent_stream as _get_stream
else:
    from galileo import GalileoLogger as Logger
    from galileo import galileo_context as context
    from galileo.handlers.langchain import GalileoCallback as _Callback
    from galileo.experiments import run_experiment
    from galileo.datasets import get_dataset, create_dataset, list_datasets
    from galileo.projects import Projects
    from galileo.log_streams import get_log_stream as _get_stream

    _Evaluators = None


def make_logger(
    *,
    project: Optional[str] = None,
    project_id: Optional[str] = None,
    stream: Optional[str] = None,
    stream_id: Optional[str] = None,
):
    """Create a logger for a project and log stream / agent stream."""
    kwargs: dict[str, Any] = {}
    if project:
        kwargs["project"] = project
    if project_id:
        kwargs["project_id"] = project_id
    stream_key = "agent_stream" if IS_SPLUNK_AO else "log_stream"
    if stream:
        kwargs[stream_key] = stream
    if stream_id:
        kwargs[f"{stream_key}_id"] = stream_id
    return Logger(**kwargs)


def make_langchain_callback(logger, **kwargs):
    """Create the LangChain callback handler bound to ``logger``."""
    return _Callback(logger, **kwargs)


def get_stream(*, name: str, project_name: Optional[str] = None, project_id: Optional[str] = None):
    """Look up a log stream (Galileo) / agent stream (Splunk AO) by name."""
    kwargs: dict[str, Any] = {"name": name}
    if project_id:
        kwargs["project_id"] = project_id
    elif project_name:
        kwargs["project_name"] = project_name
    return _get_stream(**kwargs)


def convert_metrics(metrics: list) -> list:
    """Map galileo_core ScorerName values to the active SDK's evaluator enum."""
    if not IS_SPLUNK_AO or _Evaluators is None:
        return metrics
    converted = []
    for metric in metrics:
        name = getattr(metric, "name", None)
        if name and name in _Evaluators.__members__:
            converted.append(_Evaluators[name])
        else:
            converted.append(getattr(metric, "value", metric))
    return converted


def splunk_ao_console_url() -> str:
    """Realm-derived Splunk Observability Cloud console URL (no trailing slash)."""
    realm = (os.environ.get("SPLUNK_AO_REALM") or "").strip()
    return f"https://app.{realm}.observability.splunkcloud.com" if realm else ""
