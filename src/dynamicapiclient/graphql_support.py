"""GraphQL schema parsing, binding discovery, and operation documents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dynamicapiclient.exceptions import DynamicAPIClientConfigurationError, DynamicAPIClientModelError, DynamicAPIClientSpecError
from dynamicapiclient.routing import ModelBindings

if TYPE_CHECKING:
    from graphql.type.definition import (
        GraphQLArgument,
        GraphQLField,
        GraphQLInputObjectType,
        GraphQLObjectType,
    )
    from graphql.type.schema import GraphQLSchema

try:
    from graphql import build_schema
    from graphql.error import GraphQLError
    from graphql.type import get_named_type
    from graphql.type.definition import (
        GraphQLEnumType,
        GraphQLInputObjectType,
        GraphQLList,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLScalarType,
    )
    from graphql.utilities import build_client_schema
except ImportError:  # pragma: no cover
    build_schema = None  # type: ignore[assignment]
    build_client_schema = None  # type: ignore[assignment]
    GraphQLError = Exception  # type: ignore[misc,assignment]


def require_graphql() -> None:
    if build_schema is None:
        raise DynamicAPIClientConfigurationError(
            "GraphQL support requires the graphql-core package. Install with: pip install 'dynamicapiclient[graphql]'"
        )


def parse_graphql_schema(text: str) -> GraphQLSchema:
    require_graphql()
    raw = text.strip()
    if not raw:
        raise DynamicAPIClientSpecError("GraphQL schema document is empty.")
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise DynamicAPIClientSpecError(f"Invalid JSON (expected GraphQL introspection): {e}") from e
        if not isinstance(data, dict):
            raise DynamicAPIClientSpecError("GraphQL introspection JSON must be an object.")
        inner = data.get("data") if "data" in data else data
        if not isinstance(inner, dict) or "__schema" not in inner:
            raise DynamicAPIClientSpecError(
                "GraphQL introspection JSON must contain '__schema' (or wrap it in {\"data\": {...}})."
            )
        try:
            return build_client_schema(inner)  # type: ignore[misc]
        except Exception as e:
            raise DynamicAPIClientSpecError(f"Invalid GraphQL introspection payload: {e}") from e
    try:
        return build_schema(raw)  # type: ignore[misc]
    except GraphQLError as e:  # type: ignore[misc]
        raise DynamicAPIClientSpecError(f"Invalid GraphQL SDL: {e}") from e
    except Exception as e:
        raise DynamicAPIClientSpecError(f"Invalid GraphQL SDL: {e}") from e


def _type_to_variable_type_sdl(gql_type: Any) -> str:
    if isinstance(gql_type, GraphQLNonNull):
        return f"{_type_to_variable_type_sdl(gql_type.of_type)}!"
    if isinstance(gql_type, GraphQLList):
        return f"[{_type_to_variable_type_sdl(gql_type.of_type)}]"
    return gql_type.name


def _named(t: Any) -> Any:
    return get_named_type(t)  # type: ignore[misc]


def _list_element_type(t: Any) -> Any | None:
    cur = t
    if isinstance(cur, GraphQLNonNull):
        cur = cur.of_type
    if isinstance(cur, GraphQLList):
        return _named(cur.of_type)
    return None


def _scalar_selection_lines(gql_object: GraphQLObjectType) -> list[str]:
    lines: list[str] = []
    for fname, f in gql_object.fields.items():
        nt = _named(f.type)
        if isinstance(nt, (GraphQLScalarType, GraphQLEnumType)):
            lines.append(fname)
        elif nt.name in ("String", "Int", "Float", "Boolean", "ID"):
            lines.append(fname)
    return sorted(lines)


def _scalar_selection(gql_object: GraphQLObjectType) -> str:
    return " ".join(_scalar_selection_lines(gql_object))


def _input_to_json_schema(inp: GraphQLInputObjectType) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for fname, f in inp.fields.items():
        nt = _named(f.type)
        props[fname] = _graphql_type_to_json_schema_fragment(f.type, nt)
        if isinstance(f.type, GraphQLNonNull):
            required.append(fname)
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def _object_output_schema(obj: GraphQLObjectType) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for fname, f in obj.fields.items():
        nt = _named(f.type)
        if isinstance(nt, (GraphQLScalarType, GraphQLEnumType)):
            props[fname] = _graphql_type_to_json_schema_fragment(f.type, nt)
            if isinstance(f.type, GraphQLNonNull):
                required.append(fname)
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def _graphql_type_to_json_schema_fragment(wrapping: Any, named_t: Any) -> dict[str, Any]:
    if isinstance(named_t, GraphQLEnumType):
        return {"type": "string"}
    if isinstance(named_t, GraphQLScalarType):
        n = named_t.name
        if n in ("Int",):
            return {"type": "integer"}
        if n in ("Float",):
            return {"type": "number"}
        if n in ("Boolean",):
            return {"type": "boolean"}
        return {"type": "string"}
    return {"type": "string"}


def _unwrap_return_type(field_type: Any) -> Any:
    return _named(field_type)


def _author_like_path(
    return_obj: GraphQLObjectType,
    target: GraphQLObjectType,
) -> tuple[GraphQLObjectType, tuple[str, ...]]:
    if return_obj == target:
        return target, ()
    for subname, subf in return_obj.fields.items():
        st = _unwrap_return_type(subf.type)
        if st == target:
            return target, (subname,)
    return return_obj, ()


def _model_object_types(schema: GraphQLSchema) -> list[GraphQLObjectType]:
    out: list[GraphQLObjectType] = []
    skip_root = {"Query", "Mutation", "Subscription"}
    for name, t in schema.type_map.items():
        if name.startswith("__") or name in skip_root:
            continue
        if not isinstance(t, GraphQLObjectType):
            continue
        if not t.fields:
            continue
        out.append(t)
    return sorted(out, key=lambda x: x.name)


def _is_boring_object(t: GraphQLObjectType) -> bool:
    """Heuristic: types that look like API entities (have at least one scalar field)."""
    for _, f in t.fields.items():
        nt = _named(f.type)
        if isinstance(nt, (GraphQLScalarType, GraphQLEnumType)):
            return True
    return False


@dataclass
class GraphQLModelRuntime:
    """Per-model GraphQL operation templates and validation schemas."""

    graphql_path: str
    type_name: str
    selection: str
    object_schema: dict[str, Any]
    create_document: str | None = None
    create_field_name: str | None = None
    create_var_key: str = "input"
    create_input_schema: dict[str, Any] = field(default_factory=dict)
    create_result_path: tuple[str, ...] = ()

    get_document: str | None = None
    get_field_name: str | None = None
    get_id_arg: str = "id"
    get_result_path: tuple[str, ...] = ()

    list_field: str | None = None
    list_result_path: tuple[str, ...] = ()
    list_arg_types: dict[str, Any] = field(default_factory=dict)
    list_arg_sdls: dict[str, str] = field(default_factory=dict)

    update_document: str | None = None
    update_field_name: str | None = None
    update_var_key: str = "input"
    update_input_schema: dict[str, Any] = field(default_factory=dict)
    update_id_arg: str = "id"
    update_result_path: tuple[str, ...] = ()

    delete_document: str | None = None
    delete_field_name: str | None = None
    delete_id_arg: str = "id"
    delete_result_path: tuple[str, ...] = ()


def navigate_graphql_payload(node: Any, path: tuple[str, ...]) -> Any:
    cur = node
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            raise DynamicAPIClientModelError(f"GraphQL response missing key {k!r} at path {path!r}.")
        cur = cur[k]
    return cur


def coerce_graphql_variable(gql_type: Any, value: Any) -> Any:
    nt = _named(gql_type)
    if getattr(nt, "name", None) == "ID":
        return str(value)
    return value


def build_list_query_document(
    field_name: str,
    selection: str,
    params: dict[str, Any],
    arg_sdls: dict[str, str],
    arg_types: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if not params:
        return f"query {{ {field_name} {{ {selection} }} }}", {}
    allowed = set(arg_sdls)
    bad = set(params) - allowed
    if bad:
        raise DynamicAPIClientModelError(
            f"Unknown GraphQL arguments for list field {field_name!r}: {', '.join(sorted(bad))}. "
            f"Allowed: {', '.join(sorted(allowed)) or '(none)'}"
        )
    var_defs: list[str] = []
    vars_out: dict[str, Any] = {}
    args_call: list[str] = []
    for pname in sorted(params):
        var_defs.append(f"${pname}: {arg_sdls[pname]}")
        vars_out[pname] = coerce_graphql_variable(arg_types[pname], params[pname])
        args_call.append(f"{pname}: ${pname}")
    doc = (
        f"query({', '.join(var_defs)}) {{ {field_name}({', '.join(args_call)}) {{ {selection} }} }}"
    )
    return doc, vars_out


def graphql_execute_data(
    client: Any,
    path: str,
    document: str,
    variables: dict[str, Any] | None,
) -> dict[str, Any]:
    data = client.post_graphql(path, document, variables=variables)
    if not isinstance(data, dict):
        raise DynamicAPIClientModelError("GraphQL response data is not an object.")
    return data


def build_runtime_for_type(
    schema: GraphQLSchema,
    target: GraphQLObjectType,
    graphql_path: str,
) -> GraphQLModelRuntime | None:
    if not _is_boring_object(target):
        return None
    q = schema.query_type
    m = schema.mutation_type
    sel = _scalar_selection(target)
    if not sel.strip():
        return None

    runtime = GraphQLModelRuntime(
        graphql_path=graphql_path,
        type_name=target.name,
        selection=sel,
        object_schema=_object_output_schema(target),
    )

    tname = target.name
    lc_first = tname[:1].lower() + tname[1:] if tname else tname
    plural = lc_first + "s" if not lc_first.endswith("s") else lc_first

    # --- list query ---
    if q:
        for fname, field in q.fields.items():
            elt = _list_element_type(field.type)
            if elt and elt.name == tname:
                runtime.list_field = fname
                runtime.list_result_path = ()
                runtime.list_arg_types = {n: a.type for n, a in field.args.items()}
                runtime.list_arg_sdls = {
                    n: _type_to_variable_type_sdl(a.type) for n, a in field.args.items()
                }
                break
        if runtime.list_field is None:
            for fname, field in q.fields.items():
                if fname.lower() == plural.lower() or fname.lower() == lc_first + "s":
                    elt = _list_element_type(field.type)
                    if elt and elt.name == tname:
                        runtime.list_field = fname
                        runtime.list_arg_types = {n: a.type for n, a in field.args.items()}
                        runtime.list_arg_sdls = {
                            n: _type_to_variable_type_sdl(a.type) for n, a in field.args.items()
                        }
                        break

    # --- get query ---
    if q:
        for fname, field in q.fields.items():
            rt = _unwrap_return_type(field.type)
            if not isinstance(rt, GraphQLObjectType) or rt.name != tname:
                continue
            id_candidates = ("id", f"{lc_first}Id", f"{tname[:1].lower()}{tname[1:]}Id")
            for cand in id_candidates:
                if cand in field.args and _named(field.args[cand].type).name == "ID":
                    runtime.get_document = (
                        f"query($id: ID!) {{ {fname}({cand}: $id) {{ {sel} }} }}"
                    )
                    runtime.get_field_name = fname
                    runtime.get_id_arg = cand
                    _, path_p = _author_like_path(rt, target)
                    runtime.get_result_path = path_p
                    break
            if runtime.get_document:
                break

    # --- create / update mutations (payload includes object type) ---
    if m:
        for fname, field in m.fields.items():
            rt_obj = _unwrap_return_type(field.type)
            if not isinstance(rt_obj, GraphQLObjectType):
                continue
            inner_target, subpath = _author_like_path(rt_obj, target)
            if inner_target.name != tname:
                continue
            lname = fname.lower()
            input_arg_name: str | None = None
            input_type_obj: GraphQLInputObjectType | None = None
            for aname, arg in field.args.items():
                at = _named(arg.type)
                if isinstance(at, GraphQLInputObjectType):
                    input_arg_name = aname
                    input_type_obj = at
                    break
            if (
                runtime.create_document is None
                and (lname.startswith("create") or lname.startswith("add"))
                and input_arg_name
                and input_type_obj
            ):
                in_sdl = _type_to_variable_type_sdl(field.args[input_arg_name].type)
                runtime.create_document = (
                    f"mutation(${input_arg_name}: {in_sdl}) "
                    f"{{ {fname}({input_arg_name}: ${input_arg_name}) {{ {sel} }} }}"
                )
                runtime.create_field_name = fname
                runtime.create_var_key = input_arg_name
                runtime.create_input_schema = _input_to_json_schema(input_type_obj)
                runtime.create_result_path = subpath
            elif (
                runtime.update_document is None
                and (lname.startswith("update") or lname.startswith("edit"))
                and input_arg_name
                and input_type_obj
            ):
                id_arg = None
                for cand in ("id", f"{lc_first}Id"):
                    if cand in field.args and _named(field.args[cand].type).name == "ID":
                        id_arg = cand
                        break
                if id_arg:
                    in_sdl = _type_to_variable_type_sdl(field.args[input_arg_name].type)
                    id_sdl = _type_to_variable_type_sdl(field.args[id_arg].type)
                    runtime.update_document = (
                        f"mutation($id: {id_sdl}, ${input_arg_name}: {in_sdl}) "
                        f"{{ {fname}({id_arg}: $id, {input_arg_name}: ${input_arg_name}) {{ {sel} }} }}"
                    )
                    runtime.update_field_name = fname
                    runtime.update_var_key = input_arg_name
                    runtime.update_id_arg = id_arg
                    runtime.update_input_schema = _input_to_json_schema(input_type_obj)
                    runtime.update_result_path = subpath

        # delete mutations (often return Boolean)
        for fname, field in m.fields.items():
            lname = fname.lower()
            if not (lname.startswith("delete") or lname.startswith("remove")):
                continue
            if tname.lower() not in lname and lc_first.lower() not in lname:
                continue
            id_arg = None
            for cand in ("id", f"{lc_first}Id"):
                if cand in field.args and _named(field.args[cand].type).name == "ID":
                    id_arg = cand
                    break
            if id_arg and runtime.delete_document is None:
                id_sdl = _type_to_variable_type_sdl(field.args[id_arg].type)
                runtime.delete_document = f"mutation($id: {id_sdl}) {{ {fname}({id_arg}: $id) }}"
                runtime.delete_field_name = fname
                runtime.delete_id_arg = id_arg
                runtime.delete_result_path = ()
                break

    if not (
        runtime.create_document
        or runtime.get_document
        or runtime.list_field
        or runtime.update_document
        or runtime.delete_document
    ):
        return None
    return runtime


def build_graphql_model_classes(
    schema: GraphQLSchema,
    *,
    graphql_path: str,
    http_client: Any,
) -> dict[str, type]:
    from dynamicapiclient.api import _sanitize_identifier
    from dynamicapiclient.models import Manager

    registry: dict[str, type] = {}
    for obj_t in _model_object_types(schema):
        rt = build_runtime_for_type(schema, obj_t, graphql_path)
        if rt is None:
            continue
        model_cls = type(
            obj_t.name,
            (),
            {
                "__module__": "dynamicapiclient.dynamic",
                "_dynamicapiclient_kind": "graphql",
                "_dynamicapiclient_schema": rt.object_schema,
                "_dynamicapiclient_bindings": ModelBindings(),
                "_dynamicapiclient_client": http_client,
                "_dynamicapiclient_graphql": rt,
                "__doc__": f"Dynamic model for GraphQL type {obj_t.name!r}.",
            },
        )
        model_cls.objects = Manager(model_cls)
        safe = _sanitize_identifier(obj_t.name)
        if safe in registry:
            other = getattr(registry[safe], "__name__", safe)
            raise DynamicAPIClientSpecError(
                f"GraphQL types {other!r} and {obj_t.name!r} both map to model attribute {safe!r}."
            )
        registry[safe] = model_cls
    if not registry:
        raise DynamicAPIClientSpecError(
            "No GraphQL object types with inferrable Query/Mutation fields were found. "
            "Define list/get/create/update/delete fields using conventional names (e.g. authors, author, createAuthor)."
        )
    return registry


def looks_like_graphql_sdl(text: str) -> bool:
    t = text.lstrip()
    if not t:
        return False
    if t.startswith("{") and ("__schema" in t[:20000] or '"__schema"' in t[:20000]):
        return True
    if re.search(r"^\s*schema\s*\{", t, re.MULTILINE):
        return True
    # SDL: `type Name {` / `input Name {` — avoid matching YAML `type: object`
    return bool(
        re.search(
            r"^\s*(type|input|extend)\s+[A-Za-z_]\w*\s*\{",
            t,
            re.MULTILINE,
        )
    )
