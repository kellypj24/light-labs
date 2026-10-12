"""Guts Man's model-building prompt and output cleaning. Shared by the robot and the evals."""

import re

_FENCE = re.compile(r"```(?:sql|jinja|sql\+jinja)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def model_prompt(target, task, upstream):
    """User prompt for one model. `upstream` is a list of
    {"name", "description", "columns": [{"name", "type", "description"}]}."""
    blocks = []
    for model in upstream:
        cols = "\n".join(
            f"- {c['name']} {c['type']}" + (f": {c['description']}" if c.get("description") else "")
            for c in model["columns"]
        )
        # Shown as the exact ref() call: small models copy bare names into FROM clauses.
        ref = "{{ ref('" + model["name"] + "') }}"
        blocks.append(f"### {ref}\n{model.get('description') or ''}\n{cols}".strip())
    example = "{{ ref('" + upstream[0]["name"] + "') }}"
    return (
        f"Write the dbt model `{target}`.\n\nTask: {task.strip()}\n\n"
        "Upstream models. Select from each exactly as its heading shows, "
        f"for example FROM {example}:\n\n" + "\n\n".join(blocks) + "\n\n"
        f"Return only the SQL for models/{target}.sql."
    )


def extract_sql(text):
    """The model's SQL: the first fenced block if there is one, without a final semicolon."""
    match = _FENCE.search(text)
    sql = (match.group(1) if match else text).strip()
    return sql.rstrip(";").rstrip()
