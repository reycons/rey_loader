"""What this application tells bootstrap about itself.

Identity and the surface this application allows to be invoked. Installing the
distribution is what makes it discoverable; this is what it publishes once it
is.

**One source.** An entry for this application left behind in an installation's
external registry is legacy data. It is not merged, is not a fallback and cannot
override what is here, so a command dropped from this file is gone rather than
preserved by a stale copy.

**Not configuration.** Where the application is checked out, whether an
installation enables it and where it logs are that installation's answers, held
in its ``apps:`` declaration. A registration carrying them would let a package
decide something about an installation it has never seen.

``workflow_operations`` is the approved surface a workflow may invoke. It is
empty here: which operations this application approves is decided when the
coordinator begins dispatching through them, and an application that has
published nothing has approved nothing.
"""

from __future__ import annotations

from typing import Any

__all__ = ["APPLICATION_NAME", "get_registration"]

#: The registered identity. One value, matched against the installation's own
#: declaration; a disagreement is refused rather than reconciled.
APPLICATION_NAME = "rey_loader"

#: The command-line surface this application exposes, as an assembler of a
#: pipeline step reads it.
CLI: dict[str, Any] = {   'shared_parameters': [   {   'name': 'config-path',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Path to an app config '
                                                'file or installation '
                                                'config root.'},
                             {   'name': 'config-dir',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Directory containing '
                                                'config.<env>.yaml '
                                                '(overrides '
                                                'APP_CONFIG_DIR).'},
                             {   'name': 'set',
                                 'required': False,
                                 'repeatable': True,
                                 'value_type': 'KEY=VALUE',
                                 'description': 'Override an environment '
                                                'variable for this run.'},
                             {   'name': 'pipeline-name',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Pipeline name supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-run-id',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Unique pipeline run '
                                                'identifier supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-step-name',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Pipeline step name '
                                                'supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-step-id',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Optional unique pipeline '
                                                'step identifier.'},
                             {   'name': 'log-file',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Shared pipeline JSONL log '
                                                'path.'},
                             {   'name': 'ctx-file',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Pipeline step ctx '
                                                'snapshot (JSON); mutually '
                                                'exclusive with '
                                                'config-path.'}],
    'parameters': [   {   'name': 'command',
                          'required': False,
                          'value_type': 'choice',
                          'possible_values': [   'run-workflow',
                                                 'transform',
                                                 'load',
                                                 'all',
                                                 'sql'],
                          'positional': True,
                          'description': 'Public command, or run-workflow '
                                         'with --workflow.'},
                      {   'name': 'workflow',
                          'required': False,
                          'value_type': 'choice',
                          'possible_values_from': 'workflows',
                          'description': "Workflow name under 'workflows' "
                                         'in rey_loader config (with '
                                         'run-workflow).'},
                      {   'name': 'source',
                          'required': False,
                          'value_type': 'string',
                          'description': 'For sql / sql_apply workflow, '
                                         'the sql_step name.'},
                      {   'name': 'dry-run',
                          'required': False,
                          'value_type': 'flag',
                          'description': 'Skip database/file-mutating '
                                         'steps (load-files, sql-apply).'}]}


def get_registration() -> dict[str, Any]:
    """Return this application's registration.

    Returns:
        Identity, entry point and published capability.
    """
    return {
        "name": APPLICATION_NAME,
        "entry_point": "main.py",
        "cli": CLI,
        "workflow_operations": [],
    }
